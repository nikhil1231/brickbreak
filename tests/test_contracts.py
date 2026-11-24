"""Tests for Stage W contracts and lifecycle state machine."""
from __future__ import annotations

from dataclasses import replace

import pytest

from src.contracts import (
    DataContract,
    DossierDissent,
    ExperimentContract,
    IllegalLifecycleTransitionError,
    LifecycleState,
    LifecycleTracker,
    MechanismDossier,
    SourceFieldDef,
)
from src.contracts.dossier import DossierValidationError
from src.contracts.data_contract import DataContractValidationError
from src.contracts.experiment_contract import ExperimentContractValidationError


def _sample_dossier():
    return MechanismDossier(
        dossier_id="DOS_001",
        hypothesis_id="H046",
        family="opening_window",
        claim="Opening volume surge predicts 10-day continuation",
        population="NIFTY 500 equities with median turnover > 1cr",
        expected_horizon_days=10,
        observable_facts=("Opening 15-min volume relative to 20d median",),
        interpretation="Institutional accumulation",
        causal_chain="Order execution over multiple hours/days",
        counterparty="Impatient morning liquidity demand",
        counterparty_persistence_rationale="Execution mandates and hedging deadlines",
        competing_explanations=(
            "Random morning noise",
            "Mean-reverting inventory imbalances",
        ),
        strongest_baseline="Mechanical 20d momentum sort",
        unique_predictions=("Strongest on morning gap-up sessions",),
        natural_falsifiers=("Fails on high-volatility regime sessions",),
        confounds=("Earnings announcement dates",),
        capacity_notes="Liquid top 500 only",
        min_effect_bps=45.0,
        nearest_hypothesis_ids=("H001", "H033"),
        required_observations_absent=(),
        memory_risk_classification="anonymised_unrecognised",
        forward_confirmation_path="Accrue 60 clean forward sessions",
        proposer="scout_structure",
        hostile_reviewer="critic_economic",
        dissents=(
            DossierDissent(
                reviewer_role="power_reviewer",
                objection="Turnover floor limits independent blocks to 12",
                severity="material",
            ),
        ),
    )


def test_mechanism_dossier_validation_and_hashing():
    dos = _sample_dossier()
    assert dos.dossier_hash
    assert not dos.has_data_gap
    d_dict = dos.to_dict()
    assert d_dict["dossier_hash"] == dos.dossier_hash

    restored = MechanismDossier.from_dict(d_dict)
    assert restored.dossier_hash == dos.dossier_hash
    assert len(restored.dissents) == 1
    assert restored.dissents[0].reviewer_role == "power_reviewer"
    assert replace(dos, population="A different population").dossier_hash != dos.dossier_hash
    tampered = dict(d_dict)
    tampered["population"] = "A silently altered population"
    with pytest.raises(DossierValidationError, match="hash mismatch"):
        MechanismDossier.from_dict(tampered)


def test_optional_mechanism_evidence_does_not_block_bootstrap():
    dos = replace(
        _sample_dossier(),
        optional_observations_absent=("institutional ownership", "full depth book"),
        estimated_engineering_days=1.0,
        estimated_cash_cost_usd=0.0,
    )
    assert dos.bootstrap_ready
    assert not dos.has_data_gap
    assert dos.to_dict()["optional_observations_absent"]


def test_dossier_requires_competing_explanations_and_distinct_reviewer():
    with pytest.raises(DossierValidationError, match="competing explanations"):
        MechanismDossier(
            dossier_id="DOS_BAD",
            hypothesis_id="H001",
            family="fam",
            claim="claim",
            population="pop",
            expected_horizon_days=5,
            observable_facts=("fact",),
            interpretation="interp",
            causal_chain="chain",
            counterparty="cp",
            counterparty_persistence_rationale="rat",
            competing_explanations=("Only one",),
            strongest_baseline="base",
            unique_predictions=("pred",),
            natural_falsifiers=("falsifier",),
            confounds=(),
            capacity_notes="cap",
            min_effect_bps=20.0,
            nearest_hypothesis_ids=(),
            required_observations_absent=(),
            memory_risk_classification="anon",
            forward_confirmation_path="fwd",
            proposer="scout",
            hostile_reviewer="critic",
        )

    with pytest.raises(DossierValidationError, match="separate entities"):
        MechanismDossier(
            dossier_id="DOS_BAD2",
            hypothesis_id="H001",
            family="fam",
            claim="claim",
            population="pop",
            expected_horizon_days=5,
            observable_facts=("fact",),
            interpretation="interp",
            causal_chain="chain",
            counterparty="cp",
            counterparty_persistence_rationale="rat",
            competing_explanations=("Comp 1", "Comp 2"),
            strongest_baseline="base",
            unique_predictions=("pred",),
            natural_falsifiers=("falsifier",),
            confounds=(),
            capacity_notes="cap",
            min_effect_bps=20.0,
            nearest_hypothesis_ids=(),
            required_observations_absent=(),
            memory_risk_classification="anon",
            forward_confirmation_path="fwd",
            proposer="agent_x",
            hostile_reviewer="agent_x",
        )


def test_data_contract_validation_and_hashing():
    dc = DataContract(
        contract_id="DC_BULK_01",
        source_name="NSE Historical Bulk Deals",
        source_owner="NSE India",
        licence_type="exchange_terms",
        cash_cost_usd=0.0,
        rate_limits="5 req/s",
        raw_fields=(
            SourceFieldDef("deal_date", "datetime64[ns]", "Session date", is_pit=True),
            SourceFieldDef("quantity", "int64", "Shares traded", is_pit=True),
        ),
        timestamp_tz="Asia/Kolkata",
        publication_latency_hours=4.5,
        available_at_rule="Available after 18:30 IST on deal_date",
        first_tradable_session_rule="First tradable on deal_date + 1 session",
        coverage_start="2004-01-04",
        coverage_end="present",
        universe_depth="All listed equities",
        survivorship_policy="Point in time from raw daily disclosures",
        expected_join_rate_pct=98.5,
        pagination_and_caps_notes="CSV endpoint is complete; JSON endpoint caps at 70 rows",
        entity_resolution_policy="Mapped via symbolchange.csv",
        unlocked_families=("bulk_deals", "institutional_flow"),
        storage_path="data/raw/bulk_deals/",
        maintenance_owner="Data Broker",
    )
    assert dc.contract_hash
    d = dc.to_dict()
    assert d["contract_hash"] == dc.contract_hash
    restored = DataContract.from_dict(d)
    assert restored.contract_hash == dc.contract_hash
    assert replace(dc, publication_latency_hours=24.0).contract_hash != dc.contract_hash
    tampered = dict(d)
    tampered["publication_latency_hours"] = 24.0
    with pytest.raises(DataContractValidationError, match="hash mismatch"):
        DataContract.from_dict(tampered)


def test_experiment_contract_requires_dual_bars_and_separate_roles():
    dos = _sample_dossier()
    exp = ExperimentContract(
        contract_id="EXP_001",
        dossier_id=dos.dossier_id,
        dossier_hash=dos.dossier_hash,
        hypothesis_id="H046",
        family="opening_window",
        batch_id="BATCH_2026_01",
        adapter_type="signal",
        dataset_version="v1",
        split_version="v1",
        partition="train",
        population_definition="NIFTY 500",
        estimand="10-day forward excess return over market",
        horizons=(5, 10, 20),
        cost_round_trip_bps=40.0,
        capacity_limit_inr=10000000.0,
        baselines=("momentum_20d", "sector_relative"),
        min_magnitude_bps=45.0,
        min_significance_t=2.5,
        min_independent_blocks=8,
        exposure_level_incurred="E2",
        requested_outcome_columns=("fwd_ret_10d_pct",),
        memory_risk_class="anonymised_unrecognised",
        forward_confirmation_path="Accrue 60 forward sessions",
        execution_code_or_prompt_hash="abc123hash",
        proposer="planner_agent",
        reviewer="risk_officer",
        abort_conditions=("effective_n < 10",),
    )
    assert exp.contract_hash
    exp_dict = exp.to_dict()
    restored = ExperimentContract.from_dict(exp_dict)
    assert restored.contract_hash == exp.contract_hash
    assert replace(exp, cost_round_trip_bps=75.0).contract_hash != exp.contract_hash
    tampered = dict(exp_dict)
    tampered["cost_round_trip_bps"] = 75.0
    with pytest.raises(ExperimentContractValidationError, match="hash mismatch"):
        ExperimentContract.from_dict(tampered)

    # Fails if proposer == reviewer
    with pytest.raises(ExperimentContractValidationError, match="separate entities"):
        ExperimentContract(
            contract_id="EXP_BAD",
            dossier_id=dos.dossier_id,
            dossier_hash=dos.dossier_hash,
            hypothesis_id="H046",
            family="opening_window",
            batch_id="BATCH_2026_01",
            adapter_type="signal",
            dataset_version="v1",
            split_version="v1",
            partition="train",
            population_definition="NIFTY 500",
            estimand="estimand",
            horizons=(10,),
            cost_round_trip_bps=40.0,
            capacity_limit_inr=1000000.0,
            baselines=("base",),
            min_magnitude_bps=40.0,
            min_significance_t=2.0,
            min_independent_blocks=8,
            exposure_level_incurred="E2",
            requested_outcome_columns=("fwd_ret_10d_pct",),
            memory_risk_class="anon",
            forward_confirmation_path="fwd",
            execution_code_or_prompt_hash="hash",
            proposer="same_agent",
            reviewer="same_agent",
            abort_conditions=(),
        )


def test_lifecycle_state_machine_and_illegal_transitions():
    tracker = LifecycleTracker(entity_id="H046")
    assert tracker.current_state == LifecycleState.IDEA

    # Valid step: IDEA -> DOSSIER
    tracker.transition(LifecycleState.DOSSIER, actor="scout", reason="Drafted mechanism dossier")
    assert tracker.current_state == LifecycleState.DOSSIER

    # Valid step: DOSSIER -> DATA_READY
    tracker.transition(LifecycleState.DATA_READY, actor="broker", reason="Data already in catalogue")
    assert tracker.current_state == LifecycleState.DATA_READY

    # Valid step: DATA_READY -> PREFLIGHTED
    tracker.transition(LifecycleState.PREFLIGHTED, actor="gate", reason="E0 structural gate passed")
    assert tracker.current_state == LifecycleState.PREFLIGHTED

    # Illegal step: cannot jump straight to REVEALED or FORWARD
    with pytest.raises(IllegalLifecycleTransitionError, match="Cannot transition from PREFLIGHTED to REVEALED"):
        tracker.transition(LifecycleState.REVEALED, actor="bad_runner", reason="Attempted bypass")

    # Valid continuation
    tracker.transition(LifecycleState.EXPERIMENT_CONTRACTED, actor="planner", reason="Frozen experiment contract")
    tracker.transition(LifecycleState.BATCH_FROZEN, actor="vault", reason="Frozen in Batch B1")
    tracker.transition(LifecycleState.OUTCOME_BLIND_EXECUTED, actor="runner", reason="Signal computed outcome-blind")
    tracker.transition(LifecycleState.REVEALED, actor="vault", reason="Outcomes joined", exposure_level="E2")
    tracker.transition(LifecycleState.EVIDENCE, actor="evaluator", reason="Report evaluated")
    tracker.transition(LifecycleState.FORWARD, actor="forward_lane", reason="Enrolled in forward accrual")
    assert tracker.current_state == LifecycleState.FORWARD
    assert len(tracker.history) == 9


def test_lifecycle_audit_record_cannot_omit_actor_or_reason():
    tracker = LifecycleTracker(entity_id="H046")
    with pytest.raises(ValueError, match="actor"):
        tracker.transition(LifecycleState.DOSSIER, actor="", reason="drafted")
    with pytest.raises(ValueError, match="reason"):
        tracker.transition(LifecycleState.DOSSIER, actor="scout", reason="")
    with pytest.raises(ValueError, match="exposure_level"):
        tracker.transition(
            LifecycleState.DOSSIER, actor="scout", reason="drafted",
            exposure_level="FREE")
