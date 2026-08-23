"""Tests for Stage X outcome firewall, exposure accounting and preflight gates."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.firewall import (
    ExposureLevel,
    ExposureLimitError,
    FirewallAccessError,
    FirewallZone,
    assert_zone_frame_access,
    check_weekly_exposure_limit,
    evaluate_shape_gate,
    evaluate_structural_gate,
    record_exposure,
)


def test_zone_boundary_blocks_forward_outcomes_in_research():
    df_clean = pd.DataFrame({"symbol": ["A", "B"], "open": [100.0, 200.0]})
    assert_zone_frame_access(df_clean, FirewallZone.RESEARCH)

    df_contaminated = pd.DataFrame({
        "symbol": ["A", "B"],
        "open": [100.0, 200.0],
        "fwd_ret_10d_pct": [1.5, -2.0],
    })
    with pytest.raises(FirewallAccessError, match="forbidden outcome columns"):
        assert_zone_frame_access(df_contaminated, FirewallZone.RESEARCH)

    # Vault may access outcomes
    assert_zone_frame_access(df_contaminated, FirewallZone.EVALUATION_VAULT)


def test_exposure_accounting_and_weekly_ceiling(tmp_path):
    log_file = tmp_path / "exposure_log.json"

    # Record 5 E2 exposures
    for i in range(5):
        record_exposure(
            hypothesis_id=f"H0{i:02d}",
            family="test_fam",
            batch_id="BATCH_1",
            level=ExposureLevel.E2_DIRECTIONAL_TRAIN,
            dataset_version="v1",
            partition="train",
            target_columns=["fwd_ret_10d_pct"],
            actor="agent",
            reason=f"Train reveal {i}",
            path=log_file,
            enforce_limit=True,
        )

    # 6th should fail on ceiling
    with pytest.raises(ExposureLimitError, match="Weekly outcome exposure ceiling reached"):
        record_exposure(
            hypothesis_id="H099",
            family="test_fam",
            batch_id="BATCH_1",
            level=ExposureLevel.E2_DIRECTIONAL_TRAIN,
            dataset_version="v1",
            partition="train",
            target_columns=["fwd_ret_10d_pct"],
            actor="agent",
            reason="Exceeding limit",
            path=log_file,
            enforce_limit=True,
        )


def test_structural_gate_evaluation():
    rng = np.random.default_rng(42)
    n = 200
    dates = pd.bdate_range("2021-01-04", periods=100)
    df = pd.DataFrame({
        "symbol": ["S1", "S2"] * 100,
        "date": np.repeat(dates, 2),
        "predictor_score": rng.normal(0, 1, n),
    })

    rep = evaluate_structural_gate(
        df,
        predictor_col="predictor_score",
        horizon=10,
        min_independent_blocks=5,
        min_cases_per_session=1.5,
    )
    assert rep.passed
    assert rep.estimated_independent_blocks >= 8
    assert rep.missingness_pct == 0.0


def test_structural_gate_fails_on_degenerate_and_underpowered():
    # Degenerate single value
    df_degen = pd.DataFrame({
        "symbol": ["S1"] * 50,
        "date": pd.bdate_range("2021-01-04", periods=50),
        "const_val": [1.0] * 50,
    })
    rep = evaluate_structural_gate(
        df_degen,
        predictor_col="const_val",
        horizon=10,
        min_independent_blocks=8,
    )
    assert not rep.passed
    assert any("degenerate" in r.lower() for r in rep.failure_reasons)


def test_shape_gate_with_permutation_null(tmp_path, monkeypatch):
    from src.firewall import exposure as exp_mod
    monkeypatch.setattr(exp_mod, "EXPOSURE_LOG_PATH", tmp_path / "exposure_log.json")

    rng = np.random.default_rng(123)
    n = 300
    dates = pd.bdate_range("2021-01-04", periods=50)
    # Plant distinct group means
    groups = ["A", "B", "C"] * 100
    outcomes = [10.0 if g == "A" else (-5.0 if g == "B" else 0.0) for g in groups]
    noise = rng.normal(0, 1.0, n)
    df = pd.DataFrame({
        "symbol": [f"S{i%10}" for i in range(n)],
        "date": np.repeat(dates, 6),
        "cluster_group": groups,
        "fwd_ret_10d_pct": np.array(outcomes) + noise,
    })

    rep = evaluate_shape_gate(
        df,
        hypothesis_id="H046",
        family="test_fam",
        group_col="cluster_group",
        outcome_col="fwd_ret_10d_pct",
        min_required_excess_ratio=1.2,
        n_permutations=100,
        record_exposure_log=True,
    )
    assert rep.passed
    assert rep.excess_dispersion_ratio > 1.2
    assert rep.p_value <= 0.05
