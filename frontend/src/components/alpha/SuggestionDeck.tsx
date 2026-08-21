import React, { useCallback, useEffect, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge as MantineBadge,
  Box,
  Button,
  Code,
  Divider,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  ThemeIcon,
  Tooltip,
} from '@mantine/core';
import {
  IconAlertTriangle,
  IconBulb,
  IconPlayerPlay,
  IconRefresh,
  IconRepeat,
} from '@tabler/icons-react';
import {
  fetchSuggestions,
  generateSuggestions,
  promoteSuggestion,
  refreshSuggestion,
} from '../../services/api';
import { Suggestion } from '../../types';
import { Modal } from '../common/Modal';

interface Props {
  provider: string;
  model: string;
  providerAvailable: boolean;
  /** Bumped by the parent after a launch so the deck re-reads the inbox. */
  reloadToken: number;
  /** Dispatches the exploration. The deck does not wait for it to finish. */
  onPlay: (suggestion: Suggestion) => void;
}

const SLOT_COUNT = 3;

/** One labelled paragraph of the detail view. */
const Field: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <Box>
    <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={4} style={{ letterSpacing: '0.05em' }}>
      {label}
    </Text>
    <Text size="sm" c="gray.3" style={{ lineHeight: 1.6 }}>
      {children}
    </Text>
  </Box>
);

export const SuggestionDeck: React.FC<Props> = ({
  provider,
  model,
  providerAvailable,
  reloadToken,
  onPlay,
}) => {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [proposedEver, setProposedEver] = useState<number>(0);
  const [loaded, setLoaded] = useState<boolean>(false);
  const [busySlot, setBusySlot] = useState<number | null>(null);
  const [generatingAll, setGeneratingAll] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [promotingId, setPromotingId] = useState<string | null>(null);

  // Reading the inbox is free — it does not call a model. Generating does,
  // which is why nothing here regenerates on mount.
  useEffect(() => {
    const controller = new AbortController();
    fetchSuggestions(controller.signal)
      .then((inbox) => {
        setSuggestions(inbox.suggestions);
        setProposedEver(inbox.n_proposed_ever);
        setLoaded(true);
      })
      .catch((err: Error) => {
        if (err.name !== 'AbortError') {
          setError(err.message);
          setLoaded(true);
        }
      });
    return () => controller.abort();
  }, [reloadToken]);

  const runGenerate = useCallback(
    async (slots: number[]) => {
      setError(null);
      try {
        const inbox = await generateSuggestions({
          provider,
          model: model || undefined,
          count: slots.length,
          slots,
        });
        setSuggestions(inbox.suggestions);
        setProposedEver(inbox.n_proposed_ever);
      } catch (err: any) {
        setError(err.message || 'Could not generate suggestions');
      }
    },
    [provider, model]
  );

  const handleGenerateAll = async () => {
    setGeneratingAll(true);
    await runGenerate([...Array(SLOT_COUNT).keys()]);
    setGeneratingAll(false);
  };

  const handleFillSlot = async (slot: number) => {
    setBusySlot(slot);
    await runGenerate([slot]);
    setBusySlot(null);
  };

  const handleRefreshOne = async (suggestion: Suggestion) => {
    setBusySlot(suggestion.slot);
    setError(null);
    if (openId === suggestion.id) setOpenId(null);
    try {
      const inbox = await refreshSuggestion({
        id: suggestion.id,
        provider,
        model: model || undefined,
      });
      setSuggestions(inbox.suggestions);
      setProposedEver(inbox.n_proposed_ever);
    } catch (err: any) {
      setError(err.message || 'Could not refresh that suggestion');
    } finally {
      setBusySlot(null);
    }
  };

  const handlePlay = async (suggestion: Suggestion) => {
    setPromotingId(suggestion.id);
    setError(null);
    setOpenId(null);
    try {
      // Register first, as its own step. The exploration then runs on the
      // server and the deck stops caring about it — refilling the slot before
      // the promotion landed would let the generator retire the very
      // suggestion being launched.
      const inbox = await promoteSuggestion({ id: suggestion.id });
      setSuggestions(inbox.suggestions);
      setProposedEver(inbox.n_proposed_ever);
      onPlay({ ...suggestion, hypothesis_id: inbox.hypothesis_id });
    } catch (err: any) {
      setError(err.message || 'Could not register that suggestion');
      setPromotingId(null);
      return;
    }
    setPromotingId(null);

    // The slot it vacated fills itself, so the inbox always holds three.
    if (providerAvailable) {
      setBusySlot(suggestion.slot);
      await runGenerate([suggestion.slot]);
      setBusySlot(null);
    }
  };

  const bySlot = (slot: number) => suggestions.find((s) => s.slot === slot);
  const slots = [...Array(SLOT_COUNT).keys()];
  // Deliberately does not include a running exploration. Once a suggestion is
  // registered the run belongs to the server and shows in the Explorations
  // list; blocking the inbox on it stopped the next idea being read or
  // dispatched for as long as the first one took.
  const anyBusy = generatingAll || busySlot !== null || promotingId !== null;
  const open = suggestions.find((s) => s.id === openId) || null;

  return (
    <Box mb="xl">
      <Group justify="space-between" align="flex-end" mb="sm">
        <Group gap="sm">
          <ThemeIcon size="lg" radius="md" variant="light" color="yellow">
            <IconBulb size={18} />
          </ThemeIcon>
          <div>
            <Text size="md" fw={700} c="white" style={{ letterSpacing: '-0.02em' }}>
              What to test next
            </Text>
            <Text size="xs" c="dimmed">
              Proposed against the whole ledger and the graveyard. Click one to read it.
              {proposedEver > 0 ? ` ${proposedEver} proposed so far.` : ''}
            </Text>
          </div>
        </Group>
        <Button
          size="xs"
          variant="light"
          color="yellow"
          leftSection={<IconRepeat size={14} />}
          loading={generatingAll}
          disabled={!providerAvailable || anyBusy}
          onClick={handleGenerateAll}
        >
          {suggestions.length > 0 ? 'Regenerate all three' : 'Suggest three experiments'}
        </Button>
      </Group>

      {error && (
        <Alert icon={<IconAlertTriangle size={16} />} color="red" radius="md" mb="sm" variant="light">
          {error}
        </Alert>
      )}

      <Stack gap="xs">
        {slots.map((slot) => {
          const suggestion = bySlot(slot);
          const busy = busySlot === slot || (generatingAll && !suggestion);

          if (!suggestion) {
            return (
              <Paper
                key={slot}
                p="md"
                radius="md"
                bg="transparent"
                style={{ border: '1px dashed var(--border)' }}
              >
                <Group justify="space-between">
                  <Text size="xs" c="dimmed">
                    {loaded ? `Slot ${slot + 1} is empty.` : 'Reading the inbox…'}
                  </Text>
                  <Button
                    size="compact-xs"
                    variant="subtle"
                    color="yellow"
                    loading={busy}
                    disabled={!providerAvailable || anyBusy || !loaded}
                    onClick={() => handleFillSlot(slot)}
                  >
                    Suggest one
                  </Button>
                </Group>
              </Paper>
            );
          }

          const launching = promotingId === suggestion.id;

          return (
            <Paper
              key={suggestion.id}
              p="md"
              radius="md"
              bg="#161b22"
              onClick={() => setOpenId(suggestion.id)}
              style={{
                border: '1px solid var(--border)',
                opacity: busy ? 0.55 : 1,
                cursor: 'pointer',
                transition: 'opacity 0.15s ease, border-color 0.15s ease',
              }}
            >
              <Group justify="space-between" align="center" wrap="nowrap" gap="md">
                <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
                  <Text size="sm" fw={600} c="gray.2" style={{ lineHeight: 1.5 }}>
                    {suggestion.title}
                  </Text>
                  {suggestion.warnings.length > 0 && (
                    <Tooltip label={suggestion.warnings.join(' · ')} multiline w={320}>
                      <ThemeIcon size="sm" radius="xl" variant="light" color="yellow">
                        <IconAlertTriangle size={11} />
                      </ThemeIcon>
                    </Tooltip>
                  )}
                </Group>

                <Group gap={6} wrap="nowrap" onClick={(e) => e.stopPropagation()}>
                  <Tooltip label="Register it and launch the exploration" position="left">
                    <ActionIcon
                      size="lg"
                      radius="md"
                      variant="filled"
                      color="blue"
                      loading={launching}
                      disabled={!providerAvailable || anyBusy}
                      onClick={() => handlePlay(suggestion)}
                      aria-label={`Launch ${suggestion.id}`}
                    >
                      <IconPlayerPlay size={16} />
                    </ActionIcon>
                  </Tooltip>
                  <Tooltip label="Replace this one with a new suggestion" position="left">
                    <ActionIcon
                      size="lg"
                      radius="md"
                      variant="subtle"
                      color="gray"
                      loading={busySlot === suggestion.slot}
                      disabled={!providerAvailable || anyBusy}
                      onClick={() => handleRefreshOne(suggestion)}
                      aria-label={`Refresh ${suggestion.id}`}
                    >
                      <IconRefresh size={16} />
                    </ActionIcon>
                  </Tooltip>
                </Group>
              </Group>
            </Paper>
          );
        })}
      </Stack>

      <Modal isOpen={!!open} onClose={() => setOpenId(null)} title={open?.title || ''} maxWidth="820px">
        {open && (
          <Stack gap="lg">
            <Group gap={6}>
              <MantineBadge size="sm" variant="light" color="gray" radius="sm">
                {open.family}
              </MantineBadge>
              {open.lineage.map((edge) => (
                <MantineBadge
                  key={`${edge.relation}-${edge.target_id}`}
                  size="sm"
                  variant="light"
                  color="blue"
                  radius="sm"
                >
                  {edge.relation} → {edge.target_id}
                </MantineBadge>
              ))}
              <MantineBadge size="sm" variant="outline" color="gray" radius="sm">
                {open.source === 'offline'
                  ? 'no model'
                  : `${open.source}${open.model ? `/${open.model}` : ''}`}
              </MantineBadge>
            </Group>

            <Text size="md" c="gray.1" style={{ lineHeight: 1.6 }}>
              {open.question}
            </Text>

            {open.warnings.length > 0 && (
              <Alert
                icon={<IconAlertTriangle size={16} />}
                color="yellow"
                variant="light"
                radius="md"
              >
                <Stack gap={4}>
                  {open.warnings.map((w, idx) => (
                    <Text key={idx} size="sm">
                      {w}
                    </Text>
                  ))}
                </Stack>
              </Alert>
            )}

            {open.rationale && <Field label="Mechanism">{open.rationale}</Field>}
            {open.novelty_note && <Field label="Why it is not a repeat">{open.novelty_note}</Field>}
            {open.evidence_basis && <Field label="What licensed it">{open.evidence_basis}</Field>}
            {open.expected_correlation && (
              <Field label="Expected overlap">{open.expected_correlation}</Field>
            )}

            <Divider color="var(--border)" />

            <Box>
              <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={6} style={{ letterSpacing: '0.05em' }}>
                Signal
              </Text>
              <Code style={{ fontSize: '12px' }}>{open.signal_name}</Code>
              {open.signal_sketch && (
                <Text size="sm" c="gray.3" mt={8} style={{ lineHeight: 1.6 }}>
                  {open.signal_sketch}
                </Text>
              )}
            </Box>

            <Field label="The bar it has to clear">
              {Object.entries(open.pass_criterion)
                .map(([k, v]) => `${k.replace('min_', '')} ≥ ${v}`)
                .join(' · ')}
              {` · horizons ${open.horizons.join('/')} sessions, primary ${open.primary_horizon}`}
            </Field>

            {open.falsification_condition && (
              <Field label="What would kill it">{open.falsification_condition}</Field>
            )}

            <Divider color="var(--border)" />

            <Group justify="flex-end" gap="sm">
              <Button
                variant="default"
                size="sm"
                leftSection={<IconRefresh size={16} />}
                disabled={!providerAvailable || anyBusy}
                onClick={() => handleRefreshOne(open)}
              >
                Replace this suggestion
              </Button>
              <Button
                size="sm"
                color="blue"
                leftSection={<IconPlayerPlay size={16} />}
                loading={promotingId === open.id}
                disabled={!providerAvailable || anyBusy}
                onClick={() => handlePlay(open)}
              >
                Register and launch
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>

      {!providerAvailable && loaded && (
        <Text size="xs" c="dimmed" mt="xs">
          No LLM provider is installed, so suggestions cannot be generated here.
        </Text>
      )}
      {!loaded && (
        <Group gap="xs" mt="xs">
          <Loader size="xs" />
          <Text size="xs" c="dimmed">
            Reading the research inbox…
          </Text>
        </Group>
      )}
    </Box>
  );
};
