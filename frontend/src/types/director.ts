import type { ProviderCatalogue } from './index';

export type { ProviderCatalogue };

export interface CompetingExplanation {
  name?: string;
  mechanism?: string;
  distinguishing_test?: string;
  [key: string]: unknown;
}

export interface DirectorDossier {
  dossier_id: string;
  dossier_hash: string;
  hypothesis_id: string;
  family: string;
  claim: string;
  population: string;
  expected_horizon_days: number;
  causal_chain: string | string[];
  counterparty: string;
  counterparty_persistence_rationale: string | string[];
  competing_explanations: Array<string | CompetingExplanation>;
  strongest_baseline: string | Record<string, unknown>;
  unique_predictions: Array<string | Record<string, unknown>>;
  natural_falsifiers: Array<string | Record<string, unknown>>;
  confounds: Array<string | Record<string, unknown>>;
  nearest_hypothesis_ids: string[];
  min_effect_bps: number;
  available_observations: Array<string | Record<string, unknown>>;
  required_observations_absent: Array<string | Record<string, unknown>>;
  optional_observations_absent: Array<string | Record<string, unknown>>;
  estimated_engineering_days: number;
  estimated_cash_cost_usd: number;
  memory_risk_classification: string;
  forward_confirmation_path: string | string[];
  proposer: string;
  hostile_reviewer: string;
  has_data_gap: boolean;
  bootstrap_ready: boolean;
  stage: 'dossier' | 'data_gap';
  created_at: string;
}

export interface DirectorAdjudication {
  approved: boolean;
  verdict: string;
  dossier: DirectorDossier;
  reviews: Array<{
    critic_role: string;
    approved: boolean;
    score: number;
    critique: string;
  }>;
  all_dissents: Array<{
    reviewer_role: string;
    objection: string;
    severity: string;
  }>;
  independent_attack_waiver?: {
    status: 'waived_after_failure';
    waived_at: string;
    reason: string;
    original_verdict: string;
    failed_reviews: Array<{
      critic_role: string;
      approved: boolean;
      score: number;
      critique: string;
    }>;
    original_all_dissents: Array<{
      reviewer_role: string;
      objection: string;
      severity: string;
    }>;
  };
}

export interface DirectorQualification {
  qualification_id: string;
  dossier: DirectorDossier;
  signal_name: string;
  signal_source_hash: string;
  provider: string;
  model: string;
  approved: boolean;
  rejection_reasons: string[];
  structural_gate: Record<string, unknown>;
  preflight: Record<string, unknown>;
}

export interface DirectorContract {
  contract_id: string;
  qualification_id: string;
  dossier_id: string;
  hypothesis_id: string;
  signal_name: string;
  horizons: number[];
  min_magnitude_bps: number;
  min_significance_t: number;
  exposure_level_incurred: string;
  contract_hash: string;
  lifecycle: Record<string, unknown>;
}

export interface DirectorExecution {
  contract_id?: string;
  execution?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface DirectorRun {
  run_id: string;
  dossier_id: string | null;
  claim: string | null;
  stage: 'discover' | 'attack' | 'qualify' | 'compile' | 'execute' | 'complete';
  status: 'running' | 'ready' | 'failed' | 'stopped' | 'complete';
  error: string | null;
  provider: string;
  model: string;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  last_completed_stage?: string;
}

export interface DirectorState {
  runs: DirectorRun[];
  dossiers: DirectorDossier[];
  adjudications: DirectorAdjudication[];
  qualifications: DirectorQualification[];
  contracts: DirectorContract[];
  executions: DirectorExecution[];
  withdrawals: Array<{
    contract_id: string;
    status: 'withdrawn_unopened';
    reason: string;
    withdrawn_at: string;
  }>;
  exposure: {
    weekly_used: number;
    weekly_ceiling: number;
    allowed: boolean;
    total_records: number;
  };
}
