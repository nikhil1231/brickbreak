import {
  ScreenConfig,
  ScreenResponse,
  ScreenerMeta,
  SymbolDetail,
  Hypothesis,
  IdeaGraphData,
  LedgerData,
  CatalogueData,
  ProviderCatalogue,
  ExplorationResult,
  CompareResult,
  SuggestionInbox,
  JobsResponse,
} from '../types';

const API_BASE = '';

export async function fetchMeta(signal?: AbortSignal): Promise<ScreenerMeta> {
  const res = await fetch(`${API_BASE}/api/meta`, { signal });
  if (!res.ok) throw new Error(`Failed to fetch metadata: ${res.statusText}`);
  return res.json();
}

export async function runScreen(
  config: Partial<ScreenConfig>,
  date?: string,
  signal?: AbortSignal
): Promise<ScreenResponse> {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(config)) {
    if (v !== undefined && v !== null && v !== '') {
      if (typeof v === 'boolean') {
        params.set(k, v ? '1' : '0');
      } else {
        params.set(k, String(v));
      }
    }
  }
  if (date) {
    params.set('date', date);
  }

  const res = await fetch(`${API_BASE}/api/screen?${params.toString()}`, { signal });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Screening failed: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchSymbol(symbol: string, n: number = 120, signal?: AbortSignal): Promise<SymbolDetail> {
  const params = new URLSearchParams({ symbol, n: String(n) });
  const res = await fetch(`${API_BASE}/api/symbol?${params.toString()}`, { signal });
  if (!res.ok) throw new Error(`Failed to fetch symbol ${symbol}: ${res.statusText}`);
  return res.json();
}

export async function fetchHypotheses(signal?: AbortSignal): Promise<Hypothesis[]> {
  const res = await fetch(`${API_BASE}/api/hypotheses`, { signal });
  if (!res.ok) throw new Error(`Failed to fetch hypotheses: ${res.statusText}`);
  return res.json();
}

export async function fetchHypothesisDetail(id: string, signal?: AbortSignal): Promise<Hypothesis> {
  const res = await fetch(`${API_BASE}/api/hypotheses/${id}`, { signal });
  if (!res.ok) throw new Error(`Failed to fetch hypothesis ${id}: ${res.statusText}`);
  return res.json();
}

export async function createHypothesis(
  payload: {
    statement: string;
    rationale: string;
    family: string;
    parent_id?: string;
    relation?: string;
  },
  signal?: AbortSignal
): Promise<Hypothesis> {
  const res = await fetch(`${API_BASE}/api/hypotheses`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Hypothesis registration failed: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchIdeaGraph(signal?: AbortSignal): Promise<IdeaGraphData> {
  const res = await fetch(`${API_BASE}/api/idea-graph`, { signal });
  if (!res.ok) throw new Error(`Failed to fetch idea graph: ${res.statusText}`);
  return res.json();
}

export async function fetchLedger(signal?: AbortSignal): Promise<LedgerData> {
  const res = await fetch(`${API_BASE}/api/ledger`, { signal });
  if (!res.ok) throw new Error(`Failed to fetch budget ledger: ${res.statusText}`);
  return res.json();
}

export async function fetchCatalogue(signal?: AbortSignal): Promise<CatalogueData> {
  const res = await fetch(`${API_BASE}/api/catalogue`, { signal });
  if (!res.ok) throw new Error(`Failed to fetch feature catalogue: ${res.statusText}`);
  return res.json();
}

export async function fetchProviders(signal?: AbortSignal): Promise<ProviderCatalogue> {
  const res = await fetch(`${API_BASE}/api/providers`, { signal });
  if (!res.ok) throw new Error(`Failed to fetch LLM providers: ${res.statusText}`);
  return res.json();
}

export async function fetchJobs(signal?: AbortSignal): Promise<JobsResponse> {
  const res = await fetch(`${API_BASE}/api/jobs`, { signal });
  if (!res.ok) throw new Error(`Failed to fetch explorations: ${res.statusText}`);
  return res.json();
}

export async function fetchSuggestions(signal?: AbortSignal): Promise<SuggestionInbox> {
  const res = await fetch(`${API_BASE}/api/suggestions`, { signal });
  if (!res.ok) throw new Error(`Failed to fetch suggestions: ${res.statusText}`);
  return res.json();
}

async function postSuggestions(
  path: string,
  body: Record<string, unknown>,
  signal?: AbortSignal
): Promise<SuggestionInbox> {
  const res = await fetch(`${API_BASE}/api/suggestions/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Suggestion ${path} failed: ${res.statusText}`);
  }
  return res.json();
}

export async function generateSuggestions(
  payload: { provider: string; model?: string; count?: number; slots?: number[] },
  signal?: AbortSignal
): Promise<SuggestionInbox> {
  return postSuggestions('generate', payload, signal);
}

export async function promoteSuggestion(
  payload: { id: string },
  signal?: AbortSignal
): Promise<SuggestionInbox & { hypothesis_id: string }> {
  return postSuggestions('promote', payload, signal) as Promise<
    SuggestionInbox & { hypothesis_id: string }
  >;
}

export async function refreshSuggestion(
  payload: { id: string; provider: string; model?: string },
  signal?: AbortSignal
): Promise<SuggestionInbox> {
  return postSuggestions('refresh', payload, signal);
}

export async function runExploration(
  payload: {
    hypothesis_id: string;
    question: string;
    signal_name: string;
    partition: string;
    role?: string;
    provider: string;
    model?: string;
    suggestion_id?: string;
    idea?: string;
  },
  signal?: AbortSignal
): Promise<ExplorationResult> {
  const res = await fetch(`${API_BASE}/api/explore`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const jobContext = err.job_id
      ? ` (job ${err.job_id}${err.provider ? ` via ${err.provider}` : ''})`
      : '';
    const requestError = new Error(
      (err.error || `Exploration failed: ${res.statusText}`) + jobContext
    ) as Error & { hypothesisId?: string };
    requestError.hypothesisId = err.hypothesis_id;
    throw requestError;
  }
  return res.json();
}

export async function runCompare(signals: string[], signal?: AbortSignal): Promise<CompareResult> {
  const res = await fetch(`${API_BASE}/api/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ signals }),
    signal,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Compare failed: ${res.statusText}`);
  }
  return res.json();
}
