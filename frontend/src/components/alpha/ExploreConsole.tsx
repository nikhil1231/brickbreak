import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert, Badge, Box, Button, Checkbox, Code, Collapse, Group, Paper,
  Loader, Progress, ScrollArea, Select, SimpleGrid, Stack, Switch, Text,
  TextInput, Textarea, ThemeIcon, UnstyledButton,
} from '@mantine/core';
import {
  IconAlertTriangle, IconArrowDown, IconCheck, IconChevronDown,
  IconChevronRight, IconDatabase, IconFileCheck, IconFlask, IconGitBranch,
  IconLock, IconPlayerPlay, IconPlus, IconRefresh, IconRobot, IconSearch,
  IconShieldCheck, IconSparkles,
} from '@tabler/icons-react';
import { useLocalStorage } from '@mantine/hooks';

import { fetchProviders } from '../../services/api';
import { fetchDirectorState, runDirectorStage } from '../../services/directorApi';
import type {
  DirectorAdjudication, DirectorContract, DirectorDossier, DirectorExecution,
  DirectorQualification, DirectorRun, DirectorState, ProviderCatalogue,
} from '../../types/director';

type StageKey = 'discover' | 'attack' | 'qualify' | 'compile' | 'execute';
type StageStatus = 'locked' | 'ready' | 'running' | 'complete' | 'failed' | 'blocked';
type AttackAction = 'review' | 'skip' | 'waive';
interface StageActivity {
  stage: StageKey;
  title: string;
  detail: string;
}
interface ActiveOperation extends StageActivity {
  runId: string | null;
}
interface SequenceSettings {
  autoAdvance: boolean;
  skipIndependentAttack: boolean;
  criticProvider: string;
  criticModel: string;
  authorProvider: string;
  authorModel: string;
  signalName: string;
  costBps: string;
  capacityInr: string;
  minT: string;
}
interface PipelineListItem {
  key: string;
  run: DirectorRun | null;
  dossier: DirectorDossier | null;
}
const DEFAULT_MODEL = '__cli_default__';
const NEW_RUN_KEY = '__new_pipeline__';
const SCOUT_LENSES = [
  { value: 'market_structure', label: 'Market structure' },
  { value: 'participant_constraints', label: 'Participant constraints' },
  { value: 'external_research', label: 'External research' },
  { value: 'data_catalogue', label: 'Existing data catalogue' },
  { value: 'graveyard_branch', label: 'Branch from a prior failure' },
] as const;

function nextScoutLens(state: DirectorState): string {
  const known = new Set<string>(SCOUT_LENSES.map((item) => item.value));
  const attempts: Array<{ createdAt: string; lens: string }> = [];
  for (const run of state.runs || []) {
    const candidate = String(run.config?.lens || '');
    if (known.has(candidate)) attempts.push({ createdAt: run.created_at, lens: candidate });
  }
  for (const dossier of state.dossiers || []) {
    const match = dossier.proposer?.match(/scout_([a-z_]+)/);
    const candidate = match?.[1] || '';
    if (known.has(candidate)) attempts.push({ createdAt: dossier.created_at, lens: candidate });
  }
  attempts.sort((left, right) => left.createdAt.localeCompare(right.createdAt));
  const last = attempts.at(-1)?.lens;
  if (!last) return SCOUT_LENSES[0].value;
  const index = SCOUT_LENSES.findIndex((item) => item.value === last);
  return SCOUT_LENSES[(index + 1) % SCOUT_LENSES.length].value;
}

const emptyState: DirectorState = {
  runs: [], dossiers: [], adjudications: [], qualifications: [], contracts: [], executions: [], withdrawals: [],
  exposure: { weekly_used: 0, weekly_ceiling: 0, allowed: true, total_records: 0 },
};

const statusStyle: Record<StageStatus, { color: string; label: string }> = {
  locked: { color: 'gray', label: 'Waiting' },
  ready: { color: 'blue', label: 'Ready' },
  running: { color: 'violet', label: 'Running' },
  complete: { color: 'teal', label: 'Complete' },
  failed: { color: 'red', label: 'Stopped' },
  blocked: { color: 'yellow', label: 'Blocked' },
};

function toText(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (typeof value === 'object') {
    const record = value as Record<string, unknown>;
    if (record.name) return String(record.name);
    if (record.objection) return String(record.objection);
    if (record.title) return String(record.title);
    return JSON.stringify(value);
  }
  return String(value);
}

function listText(value: unknown): string[] {
  if (!value) return [];
  if (Array.isArray(value)) return value.map(toText);
  if (typeof value !== 'string') return [toText(value)];
  const trimmed = value.trim();
  if (!trimmed.startsWith('[')) return [trimmed];
  try {
    const parsed = JSON.parse(trimmed.replace(/'/g, '"'));
    return Array.isArray(parsed) ? parsed.map(toText) : [trimmed];
  } catch {
    const matches = [...trimmed.matchAll(/'([^']+)'/g)].map((match) => match[1]);
    return matches.length ? matches : [trimmed];
  }
}

function objectValue(value: unknown, keys: string[]): string {
  if (!value || typeof value !== 'object') return '—';
  const record = value as Record<string, unknown>;
  for (const key of keys) {
    if (record[key] !== undefined && record[key] !== null) return String(record[key]);
  }
  return '—';
}

function stageScroll(stage: StageKey) {
  window.setTimeout(() => document.getElementById(`director-stage-${stage}`)?.scrollIntoView({
    behavior: 'smooth', block: 'center',
  }), 120);
}

function proposerIdentity(dossier: DirectorDossier | null) {
  if (!dossier) return { provider: '', model: '' };
  const provider = dossier.proposer?.split(':', 1)[0] || '';
  const match = dossier.proposer?.match(/;model=([^;]+)/);
  return { provider, model: match?.[1] || 'cli-default' };
}

function modelPayload(model: string) {
  return model === DEFAULT_MODEL ? '' : model;
}

function defaultModel(catalogue: ProviderCatalogue | null, provider: string) {
  const selected = catalogue?.providers.find((item) => item.id === provider);
  return selected?.default_model || DEFAULT_MODEL;
}

function validRememberedModel(catalogue: ProviderCatalogue, provider: string, model: string) {
  const selected = catalogue.providers.find((item) => item.id === provider);
  if (!selected) return defaultModel(catalogue, provider);
  const availableModels = selected.models.map((item) => item.id || DEFAULT_MODEL);
  return model && availableModels.includes(model) ? model : (selected.default_model || DEFAULT_MODEL);
}

function runKey(runId: string | null) {
  return runId || NEW_RUN_KEY;
}

function responseRunId(response: Record<string, any>, fallback: string | null) {
  return response.run?.run_id
    || fallback
    || response.dossier?.dossier_id
    || response.adjudication?.dossier?.dossier_id
    || response.qualification?.dossier?.dossier_id;
}

function newRunId() {
  return `RUN_${new Date().toISOString().replace(/\D/g, '').slice(0, 14)}_${crypto.randomUUID().replace(/-/g, '').slice(0, 8).toUpperCase()}`;
}

function hasPipeline(state: DirectorState, id: string) {
  return (state.runs || []).some((run) => run.run_id === id)
    || state.dossiers?.some((dossier) => dossier.dossier_id === id);
}

function condensedPipelineTitle(item: PipelineListItem): string {
  const claim = item.dossier?.claim || item.run?.claim || '';
  const text = claim.toLowerCase();
  if (!claim) {
    const lens = String(item.run?.config?.lens || '').replace(/_/g, ' ');
    return lens ? `${lens.replace(/\b\w/g, (letter) => letter.toUpperCase())} scout` : 'New mechanism';
  }
  if ((text.includes('15:00-to-close') || text.includes('late sell-down')
      || text.includes('closing-price pressure')) && text.includes('revers')) {
    return 'Late-session pressure reversal';
  }
  if ((text.includes('progressively diminishes') || text.includes('diminishing price impact'))
      && text.includes('deliver')) return 'Delivery exhaustion reversal';
  if ((text.includes('financial year') || text.includes('first trading day of april'))
      && text.includes('revers')) return 'Fiscal-year loser reversal';
  if (text.includes('gap-down') && (text.includes('fails to extend')
      || text.includes('not confirmed'))) return 'Failed gap-down reversal';
  if (text.includes('deliver') && text.includes('selloff') && text.includes('revers')) {
    return 'Delivery selloff reversal';
  }
  if (text.includes('idiosyncratic one-day price decline') && text.includes('deliver')) {
    return 'Delivery shock reversal';
  }
  if (text.includes('gap-down') && (text.includes('rebound') || text.includes('revers'))) {
    return 'Gap-down rebound';
  }
  if (text.includes('opening') && text.includes('activity')) return 'Opening activity persistence';

  const mechanism = claim.replace(/^(?:among|for)\b.{0,240}?,\s*/i, '');
  const terms = [
    'idiosyncratic', 'gap-down', 'gap-up', 'delivery', 'selloff', 'opening',
    'closing', 'pressure', 'exhaustion', 'reversal', 'rebound', 'continuation',
    'breakout', 'resilience', 'liquidity', 'turnover', 'volatility', 'momentum',
  ];
  const found = terms
    .map((term) => ({ term, index: mechanism.toLowerCase().indexOf(term) }))
    .filter((item) => item.index >= 0)
    .sort((left, right) => left.index - right.index)
    .slice(0, 4)
    .map((item) => item.term);
  if (found.length) {
    const title = found.join(' ');
    return title.charAt(0).toUpperCase() + title.slice(1);
  }
  const words = mechanism.replace(/[^a-zA-Z0-9-]+/g, ' ').trim().split(/\s+/).slice(0, 5);
  return words.join(' ') || 'Untitled pipeline';
}

function activityFor(stage: StageKey, payload: Record<string, unknown>): StageActivity {
  const provider = String(payload.provider || '').trim();
  const model = String(payload.model || '').trim() || 'CLI default';
  if (stage === 'discover') return {
    stage,
    title: 'Discovering a mechanism…',
    detail: `${provider || 'Selected scout'} · ${model} · ${String(payload.lens || 'market structure')}`,
  };
  if (stage === 'attack' && payload.waive_failed_independent_attack) return {
    stage,
    title: 'Applying the owner waiver…',
    detail: 'Preserving the failed critique and re-running every deterministic gate.',
  };
  if (stage === 'attack' && payload.deterministic_only) return {
    stage,
    title: 'Running deterministic gates…',
    detail: 'Independent model attack skipped; leakage, novelty, economics and power still run.',
  };
  if (stage === 'attack') return {
    stage,
    title: 'Running the independent attack…',
    detail: `${provider || 'Selected reviewer'} · ${model}`,
  };
  if (stage === 'qualify') return {
    stage,
    title: 'Authoring the signal and running E0…',
    detail: `${provider || 'Selected author'} · ${model} · ${String(payload.signal_name || 'candidate signal')}`,
  };
  if (stage === 'compile') return {
    stage,
    title: 'Freezing the experiment contract…',
    detail: `${String(payload.cost_bps || 0)} bps cost · ₹${Number(payload.capacity_inr || 0).toLocaleString()} capacity · t ≥ ${String(payload.min_t || 0)}`,
  };
  return {
    stage,
    title: 'Executing the one-shot test…',
    detail: `${String(payload.contract_id || 'Registered contract')} · outcome access in progress`,
  };
}

function pipelineIndicator(
  runId: string,
  dossier: DirectorDossier | null,
  persistedRun: DirectorRun | null,
  state: DirectorState,
  operation: ActiveOperation | null,
  errors: Partial<Record<StageKey, string>> = {},
) {
  if (operation?.runId === runId) {
    const labels: Record<StageKey, string> = {
      discover: 'Discovering', attack: 'Reviewing', qualify: 'Running E0',
      compile: 'Freezing', execute: 'Executing',
    };
    return { color: 'violet', label: labels[operation.stage], running: true };
  }
  const failedStage = (['execute', 'compile', 'qualify', 'attack', 'discover'] as StageKey[])
    .find((stage) => Boolean(errors[stage]));
  if (failedStage) {
    const labels: Record<StageKey, string> = {
      discover: 'Discovery stopped', attack: 'Review stopped', qualify: 'E0 stopped',
      compile: 'Freeze stopped', execute: 'Execution stopped',
    };
    return { color: 'red', label: labels[failedStage], running: false };
  }
  if (persistedRun?.status === 'running') {
    const labels: Record<string, string> = {
      discover: 'Discovering', attack: 'Reviewing', qualify: 'Running E0',
      compile: 'Freezing', execute: 'Executing',
    };
    return { color: 'violet', label: labels[persistedRun.stage] || 'Running', running: true };
  }
  if (persistedRun?.status === 'failed') {
    return { color: 'red', label: `${persistedRun.stage === 'qualify' ? 'E0' : persistedRun.stage} stopped`, running: false };
  }
  if (!dossier) {
    return { color: persistedRun?.status === 'stopped' ? 'red' : 'yellow', label: 'Pending dossier', running: false };
  }
  const adjudication = state.adjudications?.find((item) => item.dossier?.dossier_id === dossier.dossier_id);
  const qualification = state.qualifications?.find((item) => item.dossier?.dossier_id === dossier.dossier_id);
  const contract = state.contracts?.find((item) => item.qualification_id === qualification?.qualification_id);
  const execution = state.executions?.find((item) => item.contract_id === contract?.contract_id);
  if (execution) {
    return (execution as any).status === 'succeeded'
      ? { color: 'teal', label: 'Complete', running: false }
      : { color: 'red', label: 'Execution stopped', running: false };
  }
  if (contract && state.withdrawals?.some(
      (item) => item.contract_id === contract.contract_id)) {
    return { color: 'yellow', label: 'Withdrawn unopened', running: false };
  }
  if (contract) return { color: 'orange', label: 'Awaiting reveal', running: false };
  if (qualification) return qualification.approved
    ? { color: 'blue', label: 'Ready to freeze', running: false }
    : { color: 'red', label: 'E0 stopped', running: false };
  if (adjudication) {
    if (!adjudication.approved) return { color: 'red', label: 'Review stopped', running: false };
    return dossier.has_data_gap
      ? { color: 'yellow', label: 'Data blocked', running: false }
      : { color: 'blue', label: 'Ready for E0', running: false };
  }
  if (dossier.has_data_gap) return { color: 'yellow', label: 'Data gap', running: false };
  return { color: 'blue', label: 'Ready for review', running: false };
}

interface ProviderPickerProps {
  title: string;
  provider: string;
  model: string;
  catalogue: ProviderCatalogue | null;
  onProvider: (value: string) => void;
  onModel: (value: string) => void;
  excludeProvider?: string;
  disabled?: boolean;
  note?: string;
}

const ProviderPicker: React.FC<ProviderPickerProps> = ({
  title, provider, model, catalogue, onProvider, onModel,
  excludeProvider = '', disabled = false, note,
}) => {
  const providerOptions = (catalogue?.providers || []).map((item) => {
    const excluded = item.id === excludeProvider;
    return {
      value: item.id,
      label: `${item.label}${excluded ? ' · used by scout' : !item.available ? ' · unavailable' : ''}`,
      disabled: disabled || excluded || !item.available,
    };
  });
  const selected = catalogue?.providers.find((item) => item.id === provider);
  const modelOptions = (selected?.models || []).map((item) => ({
    value: item.id || DEFAULT_MODEL, label: item.label,
  }));

  return (
    <Box>
      <Text size="xs" fw={700} mb={5}>{title}</Text>
      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
        <Select
          aria-label={`${title} provider`} value={provider} data={providerOptions}
          disabled={disabled || !catalogue} placeholder="Provider"
          onChange={(value) => {
            const next = value || '';
            onProvider(next);
            onModel(defaultModel(catalogue, next));
          }}
        />
        <Select
          aria-label={`${title} model`} value={model} data={modelOptions}
          disabled={disabled || !selected?.available} placeholder="Model"
          onChange={(value) => onModel(value || DEFAULT_MODEL)}
        />
      </SimpleGrid>
      {note && <Text size="xs" c="dimmed" mt={5}>{note}</Text>}
      {selected && !selected.available && <Text size="xs" c="yellow.4" mt={5}>{selected.install_hint}</Text>}
    </Box>
  );
};

interface StageCardProps {
  stage: StageKey;
  number: number;
  title: string;
  subtitle: string;
  summary?: string;
  status: StageStatus;
  icon: React.ReactNode;
  error?: string;
  activity?: StageActivity | null;
  children: React.ReactNode;
  last?: boolean;
}

const StageCard: React.FC<StageCardProps> = ({
  stage, number, title, subtitle, summary, status, icon, error, activity, children, last,
}) => {
  const visual = statusStyle[status];
  const [expanded, setExpanded] = useState<boolean>(
    status === 'ready' || status === 'running' || status === 'failed');

  useEffect(() => {
    setExpanded(status === 'ready' || status === 'running' || status === 'failed');
  }, [status]);

  return (
    <Box id={`director-stage-${stage}`} style={{ position: 'relative' }}>
      <Paper p={{ base: 'md', sm: 'lg' }} radius="lg" style={{
        borderColor: status === 'ready' || status === 'running'
          ? `var(--mantine-color-${visual.color}-7)` : 'var(--border)',
        boxShadow: status === 'ready'
          ? '0 0 0 1px rgba(88,166,255,.12), 0 12px 32px rgba(0,0,0,.18)' : undefined,
        opacity: status === 'locked' ? 0.68 : 1,
      }}>
        <Group justify="space-between" align="flex-start" wrap="nowrap"
               style={{ cursor: 'pointer' }}
               onClick={() => setExpanded(e => !e)}>
          <Group align="flex-start" wrap="nowrap" style={{ minWidth: 0 }}>
            <ThemeIcon size={38} radius="xl" color={visual.color}
              variant={status === 'ready' || status === 'running' ? 'filled' : 'light'}>
              {status === 'complete' ? <IconCheck size={18} /> : icon}
            </ThemeIcon>
            <Box style={{ minWidth: 0 }}>
              <Text size="xs" c="dimmed" tt="uppercase" fw={700}>Step {number}</Text>
              <Text fw={750} size="md">{title}</Text>
              <Text size={expanded ? 'xs' : 'sm'} c={expanded ? 'dimmed' : undefined}
                fw={expanded ? 400 : 600} mt={2} lineClamp={expanded ? 2 : 1}>
                {expanded ? subtitle : summary || subtitle}
              </Text>
            </Box>
          </Group>
          <Group gap="xs" wrap="nowrap">
            <Badge color={visual.color} variant="light" style={{ flexShrink: 0 }}>{visual.label}</Badge>
            {expanded ? <IconChevronDown size={18} color="var(--text-muted)" /> : <IconChevronRight size={18} color="var(--text-muted)" />}
          </Group>
        </Group>
        <Collapse expanded={expanded}>
          {error && <Alert color="red" icon={<IconAlertTriangle size={16} />} title="This step stopped" mt="md">
            <Text size="sm" style={{ overflowWrap: 'anywhere' }}>{error}</Text>
          </Alert>}
          {status === 'running' && activity && <Paper p="sm" mt="md" radius="md" bg="rgba(121, 80, 242, .10)" style={{ borderColor: 'rgba(151, 117, 250, .35)' }}>
            <Group gap="sm" wrap="nowrap" align="flex-start">
              <Loader size="sm" color="violet" mt={2} />
              <Box style={{ minWidth: 0 }}>
                <Text size="sm" fw={700}>{activity.title}</Text>
                <Text size="xs" c="dimmed" mt={2}>{activity.detail}</Text>
              </Box>
            </Group>
          </Paper>}
          <Box mt="lg">{children}</Box>
        </Collapse>
      </Paper>
      {!last && <Stack align="center" gap={0} h={48} justify="center">
        <Box w={1} h={20} bg="var(--border-light)" />
        <IconArrowDown size={17} color="var(--text-muted)" />
      </Stack>}
    </Box>
  );
};

const LockedMessage = ({ children }: { children: React.ReactNode }) => (
  <Group gap="xs" c="dimmed"><IconLock size={15} /><Text size="sm">{children}</Text></Group>
);

export const ExploreConsole: React.FC = () => {
  const [state, setState] = useState<DirectorState>(emptyState);
  const [providers, setProviders] = useState<ProviderCatalogue | null>(null);
  const [selectedId, setSelectedId] = useLocalStorage<string | null>({ key: 'explore-selected-id', defaultValue: null, getInitialValueInEffect: false });
  const [operationsByRun, setOperationsByRun] = useState<Record<string, ActiveOperation>>({});
  const [attackActionsByRun, setAttackActionsByRun] = useState<Record<string, AttackAction>>({});
  const [stageErrorsByRun, setStageErrorsByRun] = useState<Record<string, Partial<Record<StageKey, string>>>>({});
  const [autoAdvance, setAutoAdvance] = useState(true);
  const [skipIndependentAttack, setSkipIndependentAttack] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const [pipelineBrowserOpen, setPipelineBrowserOpen] = useState(false);
  const [pipelineSearch, setPipelineSearch] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [lens, setLens] = useState('market_structure');
  const [family, setFamily] = useState('discovery');
  const [hint, setHint] = useState('');
  const [signalName, setSignalName] = useState('candidate_signal');
  const [costBps, setCostBps] = useState('40');
  const [capacityInr, setCapacityInr] = useState('1000000');
  const [minT, setMinT] = useState('2.5');
  const [scoutProvider, setScoutProvider] = useLocalStorage({ key: 'explore-scout-provider', defaultValue: '', getInitialValueInEffect: false });
  const [scoutModel, setScoutModel] = useLocalStorage({ key: 'explore-scout-model', defaultValue: '', getInitialValueInEffect: false });
  const [criticProvider, setCriticProvider] = useLocalStorage({ key: 'explore-critic-provider', defaultValue: '', getInitialValueInEffect: false });
  const [criticModel, setCriticModel] = useLocalStorage({ key: 'explore-critic-model', defaultValue: '', getInitialValueInEffect: false });
  const [authorProvider, setAuthorProvider] = useLocalStorage({ key: 'explore-author-provider', defaultValue: '', getInitialValueInEffect: false });
  const [authorModel, setAuthorModel] = useLocalStorage({ key: 'explore-author-model', defaultValue: '', getInitialValueInEffect: false });
  const selectedIdRef = useRef<string | null>(selectedId);
  const operationsRef = useRef<Record<string, ActiveOperation>>({});

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  const reload = useCallback(async (
    preferredId?: string,
    expectedSelection?: string | null,
  ) => {
    const next = await fetchDirectorState();
    setState(next);
    setSelectedId((current) => {
      let nextSelection: string | null;
      if (preferredId && (expectedSelection === undefined || current === expectedSelection)) {
        nextSelection = hasPipeline(next, preferredId)
          ? preferredId : next.runs?.[0]?.run_id || next.dossiers[0]?.dossier_id || null;
      } else if (current === null) {
        nextSelection = null;
      } else {
        nextSelection = hasPipeline(next, current) || current.startsWith('RUN_')
          ? current : next.runs?.[0]?.run_id || next.dossiers[0]?.dossier_id || null;
      }
      selectedIdRef.current = nextSelection;
      return nextSelection;
    });
    return next;
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([fetchDirectorState(controller.signal), fetchProviders(controller.signal)])
      .then(([director, catalogue]) => {
        setState(director);
        setProviders(catalogue);
        setSelectedId((current) => {
          const nextSelection = current && (hasPipeline(director, current) || current.startsWith('RUN_'))
            ? current : director.runs?.[0]?.run_id || director.dossiers[0]?.dossier_id || null;
          selectedIdRef.current = nextSelection;
          return nextSelection;
        });
        const available = catalogue.providers.filter((item) => item.available);
        const scout = available.find((item) => item.id === catalogue.default_provider) || available[0];
        const critic = available.find((item) => item.id !== scout?.id) || available[1];
        const nextScoutProvider = available.some((item) => item.id === scoutProvider)
          ? scoutProvider : (scout?.id || '');
        const nextCriticProvider = available.some((item) => item.id === criticProvider)
          ? criticProvider : (critic?.id || '');
        const nextAuthorProvider = available.some((item) => item.id === authorProvider)
          ? authorProvider : (scout?.id || '');
        setScoutProvider(nextScoutProvider);
        setScoutModel(validRememberedModel(catalogue, nextScoutProvider, scoutModel));
        setCriticProvider(nextCriticProvider);
        setCriticModel(validRememberedModel(catalogue, nextCriticProvider, criticModel));
        setAuthorProvider(nextAuthorProvider);
        setAuthorModel(validRememberedModel(catalogue, nextAuthorProvider, authorModel));
      })
      .catch((reason: Error) => {
        if (reason.name !== 'AbortError') {
          setStageErrorsByRun((current) => ({
            ...current,
            [NEW_RUN_KEY]: { ...current[NEW_RUN_KEY], discover: reason.message },
          }));
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => { reload().catch(() => undefined); }, 2000);
    return () => window.clearInterval(timer);
  }, [reload]);

  const pipelineRuns = useMemo(() => {
    const persisted: PipelineListItem[] = (state.runs || []).map((run) => ({
      key: run.run_id,
      run,
      dossier: state.dossiers?.find((item) => item.dossier_id === run.dossier_id) || null,
    }));
    const linkedDossiers = new Set((state.runs || []).map((run) => run.dossier_id).filter(Boolean));
    const legacy: PipelineListItem[] = (state.dossiers || [])
      .filter((item) => !linkedDossiers.has(item.dossier_id))
      .map((item) => ({ key: item.dossier_id, run: null, dossier: item }));
    for (const operation of Object.values(operationsByRun)) {
      if (operation.runId && !persisted.some((item) => item.key === operation.runId)
          && !legacy.some((item) => item.key === operation.runId)) {
        persisted.unshift({ key: operation.runId, run: null, dossier: null });
      }
    }
    if (selectedId?.startsWith('RUN_')
        && !persisted.some((item) => item.key === selectedId)
        && !legacy.some((item) => item.key === selectedId)) {
      persisted.unshift({ key: selectedId, run: null, dossier: null });
    }
    return [...persisted, ...legacy];
  }, [operationsByRun, selectedId, state.dossiers, state.runs]);
  const selectedRun = (state.runs || []).find((item) => item.run_id === selectedId) || null;
  const selectedDossierId = selectedRun?.dossier_id
    || (state.dossiers?.some((item) => item.dossier_id === selectedId) ? selectedId : null);
  const dossier = state.dossiers?.find((item) => item.dossier_id === selectedDossierId) || null;
  const adjudication = useMemo<DirectorAdjudication | null>(
    () => state.adjudications?.find((item) => item.dossier?.dossier_id === selectedDossierId) || null,
    [selectedDossierId, state.adjudications]);
  const qualification = useMemo<DirectorQualification | null>(
    () => state.qualifications?.find((item) => item.dossier?.dossier_id === selectedDossierId) || null,
    [selectedDossierId, state.qualifications]);
  const contract = useMemo<DirectorContract | null>(
    () => state.contracts?.find((item) => item.qualification_id === qualification?.qualification_id) || null,
    [qualification, state.contracts]);
  const execution = useMemo<DirectorExecution | null>(
    () => state.executions?.find((item) => item.contract_id === contract?.contract_id) || null,
    [contract, state.executions]);
  const withdrawal = useMemo(
    () => state.withdrawals?.find((item) => item.contract_id === contract?.contract_id) || null,
    [contract, state.withdrawals]);

  const proposer = proposerIdentity(dossier);
  const reviewerExclusion = proposer.provider || scoutProvider;

  useEffect(() => {
    if (!providers || criticProvider !== reviewerExclusion) return;
    const alternate = providers.providers.find((item) => item.available && item.id !== reviewerExclusion);
    if (alternate) {
      setCriticProvider(alternate.id);
      setCriticModel(alternate.default_model || DEFAULT_MODEL);
    }
  }, [criticProvider, providers, reviewerExclusion]);

  const perform = useCallback(async (
    stage: StageKey,
    payload: Record<string, unknown>,
    targetRunId: string | null,
  ) => {
    let operationKey = runKey(targetRunId);
    if (operationsRef.current[operationKey]) return null;
    const startedWithSelection = selectedIdRef.current;
    const stageActivity = activityFor(stage, payload);
    const initialOperation = { ...stageActivity, runId: targetRunId };
    operationsRef.current = {
      ...operationsRef.current,
      [operationKey]: initialOperation,
    };
    setOperationsByRun(operationsRef.current);
    setStageErrorsByRun((current) => ({
      ...current,
      [runKey(targetRunId)]: { ...current[runKey(targetRunId)], [stage]: undefined },
    }));
    try {
      const response = await runDirectorStage<Record<string, any>>(stage, payload);
      const resolvedRunId = responseRunId(response, targetRunId);
      const resolvedKey = runKey(resolvedRunId);
      if (resolvedKey !== operationKey) {
        const nextOperations = { ...operationsRef.current };
        delete nextOperations[operationKey];
        nextOperations[resolvedKey] = { ...stageActivity, runId: resolvedRunId };
        operationKey = resolvedKey;
        operationsRef.current = nextOperations;
        setOperationsByRun(nextOperations);
      }
      await reload(resolvedRunId || undefined, startedWithSelection);
      return response;
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setStageErrorsByRun((current) => ({
        ...current,
        [runKey(targetRunId)]: { ...current[runKey(targetRunId)], [stage]: message },
      }));
      await reload().catch(() => undefined);
      if (selectedIdRef.current === targetRunId) stageScroll(stage);
      return null;
    } finally {
      const nextOperations = { ...operationsRef.current };
      delete nextOperations[operationKey];
      operationsRef.current = nextOperations;
      setOperationsByRun(nextOperations);
    }
  }, [reload]);

  const sequenceSettings = (): SequenceSettings => ({
    autoAdvance, skipIndependentAttack, criticProvider, criticModel,
    authorProvider, authorModel, signalName, costBps, capacityInr, minT,
  });
  const attackPayload = (dossierId: string, settings: SequenceSettings, deterministicOnly = false) => ({
    dossier_id: dossierId, provider: settings.criticProvider, model: modelPayload(settings.criticModel),
    deterministic_only: deterministicOnly,
  });
  const qualifyPayload = (dossierId: string, settings: SequenceSettings) => ({
    dossier_id: dossierId, signal_name: settings.signalName.trim(), provider: settings.authorProvider,
    model: modelPayload(settings.authorModel), dataset_version: 'v1',
  });
  const compilePayload = (qualificationId: string, settings: SequenceSettings) => ({
    qualification_id: qualificationId, reviewer: 'human_owner', cost_bps: Number(settings.costBps),
    capacity_inr: Number(settings.capacityInr), min_t: Number(settings.minT),
  });

  const runSafeSequence = async (
    start: Exclude<StageKey, 'execute'>,
    initialPayload: Record<string, unknown>,
    settings: SequenceSettings,
    initialRunId: string | null,
  ) => {
    let stage: Exclude<StageKey, 'execute'> = start;
    let payload = initialPayload;
    let sequenceRunId = initialRunId;
    while (true) {
      const response = await perform(stage, {
        ...payload,
        ...(sequenceRunId ? { run_id: sequenceRunId } : {}),
      }, sequenceRunId);
      if (!response) return;
      sequenceRunId = responseRunId(response, sequenceRunId);
      if (stage === 'discover') {
        const created = response.dossier as DirectorDossier;
        if (selectedIdRef.current === sequenceRunId) stageScroll('attack');
        if (!settings.autoAdvance) return;
        if (!settings.skipIndependentAttack && settings.criticProvider === proposerIdentity(created).provider) {
          setStageErrorsByRun((current) => ({
            ...current,
            [runKey(sequenceRunId)]: {
              ...current[runKey(sequenceRunId)],
              attack: 'The reviewer must use a different provider from the scout.',
            },
          }));
          return;
        }
        stage = 'attack';
        payload = attackPayload(created.dossier_id, settings, settings.skipIndependentAttack);
        continue;
      }
      if (stage === 'attack') {
        const reviewed = response.adjudication as DirectorAdjudication;
        if (selectedIdRef.current === sequenceRunId) stageScroll('qualify');
        if (!settings.autoAdvance || !reviewed.approved || reviewed.dossier.has_data_gap) return;
        stage = 'qualify'; payload = qualifyPayload(reviewed.dossier.dossier_id, settings); continue;
      }
      if (stage === 'qualify') {
        const qualified = response.qualification as DirectorQualification;
        if (selectedIdRef.current === sequenceRunId) stageScroll('compile');
        if (!settings.autoAdvance || !qualified.approved) return;
        stage = 'compile'; payload = compilePayload(qualified.qualification_id, settings); continue;
      }
      if (selectedIdRef.current === sequenceRunId) stageScroll('execute');
      return;
    }
  };

  const startDiscovery = () => {
    const settings = sequenceSettings();
    const runId = newRunId();
    chooseRun(runId);
    return runSafeSequence('discover', {
      lens, family, hint, provider: scoutProvider, model: modelPayload(scoutModel),
    }, settings, runId);
  };
  const startAttack = async () => {
    if (!dossier) return;
    if (criticProvider === reviewerExclusion) {
      setStageErrorsByRun((current) => ({
        ...current,
        [runKey(selectedId)]: {
          ...current[runKey(selectedId)],
          attack: 'The reviewer must use a different provider from the scout.',
        },
      }));
      stageScroll('attack'); return;
    }
    const settings = sequenceSettings();
    const actionKey = runKey(selectedId || dossier.dossier_id);
    setAttackActionsByRun((current) => ({ ...current, [actionKey]: 'review' }));
    try {
      await runSafeSequence('attack', attackPayload(dossier.dossier_id, settings), settings, selectedId || dossier.dossier_id);
    } finally {
      setAttackActionsByRun((current) => {
        const next = { ...current };
        delete next[actionKey];
        return next;
      });
    }
  };
  const skipAttack = async () => {
    if (!dossier) return;
    const settings = sequenceSettings();
    const actionKey = runKey(selectedId || dossier.dossier_id);
    setAttackActionsByRun((current) => ({ ...current, [actionKey]: 'skip' }));
    try {
      await runSafeSequence('attack', attackPayload(dossier.dossier_id, settings, true), settings, selectedId || dossier.dossier_id);
    } finally {
      setAttackActionsByRun((current) => {
        const next = { ...current };
        delete next[actionKey];
        return next;
      });
    }
  };
  const waiveFailedAttack = async () => {
    if (!dossier) return;
    const settings = sequenceSettings();
    const actionKey = runKey(selectedId || dossier.dossier_id);
    setAttackActionsByRun((current) => ({ ...current, [actionKey]: 'waive' }));
    try {
      await runSafeSequence('attack', {
        dossier_id: dossier.dossier_id,
        waive_failed_independent_attack: true,
        waiver_reason: 'Owner chose to continue after reviewing the failed independent attack; objections remain attached.',
      }, settings, selectedId || dossier.dossier_id);
    } finally {
      setAttackActionsByRun((current) => {
        const next = { ...current };
        delete next[actionKey];
        return next;
      });
    }
  };
  const startQualify = () => {
    const settings = sequenceSettings();
    if (dossier && settings.signalName.trim()) {
      runSafeSequence('qualify', qualifyPayload(dossier.dossier_id, settings), settings, selectedId || dossier.dossier_id);
    }
  };
  const startCompile = () => {
    const settings = sequenceSettings();
    if (qualification && dossier) {
      runSafeSequence('compile', compilePayload(qualification.qualification_id, settings), settings, selectedId || dossier.dossier_id);
    }
  };

  const exposurePercent = state.exposure.weekly_ceiling
    ? Math.min(100, (state.exposure.weekly_used / state.exposure.weekly_ceiling) * 100) : 0;
  const localSelectedOperation = operationsByRun[runKey(selectedId)] || null;
  const recoveringMissingRun = Boolean(
    selectedId?.startsWith('RUN_') && !selectedRun && !localSelectedOperation);
  const recoveredOperation: ActiveOperation | null = selectedRun?.status === 'running'
      && selectedRun.stage !== 'complete'
    ? {
        ...activityFor(selectedRun.stage as StageKey, {
          ...selectedRun.config,
          provider: selectedRun.provider,
          model: selectedRun.model,
        }),
        runId: selectedRun.run_id,
      }
    : recoveringMissingRun ? {
        runId: selectedId,
        stage: 'discover',
        title: 'Recovering pipeline state…',
        detail: 'Waiting for the durable server record created at dispatch.',
      } : null;
  const selectedOperation = localSelectedOperation || recoveredOperation;
  const stageErrors: Partial<Record<StageKey, string>> = {
    ...(stageErrorsByRun[runKey(selectedId)] || {}),
  };
  if (selectedRun?.status === 'failed' && selectedRun.stage !== 'complete') {
    stageErrors[selectedRun.stage as StageKey] = selectedRun.error || 'This step stopped before it completed.';
  }
  const isBusy = Boolean(localSelectedOperation || recoveringMissingRun
    || selectedRun?.status === 'running');
  const attackAction = attackActionsByRun[runKey(selectedId)] || null;

  const stageStatus = (stage: StageKey): StageStatus => {
    if (selectedOperation?.stage === stage) return 'running';
    if (stageErrors[stage]) return 'failed';
    if (stage === 'discover') return dossier ? 'complete' : 'ready';
    if (stage === 'attack') {
      if (!dossier) return 'locked';
      if (!adjudication) return 'ready';
      return adjudication.approved ? 'complete' : 'failed';
    }
    if (stage === 'qualify') {
      if (!adjudication) return 'locked';
      if (!adjudication.approved || dossier?.has_data_gap) return 'blocked';
      if (!qualification) return 'ready';
      return qualification.approved ? 'complete' : 'failed';
    }
    if (stage === 'compile') {
      if (!qualification) return 'locked';
      if (!qualification.approved) return 'blocked';
      return contract ? 'complete' : 'ready';
    }
    if (!contract) return 'locked';
    if (withdrawal) return 'blocked';
    return execution ? 'complete' : 'ready';
  };

  const persistedStep = withdrawal ? 'Contract withdrawn unopened'
    : execution
    ? ((execution as any).status === 'succeeded' ? 'Evidence recorded' : 'Execution stopped')
    : contract ? 'Awaiting your sample decision'
      : qualification ? (qualification.approved ? 'Ready to freeze' : 'E0 stopped')
        : adjudication ? (adjudication.approved
          ? (dossier?.has_data_gap ? 'Blocked by data gap' : 'Ready for E0')
          : 'Independent review stopped')
          : dossier ? (dossier.has_data_gap ? 'Blocked by data gap' : 'Ready for independent review')
            : selectedId?.startsWith('RUN_') ? 'Recovering pipeline state…' : 'Ready to discover';
  const selectedErrorStage = (['execute', 'compile', 'qualify', 'attack', 'discover'] as StageKey[])
    .find((stage) => Boolean(stageErrors[stage]));
  const errorStepLabels: Record<StageKey, string> = {
    discover: 'Discovery stopped', attack: 'Independent review stopped', qualify: 'E0 stopped',
    compile: 'Contract freeze stopped', execute: 'Execution stopped',
  };
  const currentStep = selectedOperation?.title
    || (selectedErrorStage ? errorStepLabels[selectedErrorStage] : persistedStep);
  const chooseRun = (runId: string | null) => {
    selectedIdRef.current = runId;
    setSelectedId(runId);
    setConfirmed(false);
    setShowDetails(false);
    setPipelineBrowserOpen(false);
  };
  const criticReview = adjudication?.reviews.find((review) => review.critic_role.startsWith('independent_model_critic:'));
  const attackWaiver = adjudication?.independent_attack_waiver;
  const visibleDissents = attackWaiver?.original_all_dissents || adjudication?.all_dissents || [];
  const selectedPipeline = pipelineRuns.find((item) => item.key === selectedId) || null;
  const selectedPipelineTitle = selectedPipeline
    ? condensedPipelineTitle(selectedPipeline) : 'New research pipeline';
  const selectedPipelineClaim = selectedPipeline?.dossier?.claim
    || selectedPipeline?.run?.claim || 'Configure an outcome-blind mechanism search.';
  const selectedIndicator = selectedPipeline
    ? pipelineIndicator(
        selectedPipeline.key, selectedPipeline.dossier, selectedPipeline.run,
        state, operationsByRun[selectedPipeline.key] || null, stageErrorsByRun[selectedPipeline.key])
    : { color: 'blue', label: 'Not started', running: false };
  const normalizedSearch = pipelineSearch.trim().toLowerCase();
  const filteredPipelines = pipelineRuns.filter((item) => {
    if (!normalizedSearch) return true;
    const haystack = [
      condensedPipelineTitle(item), item.dossier?.claim, item.run?.claim,
      item.dossier?.dossier_id, item.run?.run_id,
    ].filter(Boolean).join(' ').toLowerCase();
    return haystack.includes(normalizedSearch);
  });
  const discoverSummary = selectedOperation?.stage === 'discover'
    ? selectedOperation.detail
    : dossier
      ? `${selectedPipelineTitle} · ${proposer.provider || 'unknown provider'}/${proposer.model} · ${dossier.expected_horizon_days} sessions · ${dossier.min_effect_bps} bps bar`
      : selectedRun ? `${selectedRun.provider || 'Scout'} / ${selectedRun.model || 'CLI default'} · ${selectedRun.status}`
        : 'No dossier has been created yet';
  const attackSummary = selectedOperation?.stage === 'attack'
    ? selectedOperation.detail
    : adjudication
      ? `${attackWaiver ? 'Owner waiver' : adjudication.approved ? 'Approved' : 'Rejected'} · ${criticReview ? criticReview.critic_role.replace('independent_model_critic:', '') : 'deterministic gates only'} · ${visibleDissents.length} dissent${visibleDissents.length === 1 ? '' : 's'}`
      : dossier ? `Awaiting ${criticProvider || 'reviewer'} / ${criticModel || 'CLI default'}` : 'Waiting for a dossier';
  const qualifySummary = selectedOperation?.stage === 'qualify'
    ? selectedOperation.detail
    : qualification
      ? `${qualification.signal_name} · ${qualification.approved ? 'E0 passed' : 'E0 stopped'} · ${qualification.provider}/${qualification.model || 'CLI default'} · coverage ${objectValue(qualification.preflight, ['coverage', 'coverage_fraction'])}`
      : adjudication?.approved && !dossier?.has_data_gap
        ? `Ready to author ${signalName || 'a signal'} with ${authorProvider || 'author'} / ${authorModel || 'CLI default'}`
        : dossier?.has_data_gap ? 'Blocked by the dossier data contract' : 'Waiting for an approved review';
  const compileSummary = selectedOperation?.stage === 'compile'
    ? selectedOperation.detail
    : contract
      ? `${contract.contract_id} · ${contract.min_magnitude_bps} bps · t ≥ ${contract.min_significance_t} · ${contract.exposure_level_incurred}`
      : qualification?.approved ? `${qualification.signal_name} passed E0 and is ready to freeze` : 'Waiting for an approved qualification';
  const executeSummary = selectedOperation?.stage === 'execute'
    ? selectedOperation.detail
    : withdrawal ? `Withdrawn unopened · ${withdrawal.reason}`
      : execution ? `${String((execution as any).status || 'recorded')} · ${contract?.contract_id || 'contract'}`
        : contract ? `${contract.contract_id} · awaiting explicit outcome access · budget ${state.exposure.weekly_used}/${state.exposure.weekly_ceiling}`
          : 'No frozen contract yet';

  return <Box p={{ base: 'md', md: 'xl' }} style={{ maxWidth: 1120, margin: '0 auto' }}>
    <Group justify="space-between" align="flex-start" mb="lg">
      <Group gap="sm">
        <ThemeIcon size={40} radius="lg" variant="gradient" gradient={{ from: 'violet', to: 'cyan' }}><IconGitBranch size={21} /></ThemeIcon>
        <Box><Text size="xl" fw={800}>Alpha research pipeline</Text><Text size="sm" c="dimmed">Safe stages can run end-to-end. Sample access always waits for you.</Text></Box>
      </Group>
      <Button variant="subtle" leftSection={<IconRefresh size={15} />} onClick={() => reload()}>Refresh</Button>
    </Group>

    <Paper radius="lg" mb="md" style={{ borderColor: 'var(--border-light)', overflow: 'hidden' }}>
      <Box p="md">
        <Group justify="space-between" align="flex-start" gap="md" wrap="nowrap">
          <Group align="flex-start" gap="sm" wrap="nowrap" style={{ minWidth: 0, flex: 1 }}>
            <ThemeIcon size={34} radius="md" variant="light" color={selectedIndicator.color}>
              {selectedIndicator.running ? <Loader size={15} color={selectedIndicator.color} /> : <IconGitBranch size={17} />}
            </ThemeIcon>
            <Box style={{ minWidth: 0, flex: 1 }}>
              <Group gap="xs" wrap="nowrap">
                <Text fw={800} size="md" truncate>{selectedPipelineTitle}</Text>
                <Badge size="xs" color={selectedIndicator.color} variant="light" style={{ flexShrink: 0 }}>
                  {selectedIndicator.label}
                </Badge>
              </Group>
              <Text size="xs" c="dimmed" mt={3} lineClamp={2}>{selectedPipelineClaim}</Text>
              {selectedPipeline && <Text size="10px" c="dimmed" mt={5} ff="monospace">
                {selectedPipeline.dossier?.dossier_id || selectedPipeline.run?.run_id || selectedPipeline.key}
              </Text>}
            </Box>
          </Group>
          <Group gap="xs" wrap="nowrap">
            <Button variant="default" size="xs" onClick={() => setPipelineBrowserOpen((open) => !open)}>
              {pipelineBrowserOpen ? 'Close browser' : `Browse ${pipelineRuns.length}`}
            </Button>
            <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => {
              setLens(nextScoutLens(state));
              chooseRun(null);
              stageScroll('discover');
            }}>New</Button>
          </Group>
        </Group>
      </Box>
      <Collapse expanded={pipelineBrowserOpen}>
        <Box px="md" pb="md" style={{ borderTop: '1px solid var(--border)', paddingTop: 12 }}>
          <TextInput value={pipelineSearch} onChange={(event) => setPipelineSearch(event.currentTarget.value)}
            leftSection={<IconSearch size={14} />} placeholder="Search title, claim, run or dossier ID…"
            aria-label="Search pipelines" mb="xs" />
          <ScrollArea.Autosize mah={330} type="auto" offsetScrollbars>
            <Stack gap={4} role="listbox" aria-label="Choose a pipeline">
              {filteredPipelines.map((item) => {
                const indicator = pipelineIndicator(
                  item.key, item.dossier, item.run, state,
                  operationsByRun[item.key] || null, stageErrorsByRun[item.key]);
                const selected = selectedId === item.key;
                const claim = item.dossier?.claim || item.run?.claim || 'Discovery has not produced a dossier yet.';
                return <UnstyledButton key={item.key} role="option" aria-selected={selected}
                  onClick={() => chooseRun(item.key)} style={{ width: '100%' }}>
                  <Box px="sm" py={9} style={{
                    borderLeft: `3px solid ${selected ? 'var(--mantine-color-blue-6)' : 'transparent'}`,
                    background: selected ? 'rgba(34, 139, 230, .09)' : 'transparent',
                    borderRadius: 6,
                  }}>
                    <Group justify="space-between" gap="sm" wrap="nowrap">
                      <Box style={{ minWidth: 0, flex: 1 }}>
                        <Text size="sm" fw={750} truncate>{condensedPipelineTitle(item)}</Text>
                        <Text size="xs" c="dimmed" lineClamp={1}>{claim}</Text>
                      </Box>
                      <Box style={{ flexShrink: 0, textAlign: 'right' }}>
                        <Badge size="xs" color={indicator.color} variant="light">{indicator.label}</Badge>
                        <Text size="9px" c="dimmed" mt={3} ff="monospace">
                          {(item.dossier?.dossier_id || item.run?.run_id || item.key).slice(-12)}
                        </Text>
                      </Box>
                    </Group>
                  </Box>
                </UnstyledButton>;
              })}
              {filteredPipelines.length === 0 && <Text size="sm" c="dimmed" ta="center" py="lg">
                No pipelines match “{pipelineSearch}”.
              </Text>}
            </Stack>
          </ScrollArea.Autosize>
        </Box>
      </Collapse>
    </Paper>

    <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm" mb="xl">
      <Paper p="md" radius="lg"><Text size="xs" c="dimmed" fw={700}>CURRENT STATE</Text><Group gap="xs" mt={3} wrap="nowrap">{selectedOperation && <Loader size="xs" color="violet" />}<Text fw={700}>{currentStep}</Text></Group>{selectedOperation && <Text size="xs" c="dimmed" mt={4}>{selectedOperation.detail}</Text>}</Paper>
      <Paper p="md" radius="lg"><Group justify="space-between" mb={4}><Text size="xs" c="dimmed" fw={700}>SAFE AUTOMATION</Text><Switch checked={autoAdvance} onChange={(event) => setAutoAdvance(event.currentTarget.checked)} /></Group><Text size="xs">{autoAdvance ? 'Runs through contract freeze' : 'Stops after each card'}</Text></Paper>
      <Paper p="md" radius="lg"><Group justify="space-between"><Text size="xs" c="dimmed" fw={700}>SAMPLE BUDGET</Text><Badge color={state.exposure.allowed ? 'teal' : 'red'}>{state.exposure.weekly_used}/{state.exposure.weekly_ceiling}</Badge></Group><Progress value={exposurePercent} mt={8} color={exposurePercent >= 100 ? 'red' : 'blue'} /></Paper>
    </SimpleGrid>

    <StageCard key={`${selectedId || NEW_RUN_KEY}-discover`} stage="discover" number={1} title="Discover a mechanism" subtitle="Outcome-blind proposal using the current catalogue and full research ledger." summary={discoverSummary} status={stageStatus('discover')} icon={<IconSparkles size={18} />} error={stageErrors.discover} activity={selectedOperation?.stage === 'discover' ? selectedOperation : null}>
      {!dossier ? <Stack gap="md">
        <ProviderPicker title="Scout model" provider={scoutProvider} model={scoutModel} catalogue={providers} onProvider={setScoutProvider} onModel={setScoutModel} disabled={isBusy} note="Creates the dossier. The reviewer must use another provider lane; changing only the model is not enough." />
        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
          <Select label="Research lens" description="Defaults to the next lens after the most recent scout run; you can still override it." value={lens} onChange={(value) => setLens(value || 'market_structure')} data={SCOUT_LENSES.map((item) => ({ ...item }))} />
          <TextInput label="Family" value={family} onChange={(event) => setFamily(event.currentTarget.value)} />
        </SimpleGrid>
        <Textarea label="Optional direction" placeholder="Leave blank for a broad search, or name a behavior worth exploring." value={hint} onChange={(event) => setHint(event.currentTarget.value)} autosize minRows={2} maxRows={4} />
        {autoAdvance && <Checkbox checked={skipIndependentAttack} onChange={(event) => setSkipIndependentAttack(event.currentTarget.checked)} label="Skip the independent model attack in this safe run" description="Deterministic leakage, novelty, economics and power gates still run." />}
        <Group justify="space-between"><Text size="xs" c="dimmed">No outcomes or sample budget are touched.</Text><Button leftSection={<IconSparkles size={16} />} loading={selectedOperation?.stage === 'discover'} onClick={startDiscovery} disabled={!providers || isBusy}>{selectedOperation?.stage === 'discover' ? 'Discovering…' : autoAdvance ? 'Run safe pipeline' : 'Create dossier'}</Button></Group>
      </Stack> : <Stack gap="sm">
        <Group justify="space-between" align="flex-start" wrap="nowrap"><Box style={{ minWidth: 0 }}><Text fw={700} lineClamp={3}>{dossier.claim}</Text><Text size="xs" c="dimmed" mt={5} lineClamp={2}>{dossier.population}</Text></Box><Badge color={dossier.bootstrap_ready ? 'teal' : 'yellow'} variant="light" style={{ flexShrink: 0 }}>{dossier.bootstrap_ready ? 'Bootstrap ready' : 'Data gap'}</Badge></Group>
        <Group gap="xs" wrap="wrap"><Badge variant="outline">{dossier.expected_horizon_days} sessions</Badge><Badge variant="outline">{dossier.min_effect_bps} bps bar</Badge><Badge variant="outline">${dossier.estimated_cash_cost_usd || 0} data</Badge><Badge variant="outline">{dossier.estimated_engineering_days || 0} eng days</Badge><Badge variant="outline">{proposer.provider} / {proposer.model}</Badge></Group>
        <Button variant="subtle" size="compact-sm" w="fit-content" rightSection={showDetails ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />} onClick={() => setShowDetails((value) => !value)}>{showDetails ? 'Hide dossier detail' : 'View dossier detail'}</Button>
        <Collapse expanded={showDetails}><SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
          <Box><Text size="xs" fw={700} c="dimmed">MECHANISM</Text><Text size="sm" mt={5}>{listText(dossier.causal_chain).slice(0, 3).join(' → ')}</Text></Box>
          <Box><Text size="xs" fw={700} c="dimmed">COUNTERPARTY</Text><Text size="sm" mt={5}>{dossier.counterparty}</Text></Box>
          <Box><Text size="xs" fw={700} c="dimmed">UNIQUE PREDICTIONS</Text>{dossier.unique_predictions.slice(0, 3).map((item, index) => <Text size="xs" mt={4} key={index}>• {toText(item)}</Text>)}</Box>
          <Box><Text size="xs" fw={700} c="dimmed">DATA</Text><Text size="xs" mt={4}>{dossier.available_observations?.length || 0} available · {dossier.required_observations_absent?.length || 0} blocking · {dossier.optional_observations_absent?.length || 0} optional</Text><Text size="xs" c="dimmed" mt={4}>Lineage: {dossier.nearest_hypothesis_ids?.join(', ') || 'missing'}</Text></Box>
        </SimpleGrid></Collapse>
      </Stack>}
    </StageCard>

    <StageCard key={`${selectedId || NEW_RUN_KEY}-attack`} stage="attack" number={2} title="Independent attack" subtitle="A separate provider challenges mechanism, leakage, power, costs and novelty." summary={attackSummary} status={stageStatus('attack')} icon={<IconShieldCheck size={18} />} error={stageErrors.attack} activity={selectedOperation?.stage === 'attack' ? selectedOperation : null}>
      {!dossier ? <LockedMessage>Create a dossier first.</LockedMessage> : adjudication ? <Stack gap="sm">
        <Group justify="space-between"><Box><Text fw={700} c={adjudication.approved ? 'teal.3' : 'red.3'}>{attackWaiver ? 'Continuing under owner waiver' : adjudication.approved ? 'Approved for E0' : 'Rejected before sample use'}</Text><Text size="xs" c="dimmed" mt={3}>{adjudication.verdict}</Text></Box>{attackWaiver ? <Badge color="yellow" variant="light">Attack waived after failure</Badge> : criticReview ? <Badge variant="outline">{criticReview.critic_role.replace('independent_model_critic:', '')}</Badge> : <Badge color="yellow" variant="light">Model attack skipped</Badge>}</Group>
        {visibleDissents.length > 0 && <Box>{visibleDissents.slice(0, 3).map((item, index) => <Text size="xs" mt={4} key={index} c={item.severity === 'fatal' ? 'red.3' : 'yellow.3'}>{item.severity.toUpperCase()} · {item.objection}</Text>)}</Box>}
        {attackWaiver && <Alert color="yellow" icon={<IconAlertTriangle size={16} />} title="Original rejection preserved">The failed critique and its objections remain attached to this dossier. Continuing does not resolve them.</Alert>}
        {!adjudication.approved && criticReview && !attackWaiver && <Alert color="yellow" icon={<IconAlertTriangle size={16} />} title="Override available">You can continue through deterministic gates without treating this failed model critique as blocking. The rejection and every dissent will remain attached.<Group justify="flex-end" mt="sm"><Button color="yellow" variant="light" loading={selectedOperation?.stage === 'attack' && attackAction === 'waive'} disabled={isBusy} onClick={waiveFailedAttack}>{selectedOperation?.stage === 'attack' && attackAction === 'waive' ? 'Applying waiver…' : 'Continue without independent attack'}</Button></Group></Alert>}
      </Stack> : <Stack gap="md">
        <ProviderPicker title="Reviewer model" provider={criticProvider} model={criticModel} catalogue={providers} excludeProvider={reviewerExclusion} onProvider={setCriticProvider} onModel={setCriticModel} disabled={isBusy} note={`Must use a different provider lane from the scout (${reviewerExclusion || 'not selected'}); changing only the model is not allowed.`} />
        <Group justify="space-between" align="center"><Text size="xs" c="dimmed">Skipping removes the independent model critique, but not the deterministic preflight gates.</Text><Group gap="xs"><Button variant="subtle" color="yellow" loading={selectedOperation?.stage === 'attack' && attackAction === 'skip'} onClick={skipAttack} disabled={isBusy}>{selectedOperation?.stage === 'attack' && attackAction === 'skip' ? 'Running gates…' : 'Skip independent attack'}</Button><Button variant="light" loading={selectedOperation?.stage === 'attack' && attackAction === 'review'} onClick={startAttack} disabled={isBusy || criticProvider === reviewerExclusion}>{selectedOperation?.stage === 'attack' && attackAction === 'review' ? 'Reviewing…' : 'Run attack'}</Button></Group></Group>
      </Stack>}
    </StageCard>

    <StageCard key={`${selectedId || NEW_RUN_KEY}-qualify`} stage="qualify" number={3} title="Author signal + E0 gates" subtitle="The selected model writes one deterministic score; the harness checks structure without returns." summary={qualifySummary} status={stageStatus('qualify')} icon={<IconFlask size={18} />} error={stageErrors.qualify} activity={selectedOperation?.stage === 'qualify' ? selectedOperation : null}>
      {!adjudication ? <LockedMessage>Independent review comes first.</LockedMessage>
        : !adjudication.approved ? <LockedMessage>The dossier was rejected. Start a new branch instead.</LockedMessage>
        : dossier?.has_data_gap ? <LockedMessage>Resolve the blocking data contract before qualification.</LockedMessage>
        : qualification ? <Stack gap="sm">
          <Group justify="space-between"><Text fw={700} c={qualification.approved ? 'teal.3' : 'red.3'}>{qualification.approved ? 'All E0 gates passed' : 'E0 rejected the signal'}</Text><Badge variant="outline">{qualification.provider} / {qualification.model || 'cli-default'}</Badge></Group>
          <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="xs">
            <Paper p="sm" bg="#0d1117"><Text size="xs" c="dimmed">Coverage</Text><Text fw={700}>{objectValue(qualification.preflight, ['coverage', 'coverage_fraction'])}</Text></Paper>
            <Paper p="sm" bg="#0d1117"><Text size="xs" c="dimmed">Independent blocks</Text><Text fw={700}>{objectValue(qualification.structural_gate, ['estimated_independent_blocks', 'independent_blocks'])}</Text></Paper>
            <Paper p="sm" bg="#0d1117"><Text size="xs" c="dimmed">Signal hash</Text><Code>{qualification.signal_source_hash.slice(0, 10)}</Code></Paper>
          </SimpleGrid>
          {!qualification.approved && <Text size="xs" c="red.3">{qualification.rejection_reasons.join(' · ')}</Text>}
        </Stack> : <Stack gap="md">
          <ProviderPicker title="Signal author model" provider={authorProvider} model={authorModel} catalogue={providers} onProvider={setAuthorProvider} onModel={setAuthorModel} disabled={isBusy} note="This role authors predictor code only. It receives no outcomes and has no tools." />
          <TextInput label="Signal name" value={signalName} onChange={(event) => setSignalName(event.currentTarget.value)} />
          <Group justify="flex-end"><Button loading={selectedOperation?.stage === 'qualify'} onClick={startQualify} disabled={isBusy || !signalName.trim()}>{selectedOperation?.stage === 'qualify' ? 'Authoring and checking…' : 'Author and run E0'}</Button></Group>
        </Stack>}
    </StageCard>

    <StageCard key={`${selectedId || NEW_RUN_KEY}-compile`} stage="compile" number={4} title="Freeze experiment contract" subtitle="Lock the bar, cost, capacity, population and signal identity before outcomes exist." summary={compileSummary} status={stageStatus('compile')} icon={<IconFileCheck size={18} />} error={stageErrors.compile} activity={selectedOperation?.stage === 'compile' ? selectedOperation : null}>
      {!qualification ? <LockedMessage>The signal must pass E0 first.</LockedMessage>
        : !qualification.approved ? <LockedMessage>E0 failed; no contract can be frozen.</LockedMessage>
        : contract ? <Stack gap="sm">
          <Group justify="space-between"><Code>{contract.contract_id}</Code><Badge color="teal">Frozen</Badge></Group>
          <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="xs"><Paper p="sm" bg="#0d1117"><Text size="xs" c="dimmed">Magnitude bar</Text><Text fw={700}>{contract.min_magnitude_bps} bps</Text></Paper><Paper p="sm" bg="#0d1117"><Text size="xs" c="dimmed">Significance</Text><Text fw={700}>t ≥ {contract.min_significance_t}</Text></Paper><Paper p="sm" bg="#0d1117"><Text size="xs" c="dimmed">Exposure</Text><Text fw={700}>{contract.exposure_level_incurred}</Text></Paper></SimpleGrid>
          <Alert color="blue" icon={<IconCheck size={15} />}>Safe automation stopped here. No outcomes have been read.</Alert>
        </Stack> : <Stack gap="md">
          <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm"><TextInput label="Round-trip cost (bps)" value={costBps} onChange={(event) => setCostBps(event.currentTarget.value)} /><TextInput label="Capacity (INR)" value={capacityInr} onChange={(event) => setCapacityInr(event.currentTarget.value)} /><TextInput label="Minimum t" value={minT} onChange={(event) => setMinT(event.currentTarget.value)} /></SimpleGrid>
          <Group justify="space-between"><Text size="xs" c="dimmed">Freezing is outcome-blind and does not spend the sample.</Text><Button leftSection={<IconLock size={15} />} loading={selectedOperation?.stage === 'compile'} onClick={startCompile} disabled={isBusy}>{selectedOperation?.stage === 'compile' ? 'Freezing…' : 'Freeze contract'}</Button></Group>
        </Stack>}
    </StageCard>

    <StageCard key={`${selectedId || NEW_RUN_KEY}-execute`} stage="execute" number={5} title="Reveal outcomes" subtitle="The only sample-bearing step. It is never triggered by automation." summary={executeSummary} status={stageStatus('execute')} icon={<IconDatabase size={18} />} error={stageErrors.execute} activity={selectedOperation?.stage === 'execute' ? selectedOperation : null} last>
      {!contract ? <LockedMessage>Freeze an experiment contract first.</LockedMessage> : withdrawal ? <Alert color="yellow" icon={<IconAlertTriangle size={16} />} title="Withdrawn unopened">{withdrawal.reason}</Alert> : execution ? <Stack gap="sm">
        <Group justify="space-between"><Text fw={700} c={(execution as any).status === 'succeeded' ? 'teal.3' : 'red.3'}>Outcome-bearing execution recorded</Text><Badge>{String((execution as any).status || 'unknown')}</Badge></Group>
        <Code block style={{ maxHeight: 240, overflow: 'auto', fontSize: 11 }}>{JSON.stringify((execution as any).result || execution, null, 2)}</Code>
      </Stack> : <Stack gap="md">
        <Alert color="orange" icon={<IconAlertTriangle size={16} />} title="Manual boundary">This spends one {contract.exposure_level_incurred} attempt and publishes the full registered report. Safe automation cannot cross this card.</Alert>
        <Checkbox checked={confirmed} onChange={(event) => setConfirmed(event.currentTarget.checked)} label={`I intend to spend the sample on ${contract.contract_id}`} />
        <Group justify="space-between"><Text size="xs" c="dimmed">Weekly usage: {state.exposure.weekly_used}/{state.exposure.weekly_ceiling}</Text><Button color="orange" leftSection={<IconPlayerPlay size={15} />} loading={selectedOperation?.stage === 'execute'} disabled={!confirmed || !state.exposure.allowed || isBusy} onClick={async () => { await perform('execute', { run_id: selectedId, contract_id: contract.contract_id, confirm_outcome_access: true }, selectedId); setConfirmed(false); }}>{selectedOperation?.stage === 'execute' ? 'Executing…' : 'Execute one-shot test'}</Button></Group>
      </Stack>}
    </StageCard>

    <Group justify="center" gap="xs" mt="xl" c="dimmed"><IconRobot size={15} /><Text size="xs">State refreshes every two seconds, including while a stage is running. Every error stays attached to its card.</Text></Group>
  </Box>;
};
