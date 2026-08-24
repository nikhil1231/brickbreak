// Screener Types
export interface ScreenConfig {
  min_size_rank?: number | null;
  max_size_rank?: number | null;
  min_median_tv_cr?: number | null;
  min_price?: number | null;
  sector_mode?: string;
  sector_min_slope?: number | null;
  sector_min_breadth?: number | null;
  sector_require_labelled?: boolean;
  require_ema_stack?: boolean;
  require_above_ema_mid?: boolean;
  min_ret_60d?: number | null;
  max_atr_ratio?: number | null;
  max_base_depth?: number | null;
  max_bb_width_pctile?: number | null;
  max_range_pct_ma?: number | null;
  min_contraction_steps?: number | null;
  min_small_bodies_5?: number | null;
  max_vol_squeeze?: number | null;
  require_nr_k?: boolean;
  allowed_series?: string;
}

export interface CandidateRow {
  symbol: string;
  sector?: string;
  size_tier?: string;
  size_tier_rank?: number;
  close?: number;
  median_tv_20_cr?: number;
  atr_ratio?: number;
  base_depth?: number;
  bb_width_pctile?: number;
  range_pct_ma?: number;
  contraction_steps?: number;
  nr_k?: boolean;
  n_small_bodies_5?: number;
  vol_squeeze?: number;
  px_vs_ema_fast?: number;
  ret_20d?: number;
  ret_60d?: number;
  dist_52w_high?: number;
  sector_breadth?: number;
  sec_slope?: number;
  deliv_pct?: number;
  [key: string]: any;
}

export interface SummaryStats {
  candidates_per_day: {
    mean: number;
    median: number;
    p90: number;
    max: number;
    zero_days_pct: number;
  };
  mean_per_stage: Record<string, number>;
}

export interface ScreenerSeries {
  dates: string[];
  [stage: string]: number[] | string[];
}

export interface ScreenResponse {
  config: ScreenConfig;
  summary: SummaryStats;
  series: {
    dates: string[];
    contraction: number[];
    [key: string]: number[] | string[];
  };
  selected_date: string;
  candidates: CandidateRow[];
  columns: string[];
  total_candidates: number;
  by_sector: Record<string, number>;
  error?: string;
}

export interface ScreenerMeta {
  dates: string[];
  sectors: string[];
  n_symbols: number;
  n_rows: number;
  stages: string[];
  defaults: Record<string, any>;
  size_tiers: number[];
}

export interface SymbolBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
  ema_fast?: number;
  ema_mid?: number;
  atr_ratio?: number;
  base_depth?: number;
  bb_width_pctile?: number;
}

export interface SymbolDetail {
  symbol: string;
  sector: string;
  bars: SymbolBar[];
}

// Alpha Lab Types
export interface HypothesisEdge {
  relation: string;
  target_id: string;
}

export interface Hypothesis {
  id: string;
  title: string;
  statement: string;
  rationale: string;
  family: string;
  status: 'proposed' | 'exploring' | 'promising' | 'rejected' | 'validated' | 'decayed' | 'superseded' | string;
  tags: string[];
  lineage: string[];
  created_at: string;
  updated_at: string;
  edges?: HypothesisEdge[];
  evidence?: Evidence[];
}

export interface Evidence {
  evidence_id: string;
  hypothesis_id: string;
  role: 'exploratory' | 'confirmatory' | 'generation' | string;
  partition: 'train' | 'validation' | 'test' | 'forward' | string;
  quarters: string[];
  metrics: Record<string, any>;
  verdict: 'supported' | 'rejected' | 'inconclusive' | string;
  verdict_statement: string;
  timestamp?: string;
}

export interface IdeaGraphNode {
  id: string;
  title: string;
  family: string;
  status: string;
  tags: string[];
  placeholder?: boolean;
}

export interface IdeaGraphEdge {
  source: string;
  target: string;
  relation: string;
}

export interface IdeaGraphData {
  nodes: IdeaGraphNode[];
  edges: IdeaGraphEdge[];
  summary: string;
}

export interface LedgerEntry {
  hypothesis_id: string;
  family: string;
  role: string;
  partition: string;
  quarters: string[];
  timestamp?: string;
}

export interface LedgerData {
  n_entries: number;
  entries: LedgerEntry[];
}

export interface FeatureItem {
  name: string;
  owner: string;
  available_as_of: string;
  lookback: string;
  point_in_time: boolean;
  scorable: boolean;
}

export interface CatalogueData {
  features: FeatureItem[];
  summary: string;
}

export interface ProviderModelOption {
  id: string;
  label: string;
}

export interface ProviderOption {
  id: 'claude' | 'codex' | string;
  label: string;
  available: boolean;
  default_model: string;
  models: ProviderModelOption[];
  install_hint: string;
}

export interface ProviderCatalogue {
  default_provider: string;
  providers: ProviderOption[];
}

export interface BreezeSettings {
  configured: boolean;
  has_session_token: boolean;
  session_refreshed_at: string | null;
  totp_configured: boolean;
  callback_url: string;
  login_path: string;
  login_url?: string;
  error: string | null;
}

export interface BreezeTotp {
  code: string;
  period_seconds: number;
  valid_for_seconds: number;
  expires_at: string;
}

export interface CompareResult {
  pairwise_rank_correlation?: Record<string, Record<string, number>>;
  pairwise_top_k_overlap_pct?: Record<string, Record<string, number>>;
  combined_ensemble?: {
    equal_weight?: {
      ic: number;
      t_stat: number;
    };
    rank_weight?: {
      ic: number;
      t_stat: number;
    };
  };
  error?: string;
}
