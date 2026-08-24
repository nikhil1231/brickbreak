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
  CompareResult,
  BreezeSettings,
  BreezeTotp,
  SetupReviewSummary,
  SetupReviewQueue,
  SetupReviewCase,
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

export async function fetchBreezeSettings(signal?: AbortSignal): Promise<BreezeSettings> {
  const res = await fetch(`${API_BASE}/api/settings/breeze`, { signal });
  if (!res.ok) throw new Error(`Failed to fetch Breeze settings: ${res.statusText}`);
  return res.json();
}

export async function fetchBreezeTotp(signal?: AbortSignal): Promise<BreezeTotp> {
  const res = await fetch(`${API_BASE}/api/settings/breeze/totp`, { signal, cache: 'no-store' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Failed to generate Breeze TOTP: ${res.statusText}`);
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

async function setupReviewResponse<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `${fallback}: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchSetupReviewQueues(signal?: AbortSignal): Promise<SetupReviewSummary[]> {
  const res = await fetch(`${API_BASE}/api/setup-reviews`, { signal, cache: 'no-store' });
  const data = await setupReviewResponse<{ queues: SetupReviewSummary[] }>(res, 'Could not load setup reviews');
  return data.queues;
}

export async function fetchSetupReview(
  reviewId: string,
  annotator: string,
  signal?: AbortSignal
): Promise<SetupReviewQueue> {
  const params = new URLSearchParams({ annotator });
  const res = await fetch(`${API_BASE}/api/setup-reviews/${encodeURIComponent(reviewId)}?${params}`, {
    signal,
    cache: 'no-store',
  });
  return setupReviewResponse<SetupReviewQueue>(res, 'Could not load the review queue');
}

export async function fetchSetupReviewCase(
  reviewId: string,
  caseId: string,
  annotator: string,
  signal?: AbortSignal
): Promise<SetupReviewCase> {
  const params = new URLSearchParams({ annotator });
  const res = await fetch(
    `${API_BASE}/api/setup-reviews/${encodeURIComponent(reviewId)}/cases/${encodeURIComponent(caseId)}?${params}`,
    { signal, cache: 'no-store' }
  );
  return setupReviewResponse<SetupReviewCase>(res, 'Could not load the setup');
}

export async function saveSetupReviewDraft(
  reviewId: string,
  annotator: string,
  caseId: string,
  values: Record<string, unknown>
): Promise<SetupReviewQueue> {
  const res = await fetch(`${API_BASE}/api/setup-reviews/${encodeURIComponent(reviewId)}/draft`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ annotator, case_id: caseId, values }),
  });
  return setupReviewResponse<SetupReviewQueue>(res, 'Could not save the review');
}

export async function finalizeSetupReview(
  reviewId: string,
  annotator: string
): Promise<SetupReviewQueue> {
  const res = await fetch(`${API_BASE}/api/setup-reviews/${encodeURIComponent(reviewId)}/finalize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ annotator }),
  });
  return setupReviewResponse<SetupReviewQueue>(res, 'Could not finalize the review');
}
