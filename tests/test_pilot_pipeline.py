"""End-to-end validation for Stage AC (Pilot) and Stage AD (Batch Execution)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.contracts import (
    DataContract,
    ExperimentContract,
    LifecycleState,
    LifecycleTracker,
    MechanismDossier,
    SourceFieldDef,
)
from src.council import adjudicate_dossier
from src.data_broker import create_approval_card, run_source_micro_probe, synthesize_data_contract
from src.firewall import (
    ExposureLevel,
    assert_zone_frame_access,
    evaluate_structural_gate,
    record_exposure,
)
from src.firewall.zones import FirewallZone
from src.runner import forward as forward_mod


def test_stage_ac_pilot_data_gap_dossier(tmp_path, monkeypatch):
    """Stage AC Pilot 1: End-to-end data-gap dossier through contract without firewall breach."""
    tracker = LifecycleTracker(entity_id="H_PILOT_GAP")
    assert tracker.current_state == LifecycleState.IDEA

    # 1. Scout proposes dossier with data gap
    dossier = MechanismDossier(
        dossier_id="DOS_PILOT_GAP",
        hypothesis_id="H_PILOT_GAP",
        family="futures_carry",
        claim="NSE single-stock futures basis premium over cash provides carry alpha",
        population="Top 50 single-stock futures",
        expected_horizon_days=20,
        observable_facts=("Futures close vs Cash close",),
        interpretation="Financing and margin constraint compensation",
        causal_chain="Directional leverage demand bids up futures",
        counterparty="Directional levered buyers",
        counterparty_persistence_rationale="Capital and margin constraints limit arbitrage",
        competing_explanations=("Dividend uncertainty", "Cost of carry friction"),
        strongest_baseline="Hold 91-day T-Bill rate",
        unique_predictions=("Premium widens during market bull trends",),
        natural_falsifiers=("Net basis does not exceed financing hurdle",),
        confounds=("Ex-dividend cash flow adjustments",),
        capacity_notes="₹10 lakh book scale",
        min_effect_bps=60.0,
        nearest_hypothesis_ids=(),
        required_observations_absent=("historical_futures_bhavcopy", "lot_sizes"),
        memory_risk_classification="anonymised_unrecognised",
        forward_confirmation_path="Accrue forward carry on listed contracts",
        proposer="scout_market_structure",
        hostile_reviewer="critic_economic",
    )
    assert dossier.has_data_gap
    tracker.transition(LifecycleState.DOSSIER, actor="scout", reason="Proposed futures carry mechanism")
    tracker.transition(LifecycleState.DATA_GAP, actor="router", reason="Identified missing futures bhavcopy")

    # 2. Broker probes source data and synthesizes DataContract
    dates = pd.bdate_range("2021-01-04", periods=40)
    sample_df = pd.DataFrame({"symbol": ["RELIANCE"] * 40, "date": dates, "settle_price": [2500.0] * 40})
    probe = run_source_micro_probe("NSE Stock Futures Bhavcopy", sample_df, calendar_sessions=dates)
    approval = create_approval_card("NSE Stock Futures Bhavcopy", "exchange_terms", 0.0, 2.0, ("futures_carry",), 20)

    data_contract = synthesize_data_contract(
        probe=probe,
        approval=approval,
        fields=[
            SourceFieldDef("date", "datetime64[ns]", "Session date", is_pit=True),
            SourceFieldDef("settle_price", "float64", "Daily settlement price", is_pit=True),
        ],
        source_owner="NSE India",
        storage_path="data/raw/futures/",
        available_at_rule="Available 18:30 IST on date",
        first_tradable_session_rule="First tradable on date + 1 session",
    )
    assert data_contract.contract_hash
    tracker.transition(LifecycleState.SOURCE_PROBED, actor="broker", reason="Micro-probe succeeded")
    tracker.transition(LifecycleState.DATA_CONTRACTED, actor="broker", reason="Data contract synthesized")
    tracker.transition(LifecycleState.DATA_READY, actor="broker", reason="Data contract ready")

    # 3. E0 Structural gate
    panel = pd.DataFrame({
        "symbol": ["S1", "S2"] * 80,
        "date": np.repeat(pd.bdate_range("2021-01-04", periods=80), 2),
        "basis_spread_bps": np.random.default_rng(42).normal(80, 20, 160),
    })
    # Verify no outcome columns in research zone
    assert_zone_frame_access(panel, FirewallZone.RESEARCH)

    gate_rep = evaluate_structural_gate(panel, predictor_col="basis_spread_bps", horizon=10, min_independent_blocks=6)
    assert gate_rep.passed
    tracker.transition(LifecycleState.PREFLIGHTED, actor="gate", reason="E0 structural preflight passed")

    # 4. Freeze ExperimentContract
    exp = ExperimentContract(
        contract_id="EXP_PILOT_GAP",
        dossier_id=dossier.dossier_id,
        dossier_hash=dossier.dossier_hash,
        hypothesis_id=dossier.hypothesis_id,
        family=dossier.family,
        batch_id="BATCH_PILOT_01",
        adapter_type="signal",
        dataset_version="v1",
        split_version="v1",
        partition="train",
        population_definition="Top single-stock futures",
        estimand="Net locked annualised carry return",
        horizons=(20,),
        cost_round_trip_bps=40.0,
        capacity_limit_inr=1000000.0,
        baselines=("tbill_91d", "mechanical_carry"),
        min_magnitude_bps=60.0,
        min_significance_t=2.5,
        min_independent_blocks=8,
        exposure_level_incurred="E2",
        requested_outcome_columns=("fwd_ret_20d_pct",),
        memory_risk_class="anonymised_unrecognised",
        forward_confirmation_path="Accrue forward carry",
        execution_code_or_prompt_hash="fwd_carry_code_hash",
        proposer="planner_agent",
        reviewer="risk_reviewer",
        abort_conditions=(),
    )
    assert exp.contract_hash
    tracker.transition(LifecycleState.EXPERIMENT_CONTRACTED, actor="planner", reason="Experiment contract frozen")
    assert tracker.current_state == LifecycleState.EXPERIMENT_CONTRACTED


def test_stage_ad_batch_execution_and_forward_enrollment(tmp_path, monkeypatch):
    """Stage AD: End-to-end data-ready dossier execution, reveal, and forward enrollment."""
    from src.firewall import exposure as exp_mod
    monkeypatch.setattr(exp_mod, "EXPOSURE_LOG_PATH", tmp_path / "exposure_log.json")
    monkeypatch.setattr(forward_mod, "REGISTRY_PATH", tmp_path / "forward_registry.json")

    tracker = LifecycleTracker(entity_id="H_PILOT_READY")

    # 1. Dossier proposal & Adjudication
    dossier = MechanismDossier(
        dossier_id="DOS_PILOT_READY",
        hypothesis_id="H_PILOT_READY",
        family="opening_momentum",
        claim="Morning 15-min turnover surge in uptrending sectors predicts 5-day continuation",
        population="Liquid NIFTY 500",
        expected_horizon_days=5,
        observable_facts=("Opening 15m turnover", "Sector breadth"),
        interpretation="Institutional sector accumulation",
        causal_chain="Order flow execution across consecutive days",
        counterparty="Intraday scalpers providing morning liquidity",
        counterparty_persistence_rationale="Execution mandates",
        competing_explanations=("Intraday noise", "Mean reverting bounce"),
        strongest_baseline="Mechanical 5d return sort",
        unique_predictions=("Strongest when sector breadth > 70%",),
        natural_falsifiers=("Fails in declining market regime",),
        confounds=(),
        capacity_notes="Liquid names",
        min_effect_bps=50.0,
        nearest_hypothesis_ids=(),
        required_observations_absent=(),
        memory_risk_classification="anonymised_unrecognised",
        forward_confirmation_path="Accrue 60 forward sessions",
        proposer="scout_market_structure",
        hostile_reviewer="critic_economic",
    )
    adj = adjudicate_dossier(dossier)
    assert adj.approved

    tracker.transition(LifecycleState.DOSSIER, actor="scout", reason="Proposed data-ready mechanism")
    tracker.transition(LifecycleState.DATA_READY, actor="broker", reason="All observations available in catalogue")
    tracker.transition(LifecycleState.PREFLIGHTED, actor="gate", reason="E0 preflight passed")

    # 2. Experiment Contract & Batch Freeze
    exp = ExperimentContract(
        contract_id="EXP_PILOT_READY",
        dossier_id=dossier.dossier_id,
        dossier_hash=dossier.dossier_hash,
        hypothesis_id=dossier.hypothesis_id,
        family=dossier.family,
        batch_id="BATCH_PILOT_01",
        adapter_type="signal",
        dataset_version="v1",
        split_version="v1",
        partition="train",
        population_definition="NIFTY 500",
        estimand="5-day forward excess return",
        horizons=(5,),
        cost_round_trip_bps=40.0,
        capacity_limit_inr=1000000.0,
        baselines=("momentum_5d",),
        min_magnitude_bps=50.0,
        min_significance_t=2.5,
        min_independent_blocks=8,
        exposure_level_incurred="E2",
        requested_outcome_columns=("fwd_ret_5d_pct",),
        memory_risk_class="anonymised_unrecognised",
        forward_confirmation_path="Accrue forward sessions",
        execution_code_or_prompt_hash="batch_signal_hash_01",
        proposer="planner_agent",
        reviewer="risk_reviewer",
        abort_conditions=(),
    )
    tracker.transition(LifecycleState.EXPERIMENT_CONTRACTED, actor="planner", reason="Contract frozen")
    tracker.transition(LifecycleState.BATCH_FROZEN, actor="vault", reason="Enrolled in Batch 01")

    # 3. Outcome-blind compute
    tracker.transition(LifecycleState.OUTCOME_BLIND_EXECUTED, actor="runner", reason="Computed signal without labels")

    # 4. Reveal & Outcome Evaluation (records E2 exposure)
    rec = record_exposure(
        hypothesis_id=exp.hypothesis_id,
        family=exp.family,
        batch_id=exp.batch_id,
        level=ExposureLevel.E2_DIRECTIONAL_TRAIN,
        dataset_version=exp.dataset_version,
        partition=exp.partition,
        target_columns=exp.requested_outcome_columns,
        actor="evaluation_vault",
        reason="Evaluating Batch Pilot 01 against train partition",
        path=tmp_path / "exposure_log.json",
    )
    assert rec.exposure_level == ExposureLevel.E2_DIRECTIONAL_TRAIN
    tracker.transition(LifecycleState.REVEALED, actor="vault", reason="Revealed and evaluated", exposure_level="E2")
    tracker.transition(LifecycleState.EVIDENCE, actor="evaluator", reason="Evidence recorded")

    # 5. Enroll in Forward Accrual Lane
    reg = forward_mod.register(
        signal_name=f"signal_{dossier.hypothesis_id}",
        hypothesis_id=dossier.hypothesis_id,
        source="def compute(df):\n    return df.get('open_15m_turnover', 0.0)\n",
        primary_horizon=5,
        dataset_version="v1",
        exploration_id=exp.contract_id,
    )
    assert reg.signal_name == f"signal_{dossier.hypothesis_id}"
    tracker.transition(LifecycleState.FORWARD, actor="forward_lane", reason="Enrolled in forward accrual")

    assert tracker.current_state == LifecycleState.FORWARD
    assert len(tracker.history) == 9
