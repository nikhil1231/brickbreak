import React, { useEffect, useState } from 'react';
import { fetchHypotheses, fetchProviders, runExploration } from '../../services/api';
import { ExplorationResult, Hypothesis, ProviderCatalogue, Suggestion } from '../../types';
import { SuggestionDeck } from './SuggestionDeck';
import { ExplorationStatus } from './ExplorationStatus';
import { Badge } from '../common/Badge';
import { MetricBox } from '../common/MetricBox';
import {
  Paper,
  Text,
  TextInput,
  Textarea,
  Select,
  Button,
  SimpleGrid,
  Group,
  Stack,
  Alert,
  Code,
  List,
  ThemeIcon,
  Box,
  Badge as MantineBadge,
  SegmentedControl,
} from '@mantine/core';
import {
  IconPlayerPlay,
  IconArrowRight,
  IconHash,
  IconAlertCircle,
  IconSparkles,
} from '@tabler/icons-react';

export const ExploreConsole: React.FC = () => {
  const [mode, setMode] = useState<'new' | 'continue'>('new');
  const [hypId, setHypId] = useState<string>('');
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([]);
  const [question, setQuestion] = useState<string>('');
  const [signalName, setSignalName] = useState<string>('');
  const [partition, setPartition] = useState<string>('train');
  const [provider, setProvider] = useState<string>('claude');
  const [model, setModel] = useState<string>('');
  const [providers, setProviders] = useState<ProviderCatalogue | null>(null);
  const [providerError, setProviderError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [result, setResult] = useState<ExplorationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [launchingIds, setLaunchingIds] = useState<string[]>([]);
  const [inboxReload, setInboxReload] = useState<number>(0);

  useEffect(() => {
    const controller = new AbortController();

    // Existing hypotheses are available as lineage parents and for the
    // explicit "continue existing" workflow. New ideas remain the default.
    fetchHypotheses(controller.signal)
      .then((hyps) => {
        setHypotheses(hyps);
        const preferred = hyps.find((item) => item.id === 'H026') || hyps[0];
        if (preferred) {
          setHypId(preferred.id);
        }
      })
      .catch((err: Error) => {
        if (err.name !== 'AbortError') {
          setError(`Could not load the hypothesis ledger: ${err.message}`);
        }
      });

    // Fetch LLM providers
    fetchProviders(controller.signal)
      .then((catalogue) => {
        setProviders(catalogue);
        const preferred =
          catalogue.providers.find((item) => item.id === catalogue.default_provider && item.available) ||
          catalogue.providers.find((item) => item.available);
        if (preferred) {
          setProvider(preferred.id);
          setModel(preferred.default_model || '');
        }
      })
      .catch((err: Error) => {
        // Unmounting aborts these fetches. Reporting that as a provider
        // failure put "signal is aborted without reason" under the picker.
        if (err.name !== 'AbortError') {
          setProviderError(err.message);
        }
      });

    return () => controller.abort();
  }, []);

  const selectedProvider = providers?.providers.find((item) => item.id === provider);
  const selectedHypothesis = hypotheses.find((item) => item.id === hypId);
  const hypothesisChoices = hypotheses.map((item) => ({
    value: item.id,
    label: `${item.id} — ${item.title}`,
  }));
  const providerChoices = (providers?.providers || []).map((item) => ({
    value: item.id,
    label: `${item.label}${item.available ? '' : ' (not installed)'}`,
    disabled: !item.available,
  }));
  const modelChoices = (selectedProvider?.models || []).map((item) => ({
    value: item.id || '__default__',
    label: item.label,
  }));

  const handleLaunch = async () => {
    if (mode === 'continue' && !selectedHypothesis) {
      setError('Choose a registered hypothesis before launching an exploration.');
      return;
    }
    if (!question.trim()) {
      setError(mode === 'new' ? 'Write a testable hypothesis.' : 'Provide an exploration question.');
      return;
    }
    setLoading(true);
    setError(null);
    setInboxReload((n) => n + 1);
    try {
      if (mode === 'new') {
        const res = await runExploration({
          idea: question.trim(),
          hypothesis_id: '',
          question: '',
          signal_name: '',
          partition: 'train',
          provider,
          model: model || undefined,
        });
        setResult(res);
        setHypId(res.hypothesis_id);
        setMode('continue');
        setSignalName(res.signal_name);
        try {
          setHypotheses(await fetchHypotheses());
        } catch {
          /* the new entry is durable; refresh on next mount */
        }
      } else {
        const res = await runExploration({
          hypothesis_id: hypId,
          question,
          signal_name: signalName || `${hypId.toLowerCase()}_signal`,
          partition,
          provider,
          model: model || undefined,
        });
        setResult(res);
      }
    } catch (err: any) {
      if (mode === 'new' && err.hypothesisId) {
        setHypId(err.hypothesisId);
        setMode('continue');
        try {
          setHypotheses(await fetchHypotheses());
        } catch {
          /* the registered entry appears on the next refresh */
        }
        setError(`${err.hypothesisId} was registered, but its first exploration failed: ${err.message}`);
      } else {
        setError(err.message || 'Exploration failed');
      }
    } finally {
      setLoading(false);
      setInboxReload((n) => n + 1);
    }
  };

  // Playing a suggestion dispatches it and then leaves it alone. The form is
  // deliberately untouched: the run is already under way, so pre-filling the
  // box with its question invites launching the same thing twice, and the
  // Explorations list is where its progress belongs. Several can be in
  // flight at once — the server runs each in its own thread.
  const handlePlaySuggestion = async (suggestion: Suggestion) => {
    setLaunchingIds((ids) => [...ids, suggestion.id]);
    setError(null);
    setInboxReload((n) => n + 1);
    try {
      const res = await runExploration({
        hypothesis_id: suggestion.hypothesis_id || '',
        suggestion_id: suggestion.id,
        question: suggestion.question,
        signal_name: suggestion.signal_name,
        partition,
        provider,
        model: model || undefined,
      });
      setResult(res);
      try {
        setHypotheses(await fetchHypotheses());
      } catch {
        /* the exploration still ran; the picker refreshes on next mount */
      }
    } catch (err: any) {
      setError(err.message || 'Exploration failed');
    } finally {
      setLaunchingIds((ids) => ids.filter((id) => id !== suggestion.id));
      setInboxReload((n) => n + 1);
    }
  };

  const pc = result?.evaluation?.predictive_content?.primary_ic;
  const q = result?.evaluation?.quantiles;

  return (
    <Box p="xl" style={{ maxWidth: '1200px', margin: '0 auto' }}>
      {/* Hero Exploration Form */}
      <Paper
        p="xl"
        radius="lg"
        mb="xl"
        bg="#161b22"
        style={{
          border: '1px solid var(--border)',
          boxShadow: '0 8px 30px rgba(0, 0, 0, 0.4)',
        }}
      >
        <Group justify="space-between" align="center" mb="lg">
          <Group gap="sm">
            <ThemeIcon size="lg" radius="md" variant="gradient" gradient={{ from: 'blue.5', to: 'cyan.4', deg: 135 }}>
              <IconSparkles size={18} />
            </ThemeIcon>
            <div>
              <Text size="lg" fw={700} c="white" style={{ letterSpacing: '-0.02em' }}>
                {mode === 'new' ? 'Explore a New Hypothesis' : 'Continue Existing Research'}
              </Text>
              <Text size="xs" c="dimmed">
                {mode === 'new'
                  ? 'Describe the idea; planning infers the research design and registers it.'
                  : 'Keep the durable hypothesis unchanged and ask a narrower follow-up question.'}
              </Text>
            </div>
          </Group>

          <SegmentedControl
            size="xs"
            value={mode}
            data={[
              { label: 'New hypothesis', value: 'new' },
              { label: 'Continue existing', value: 'continue' },
            ]}
            onChange={(value) => {
              const nextMode = value as 'new' | 'continue';
              setMode(nextMode);
              setError(null);
              setResult(null);
              if (nextMode === 'new') {
                setQuestion('');
                setSignalName('');
              } else if (selectedHypothesis) {
                setQuestion(selectedHypothesis.statement);
                setSignalName(`${selectedHypothesis.id.toLowerCase()}_signal`);
              }
            }}
          />
        </Group>

        {/* Hero Input Element */}
        <Stack gap="md">
          {mode === 'continue' && (
            <>
              <Select
                label="Registered hypothesis"
                description="Selecting an entry does not edit its durable statement."
                placeholder="Choose a registered hypothesis"
                searchable
                value={hypId || null}
                data={hypothesisChoices}
                onChange={(value) => {
                  const next = hypotheses.find((item) => item.id === value);
                  if (!next) return;
                  setHypId(next.id);
                  setQuestion(next.statement);
                  setSignalName(`${next.id.toLowerCase()}_signal`);
                }}
              />
              {selectedHypothesis && (
                <Paper p="md" radius="md" bg="#0d1117" style={{ border: '1px solid var(--border)' }}>
                  <Group justify="space-between" mb="xs">
                    <Text size="xs" fw={700} tt="uppercase" c="dimmed">Durable hypothesis — read only</Text>
                    <Group gap="xs">
                      <MantineBadge color="gray" variant="light">{selectedHypothesis.family}</MantineBadge>
                      <MantineBadge color="blue" variant="light">{selectedHypothesis.status}</MantineBadge>
                    </Group>
                  </Group>
                  <Text size="sm" c="white">{selectedHypothesis.statement}</Text>
                  <Text size="xs" c="dimmed" mt="xs">{selectedHypothesis.rationale}</Text>
                </Paper>
              )}
            </>
          )}

          <Textarea
            label={mode === 'continue' ? 'Exploration question' : undefined}
            description={mode === 'continue'
              ? 'You may narrow the experiment here; the hypothesis above remains unchanged.'
              : undefined}
            placeholder={mode === 'new'
              ? 'e.g. Does volume dry-up during consolidation predict stronger breakouts?'
              : 'What additional aspect of this hypothesis should this run test?'}
            minRows={mode === 'new' ? 7 : 4}
            autosize
            maxRows={10}
            value={question}
            onChange={(e) => setQuestion(e.currentTarget.value)}
            styles={{
              input: {
                fontSize: '16px',
                lineHeight: '1.6',
                padding: '16px 18px',
                background: '#0d1117',
                border: '1px solid var(--border)',
                borderRadius: '8px',
                color: '#ffffff',
                transition: 'border-color 0.2s ease, box-shadow 0.2s ease',
              },
            }}
          />

          {/* Secondary Controls Grid */}
          <SimpleGrid cols={{ base: 1, sm: 2, md: mode === 'new' ? 2 : 4 }} spacing="md" mt="xs">
            {mode === 'continue' && (
              <TextInput
                label="Signal Name"
                size="xs"
                value={signalName}
                onChange={(e) => setSignalName(e.currentTarget.value)}
              />
            )}
            {mode === 'continue' && (
              <Select
                label="Data Partition"
                size="xs"
                value={partition}
                onChange={(v) => setPartition(v || 'train')}
                data={[
                  { label: 'train (exploration)', value: 'train' },
                  { label: 'validation (intermediate tune)', value: 'validation' },
                  { label: 'test (shuffled holdout)', value: 'test' },
                  { label: 'forward (chronological live lane)', value: 'forward' },
                ]}
              />
            )}
            <Select
              label="LLM Provider"
              size="xs"
              value={provider}
              data={providerChoices}
              disabled={!providers}
              error={providerError}
              onChange={(value) => {
                const next = value || 'claude';
                setProvider(next);
                const option = providers?.providers.find((item) => item.id === next);
                setModel(option?.default_model || '');
              }}
            />
            <Select
              label="Model"
              size="xs"
              value={model || '__default__'}
              data={modelChoices}
              disabled={!selectedProvider?.available}
              onChange={(value) => setModel(value === '__default__' ? '' : (value || ''))}
            />
          </SimpleGrid>

          {/* Prominent Launch Button */}
          <Button
            leftSection={<IconPlayerPlay size={18} />}
            color="blue"
            size="lg"
            radius="md"
            mt="sm"
            fullWidth
            loading={loading}
            disabled={
              !selectedProvider?.available ||
              !question.trim() ||
              (mode === 'continue' && !selectedHypothesis)
            }
            onClick={handleLaunch}
            style={{
              fontWeight: 650,
              fontSize: '15px',
              letterSpacing: '0.01em',
              boxShadow: '0 4px 14px rgba(88, 166, 255, 0.25)',
            }}
          >
            {mode === 'new' ? 'Plan & Launch Exploration' : 'Launch Follow-up Exploration'}
          </Button>
        </Stack>
      </Paper>

      <ExplorationStatus reloadToken={inboxReload + launchingIds.length} />

      {/* The inbox proposes *new* hypotheses, so it belongs under the console
          in both modes — gating it behind "continue existing" hides it in the
          very view where a fresh idea is being chosen. */}
      <SuggestionDeck
        provider={provider}
        model={model}
        providerAvailable={!!selectedProvider?.available}
        reloadToken={inboxReload}
        onPlay={handlePlaySuggestion}
      />

      {error && (
        <Alert icon={<IconAlertCircle size={16} />} title="Exploration Failed" color="red" mb="lg" radius="md">
          {error}
        </Alert>
      )}

      {/* Results Section */}
      {result && (
        <Paper p="lg" radius="md">
          <Group justify="space-between" mb="sm">
            <Group gap="sm">
              <Text size="md" fw={700} c="white">
                Exploration Result ({result.hypothesis_id})
              </Text>
              <Badge status={result.failure_class} size="lg" />
            </Group>
            {result.runtime_seconds != null && (
              <Text size="xs" c="dimmed">
                {result.provider || result.manifest?.provider_used}/
                {result.model || result.manifest?.model_used || 'cli-default'} · Runtime: {result.runtime_seconds}s
              </Text>
            )}
          </Group>

          <Alert
            variant="light"
            color={result.failure_class === 'VALIDATED' || result.failure_class === 'PROMISSING' ? 'teal' : 'blue'}
            radius="md"
            mb="md"
          >
            <Text size="sm" fw={500}>
              {result.interpretation}
            </Text>
          </Alert>

          <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md" mb="md">
            <SimpleGrid cols={2} spacing="sm">
              <MetricBox
                label="Mean Rank IC"
                value={pc?.mean_ic != null ? pc.mean_ic.toFixed(4) : '—'}
                highlight={pc?.mean_ic != null && pc.mean_ic > 0.03 ? 'green' : 'none'}
              />
              <MetricBox
                label="IC t-statistic"
                value={pc?.t_stat != null ? pc.t_stat.toFixed(2) : '—'}
                highlight={pc?.t_stat != null && Math.abs(pc.t_stat) >= 2.0 ? 'green' : 'none'}
              />
              <MetricBox
                label="Q5 - Q1 Spread"
                value={q?.q5_spread_bps != null ? `${q.q5_spread_bps.toFixed(0)} bps` : '—'}
              />
              <MetricBox
                label="Monotonicity"
                value={q?.q5_monotonicity != null ? q.q5_monotonicity.toFixed(3) : '—'}
              />
            </SimpleGrid>

            <Stack gap="xs">
              <Group gap={6}>
                <IconHash size={14} color="var(--mantine-color-dimmed)" />
                <Text size="xs" fw={700} tt="uppercase" c="dimmed">
                  Immutable Manifest Hash
                </Text>
              </Group>
              <Code block style={{ fontSize: '11px', maxHeight: '140px', overflowY: 'auto' }}>
                {JSON.stringify(result.manifest, null, 2)}
              </Code>
            </Stack>
          </SimpleGrid>

          {/* Suggested Next Moves */}
          {result.suggested_next_moves && result.suggested_next_moves.length > 0 && (
            <Box mt="md" pt="md" style={{ borderTop: '1px solid var(--border)' }}>
              <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb="xs">
                Suggested Next Moves
              </Text>
              <List
                spacing="xs"
                size="sm"
                icon={
                  <ThemeIcon color="blue" size={18} radius="xl">
                    <IconArrowRight size={12} />
                  </ThemeIcon>
                }
              >
                {result.suggested_next_moves.map((m, idx) => (
                  <List.Item key={idx}>
                    <Text size="xs">
                      <strong style={{ color: 'var(--text-bright)' }}>{m.action}</strong>{' '}
                      <span style={{ color: 'var(--mantine-color-blue-4)' }}>({m.relation})</span>: {m.rationale}
                    </Text>
                  </List.Item>
                ))}
              </List>
            </Box>
          )}
        </Paper>
      )}
    </Box>
  );
};
