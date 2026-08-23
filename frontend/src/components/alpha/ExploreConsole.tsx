import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  Checkbox,
  Code,
  Divider,
  Grid,
  Group,
  List,
  Paper,
  Progress,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Textarea,
  ThemeIcon,
} from '@mantine/core';
import {
  IconAlertTriangle,
  IconCheck,
  IconFlask,
  IconLock,
  IconRefresh,
  IconRobot,
  IconShieldCheck,
  IconSparkles,
} from '@tabler/icons-react';

import { fetchProviders } from '../../services/api';
import { fetchDirectorState, runDirectorStage } from '../../services/directorApi';
import type {
  DirectorAdjudication,
  DirectorContract,
  DirectorDossier,
  DirectorExecution,
  DirectorQualification,
  DirectorState,
  ProviderCatalogue,
} from '../../types/director';

type BusyStage = 'discover' | 'attack' | 'qualify' | 'compile' | 'execute' | null;

const emptyState: DirectorState = {
  dossiers: [],
  adjudications: [],
  qualifications: [],
  contracts: [],
  executions: [],
  exposure: { weekly_used: 0, weekly_ceiling: 0, allowed: true, total_records: 0 },
};

function objectValue(value: unknown, keys: string[]): string {
  if (!value || typeof value !== 'object') return '—';
  const record = value as Record<string, unknown>;
  for (const key of keys) {
    if (record[key] !== undefined && record[key] !== null) return String(record[key]);
  }
  return '—';
}

const StageBadge = ({ done, label }: { done: boolean; label: string }) => (
  <Badge color={done ? 'teal' : 'gray'} variant={done ? 'light' : 'outline'}>
    {done ? '✓ ' : ''}{label}
  </Badge>
);

export const ExploreConsole: React.FC = () => {
  const [state, setState] = useState<DirectorState>(emptyState);
  const [providers, setProviders] = useState<ProviderCatalogue | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [lens, setLens] = useState('market_structure');
  const [family, setFamily] = useState('discovery');
  const [hint, setHint] = useState('');
  const [provider, setProvider] = useState('claude');
  const [signalName, setSignalName] = useState('candidate_signal');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<BusyStage>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = async (preferredId?: string) => {
    const next = await fetchDirectorState();
    setState(next);
    setSelectedId((current) => {
      const wanted = preferredId || current;
      return next.dossiers.some((item) => item.dossier_id === wanted)
        ? wanted!
        : next.dossiers[0]?.dossier_id || null;
    });
  };

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([fetchDirectorState(controller.signal), fetchProviders(controller.signal)])
      .then(([director, catalogue]) => {
        setState(director);
        setProviders(catalogue);
        setSelectedId(director.dossiers[0]?.dossier_id || null);
        const preferred = catalogue.providers.find(
          (item) => item.id === catalogue.default_provider && item.available,
        ) || catalogue.providers.find((item) => item.available);
        if (preferred) setProvider(preferred.id);
      })
      .catch((reason: Error) => {
        if (reason.name !== 'AbortError') setError(reason.message);
      });
    return () => controller.abort();
  }, []);

  const dossier = state.dossiers.find((item) => item.dossier_id === selectedId) || null;
  const adjudication = useMemo<DirectorAdjudication | null>(
    () => state.adjudications.find((item) => item.dossier?.dossier_id === selectedId) || null,
    [selectedId, state.adjudications],
  );
  const qualification = useMemo<DirectorQualification | null>(
    () => state.qualifications.find((item) => item.dossier?.dossier_id === selectedId) || null,
    [selectedId, state.qualifications],
  );
  const contract = useMemo<DirectorContract | null>(
    () => state.contracts.find((item) => item.qualification_id === qualification?.qualification_id) || null,
    [qualification, state.contracts],
  );
  const execution = useMemo<DirectorExecution | null>(
    () => state.executions.find((item) => item.contract_id === contract?.contract_id) || null,
    [contract, state.executions],
  );

  const providerOptions = (providers?.providers || []).map((item) => ({
    value: item.id,
    label: `${item.label}${item.available ? '' : ' (unavailable)'}`,
    disabled: !item.available,
  }));
  const exposurePercent = state.exposure.weekly_ceiling
    ? Math.min(100, (state.exposure.weekly_used / state.exposure.weekly_ceiling) * 100)
    : 0;

  const run = async (stage: Exclude<BusyStage, null>, payload: Record<string, unknown>) => {
    setBusy(stage);
    setError(null);
    try {
      const response = await runDirectorStage<Record<string, any>>(stage, payload);
      const preferred = response.dossier?.dossier_id
        || response.adjudication?.dossier?.dossier_id
        || selectedId
        || undefined;
      await reload(preferred);
      if (stage === 'execute') setConfirmed(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      await reload().catch(() => undefined);
    } finally {
      setBusy(null);
    }
  };

  const discover = () => run('discover', { lens, family, hint, provider });
  const attack = (item: DirectorDossier) => run('attack', {
    dossier_id: item.dossier_id,
    provider: 'auto',
  });
  const qualify = (item: DirectorDossier) => run('qualify', {
    dossier_id: item.dossier_id,
    signal_name: signalName,
    provider,
    dataset_version: 'v1',
  });

  return (
    <Box p="xl" style={{ maxWidth: 1280, margin: '0 auto' }}>
      <Group justify="space-between" align="flex-start" mb="xl">
        <Box>
          <Group gap="sm">
            <ThemeIcon size="lg" radius="md" variant="gradient" gradient={{ from: 'violet', to: 'cyan' }}>
              <IconRobot size={19} />
            </ThemeIcon>
            <Text size="xl" fw={750} c="white">AI Research Director</Text>
          </Group>
          <Text size="sm" c="dimmed" mt="xs" maw={760}>
            Generate mechanisms without outcomes, attack them independently, check the signal's
            distribution, then freeze exactly one outcome-bearing experiment.
          </Text>
        </Box>
        <Button variant="subtle" leftSection={<IconRefresh size={16} />} onClick={() => reload()}>
          Refresh
        </Button>
      </Group>

      {error && (
        <Alert color="red" icon={<IconAlertTriangle size={17} />} title="Director stopped" mb="lg">
          {error}
        </Alert>
      )}

      <SimpleGrid cols={{ base: 1, lg: 3 }} spacing="lg" mb="lg">
        <Paper p="lg" radius="md" style={{ border: '1px solid var(--border)' }}>
          <Group justify="space-between" mb="sm">
            <Text fw={700}>Weekly sample budget</Text>
            <Badge color={state.exposure.allowed ? 'teal' : 'red'}>
              {state.exposure.weekly_used}/{state.exposure.weekly_ceiling} E1/E2
            </Badge>
          </Group>
          <Progress value={exposurePercent} color={exposurePercent >= 100 ? 'red' : 'blue'} mb="xs" />
          <Text size="xs" c="dimmed">
            Discovery, criticism and distribution checks are E0. Only Execute reveals outcomes.
          </Text>
        </Paper>
        <Paper p="lg" radius="md" style={{ border: '1px solid var(--border)' }}>
          <Text size="xs" c="dimmed" tt="uppercase" fw={700}>Current lane</Text>
          <Group gap="xs" mt="sm" wrap="wrap">
            <StageBadge done={!!dossier} label="Dossier" />
            <StageBadge done={!!adjudication} label="Attack" />
            <StageBadge done={!!qualification} label="E0 qualify" />
            <StageBadge done={!!contract} label="Frozen" />
            <StageBadge done={!!execution} label="Revealed" />
          </Group>
        </Paper>
        <Paper p="lg" radius="md" style={{ border: '1px solid var(--border)' }}>
          <Text size="xs" c="dimmed" tt="uppercase" fw={700}>Safety boundary</Text>
          <Group gap="sm" mt="sm" align="flex-start" wrap="nowrap">
            <IconShieldCheck size={22} color="var(--mantine-color-teal-5)" />
            <Text size="xs">
              The scout and signal author cannot read labels. The canonical harness—not the model—runs the frozen code.
            </Text>
          </Group>
        </Paper>
      </SimpleGrid>

      <Paper p="xl" radius="md" mb="lg" style={{ border: '1px solid var(--border)' }}>
        <Group justify="space-between" mb="md">
          <Box>
            <Text fw={700}>1. Generate a mechanism dossier</Text>
            <Text size="xs" c="dimmed">A high-level proposal grounded in available point-in-time features and the graveyard.</Text>
          </Box>
          <IconSparkles size={21} color="var(--mantine-color-violet-4)" />
        </Group>
        <SimpleGrid cols={{ base: 1, md: 3 }} spacing="md">
          <Select label="Scout lens" value={lens} onChange={(value) => setLens(value || 'market_structure')} data={[
            { value: 'market_structure', label: 'Market structure' },
            { value: 'behavioural', label: 'Behavioural' },
            { value: 'information_flow', label: 'Information flow' },
            { value: 'forced_flow', label: 'Forced / constrained flow' },
          ]} />
          <TextInput label="Family" value={family} onChange={(event) => setFamily(event.currentTarget.value)} />
          <Select label="Subscription lane" value={provider} data={providerOptions} onChange={(value) => setProvider(value || 'claude')} />
        </SimpleGrid>
        <Textarea
          label="Optional direction"
          placeholder="A market behaviour or data source worth exploring—leave blank for a wider search."
          value={hint}
          onChange={(event) => setHint(event.currentTarget.value)}
          minRows={2}
          mt="md"
        />
        <Button mt="md" leftSection={<IconSparkles size={16} />} loading={busy === 'discover'} onClick={discover} disabled={!providers}>
          Generate outcome-blind dossier
        </Button>
      </Paper>

      <Grid gap="lg">
        <Grid.Col span={{ base: 12, lg: 3 }}>
        <Paper p="md" radius="md" style={{ border: '1px solid var(--border)', height: '100%' }}>
          <Text fw={700} mb="sm">Dossiers</Text>
          <Stack gap="xs">
            {state.dossiers.length === 0 && <Text size="sm" c="dimmed">No dossiers yet.</Text>}
            {state.dossiers.map((item) => (
              <Button
                key={item.dossier_id}
                variant={item.dossier_id === selectedId ? 'light' : 'subtle'}
                color={item.has_data_gap ? 'yellow' : 'blue'}
                justify="flex-start"
                h="auto"
                py="sm"
                onClick={() => { setSelectedId(item.dossier_id); setConfirmed(false); }}
              >
                <Box style={{ textAlign: 'left', whiteSpace: 'normal' }}>
                  <Text size="xs" fw={700}>{item.dossier_id}</Text>
                  <Text size="xs" lineClamp={2}>{item.claim}</Text>
                </Box>
              </Button>
            ))}
          </Stack>
        </Paper>
        </Grid.Col>

        <Grid.Col span={{ base: 12, lg: 9 }}>
        <Paper p="xl" radius="md" style={{ border: '1px solid var(--border)', height: '100%' }}>
          {!dossier ? (
            <Stack align="center" py={60}>
              <IconFlask size={34} color="var(--mantine-color-dimmed)" />
              <Text c="dimmed">Generate a dossier to begin.</Text>
            </Stack>
          ) : (
            <Stack gap="lg">
              <Box>
                <Group justify="space-between" align="flex-start">
                  <Box maw={780}>
                    <Text size="xs" c="dimmed">{dossier.dossier_id} · {dossier.family} · {dossier.expected_horizon_days} sessions</Text>
                    <Text size="lg" fw={700} mt={4}>{dossier.claim}</Text>
                    <Text size="sm" c="dimmed" mt="xs">Population: {dossier.population}</Text>
                  </Box>
                  <Badge color={dossier.has_data_gap ? 'yellow' : 'teal'}>
                    {dossier.has_data_gap ? 'data gap' : 'data available'}
                  </Badge>
                </Group>
              </Box>

              <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
                <Box>
                  <Text size="xs" tt="uppercase" c="dimmed" fw={700}>Mechanism</Text>
                  <Text size="sm" mt={5}>{dossier.causal_chain}</Text>
                </Box>
                <Box>
                  <Text size="xs" tt="uppercase" c="dimmed" fw={700}>Persistent counterparty</Text>
                  <Text size="sm" mt={5}>{dossier.counterparty}: {dossier.counterparty_persistence_rationale}</Text>
                </Box>
              </SimpleGrid>

              <SimpleGrid cols={{ base: 1, md: 3 }} spacing="md">
                <Box>
                  <Text size="xs" tt="uppercase" c="dimmed" fw={700}>Unique predictions</Text>
                  <List size="xs" mt="xs">{dossier.unique_predictions.map((item) => <List.Item key={item}>{item}</List.Item>)}</List>
                </Box>
                <Box>
                  <Text size="xs" tt="uppercase" c="dimmed" fw={700}>Alternatives</Text>
                  <List size="xs" mt="xs">{dossier.competing_explanations.map((item) => <List.Item key={item}>{item}</List.Item>)}</List>
                </Box>
                <Box>
                  <Text size="xs" tt="uppercase" c="dimmed" fw={700}>Falsifiers</Text>
                  <List size="xs" mt="xs">{dossier.natural_falsifiers.map((item) => <List.Item key={item}>{item}</List.Item>)}</List>
                </Box>
              </SimpleGrid>

              {dossier.has_data_gap && (
                <Alert color="yellow" icon={<IconAlertTriangle size={17} />} title="Collect data before qualification">
                  {dossier.required_observations_absent.join('; ')}
                </Alert>
              )}

              <Divider />
              <Box>
                <Group justify="space-between" mb="sm">
                  <Box>
                    <Text fw={700}>2. Independent hostile review</Text>
                    <Text size="xs" c="dimmed">Automatically routes away from the proposing provider when possible.</Text>
                  </Box>
                  {!adjudication && (
                    <Button variant="light" loading={busy === 'attack'} onClick={() => attack(dossier)}>
                      Attack dossier
                    </Button>
                  )}
                </Group>
                {adjudication && (
                  <Alert color={adjudication.approved ? 'teal' : 'red'} icon={adjudication.approved ? <IconCheck size={17} /> : <IconAlertTriangle size={17} />}>
                    <Text fw={650}>{adjudication.approved ? 'Approved for E0 qualification' : 'Rejected before sample spend'}</Text>
                    <Text size="xs" mt={4}>{adjudication.verdict}</Text>
                    {adjudication.all_dissents.length > 0 && (
                      <List size="xs" mt="xs">
                        {adjudication.all_dissents.map((item, index) => (
                          <List.Item key={`${item.reviewer_role}-${index}`}>{item.severity}: {item.objection}</List.Item>
                        ))}
                      </List>
                    )}
                  </Alert>
                )}
              </Box>

              {adjudication?.approved && !dossier.has_data_gap && (
                <>
                  <Divider />
                  <Box>
                    <Group justify="space-between" align="flex-end" gap="md">
                      <Box style={{ flex: 1 }}>
                        <Text fw={700}>3. Author and qualify the signal (E0)</Text>
                        <Text size="xs" c="dimmed" mb="sm">Runs determinism, coverage, concentration, breadth and independent-block checks without constructing returns.</Text>
                        <TextInput label="Signal name" value={signalName} onChange={(event) => setSignalName(event.currentTarget.value)} disabled={!!qualification} />
                      </Box>
                      {!qualification && (
                        <Button loading={busy === 'qualify'} onClick={() => qualify(dossier)} disabled={!signalName.trim()}>
                          Run E0 qualification
                        </Button>
                      )}
                    </Group>
                    {qualification && (
                      <Alert mt="md" color={qualification.approved ? 'teal' : 'red'}>
                        <Group justify="space-between"><Text fw={650}>{qualification.approved ? 'E0 gates passed' : 'E0 gates failed'}</Text><Code>{qualification.signal_source_hash}</Code></Group>
                        <SimpleGrid cols={{ base: 1, sm: 3 }} mt="sm">
                          <Text size="xs">Coverage: {objectValue(qualification.preflight, ['coverage', 'coverage_fraction'])}</Text>
                          <Text size="xs">Independent blocks: {objectValue(qualification.structural_gate, ['estimated_independent_blocks', 'independent_blocks'])}</Text>
                          <Text size="xs">Dominant date: {objectValue(qualification.preflight, ['max_date_share', 'dominant_date_share'])}</Text>
                        </SimpleGrid>
                        {!qualification.approved && <Text size="xs" mt="xs">{qualification.rejection_reasons.join('; ')}</Text>}
                      </Alert>
                    )}
                  </Box>
                </>
              )}

              {qualification?.approved && (
                <>
                  <Divider />
                  <Box>
                    <Group justify="space-between">
                      <Box>
                        <Text fw={700}>4. Freeze the experiment contract</Text>
                        <Text size="xs" c="dimmed">Locks the population, signal hash, horizon, baselines, costs and pass bar.</Text>
                      </Box>
                      {!contract && (
                        <Button variant="light" leftSection={<IconLock size={16} />} loading={busy === 'compile'} onClick={() => run('compile', { qualification_id: qualification.qualification_id })}>
                          Freeze contract
                        </Button>
                      )}
                    </Group>
                    {contract && (
                      <Paper p="md" mt="sm" bg="#0d1117">
                        <Group justify="space-between"><Code>{contract.contract_id}</Code><Badge>{contract.exposure_level_incurred}</Badge></Group>
                        <Text size="xs" mt="xs">Bar: {contract.min_magnitude_bps} bps and t ≥ {contract.min_significance_t}; horizon {contract.horizons.join(', ')} sessions.</Text>
                      </Paper>
                    )}
                  </Box>
                </>
              )}

              {contract && !execution && (
                <>
                  <Divider />
                  <Alert color="orange" icon={<IconLock size={17} />} title="5. One-shot outcome reveal">
                    <Text size="xs" mb="sm">This spends the finite historical sample. The full registered report is persisted even if the signal fails.</Text>
                    <Checkbox
                      checked={confirmed}
                      onChange={(event) => setConfirmed(event.currentTarget.checked)}
                      label={`I intend to spend one ${contract.exposure_level_incurred} attempt on ${contract.contract_id}`}
                    />
                    <Button color="orange" mt="md" loading={busy === 'execute'} disabled={!confirmed || !state.exposure.allowed} onClick={() => run('execute', { contract_id: contract.contract_id, confirm_outcome_access: true })}>
                      Execute frozen experiment
                    </Button>
                  </Alert>
                </>
              )}

              {execution && (
                <>
                  <Divider />
                  <Alert color={(execution as any).status === 'succeeded' ? 'teal' : 'red'} title="Outcome-bearing execution recorded">
                    <Text size="sm">Status: {String((execution as any).status || 'unknown')}</Text>
                    <Code block mt="sm" style={{ maxHeight: 360, overflow: 'auto', fontSize: 11 }}>
                      {JSON.stringify((execution as any).result || execution, null, 2)}
                    </Code>
                  </Alert>
                </>
              )}
            </Stack>
          )}
        </Paper>
        </Grid.Col>
      </Grid>
    </Box>
  );
};
