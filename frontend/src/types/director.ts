import type { ProviderCatalogue } from './index';

export type { ProviderCatalogue };

export interface DirectorDossier {
  dossier_id: string;
  dossier_hash: string;
  hypothesis_id: string;
  family: string;
  claim: string;
  population: string;
  expected_horizon_days: number;
  causal_chain: string;
  counterparty: string;
  counterparty_persistence_rationale: string;
  competing_explanations: string[];
  strongest_baseline: string;
  unique_predictions: string[];
  natural_falsifiers: string[];
  confounds: string[];
  min_effect_bps: number;
  required_observations_absent: string[];
  memory_risk_classification: string;
  forward_confirmation_path: string;
  proposer: string;
  hostile_reviewer: string;
  has_data_gap: boolean;
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

export interface DirectorState {
  dossiers: DirectorDossier[];
  adjudications: DirectorAdjudication[];
  qualifications: DirectorQualification[];
  contracts: DirectorContract[];
  executions: DirectorExecution[];
  exposure: {
    weekly_used: number;
    weekly_ceiling: number;
    allowed: boolean;
    total_records: number;
  };
}
