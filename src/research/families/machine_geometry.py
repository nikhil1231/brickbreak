"""H056 machine-discovered support/resistance role-reversal retests.

This family deliberately contains no outcome loader.  It turns causal intraday
features into a broad, auditable setup population and records the manual priors
that every later learned selector inherits.  Outcomes remain behind the normal
experiment contract and firewall.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from typing import Any

import numpy as np
import pandas as pd

from ...alpha_eval.guards import assert_no_forward_labels


class MachineGeometryError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetestPrior:
    """Outcome-free H056 manual filter and execution prior."""

    min_zone_age_bars: int = 12
    min_break_to_retest_bars: int = 3
    max_break_to_retest_bars: int = 36
    max_bleed_bars: int = 1
    max_cumulative_bleed_atr: float = 0.25
    stop_buffer_atr: float = 0.10
    min_reward_risk: float = 1.50
    min_target_bps: float = 80.0
    # WHY THIS IS BARS AND NOT SESSIONS
    # PLAN.md §9 caps candidates at one per symbol *over the registered holding
    # window*. The holding window here is the stagnation grid — at most 24
    # completed bars, so two hours. The previous `cooldown_sessions = 1` blocked
    # the symbol for the whole of the following session as well, which is two
    # orders of magnitude longer than the overlap it exists to prevent and cost
    # sample for no leakage benefit.
    cooldown_bars: int = 24
    stagnation_bars: tuple[int, ...] = (6, 12, 24)

    def __post_init__(self) -> None:
        if self.min_zone_age_bars < 1 or self.min_break_to_retest_bars < 1:
            raise ValueError("zone and retest delays must be positive")
        if self.max_break_to_retest_bars < self.min_break_to_retest_bars:
            raise ValueError("maximum retest delay precedes its minimum")
        if self.max_bleed_bars < 0 or self.max_cumulative_bleed_atr < 0:
            raise ValueError("bleed tolerances cannot be negative")
        if self.stop_buffer_atr < 0 or self.min_reward_risk <= 0:
            raise ValueError("invalid stop or reward/risk prior")
        if self.min_target_bps <= 0 or self.cooldown_bars < 0:
            raise ValueError("invalid target or cooldown prior")
        if not self.stagnation_bars or min(self.stagnation_bars) < 1:
            raise ValueError("stagnation grid needs positive completed-bar counts")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


REQUIRED_FEATURES = {
    "symbol_asof", "session", "bar_end", "available_at", "close_raw",
    "atr_20", "htf_ema_20", "htf_ema_50", "htf_ema_20_slope_pct",
    "support_zone_kind", "support_zone_lower", "support_zone_upper",
    "support_known_at", "support_age_bars", "support_break_age_bars",
    "support_bleed_bars", "support_cumulative_bleed_atr",
    "resistance_zone_kind", "resistance_zone_lower", "resistance_zone_upper",
    "resistance_known_at", "resistance_age_bars", "resistance_break_age_bars",
    "resistance_bleed_bars", "resistance_cumulative_bleed_atr",
    "bullish_flip_retest", "bearish_flip_retest", "quality_flags",
}


def _candidate_id(symbol: str, decision_at: pd.Timestamp, direction: str) -> str:
    payload = f"H056|{symbol}|{decision_at.isoformat()}|{direction}".encode()
    return "H056_" + hashlib.sha256(payload).hexdigest()[:16].upper()


def generate_retest_population(
    features: pd.DataFrame,
    prior: RetestPrior | None = None,
) -> pd.DataFrame:
    """Return every role-reversal retest with pass/fail reasons.

    Rejected rows are intentionally retained.  A learned selector must see the
    broad population it inherited; dropping awkward, bleeding, targetless or
    source-failed events would manufacture selectivity before learning begins.
    """
    cfg = prior or RetestPrior()
    assert_no_forward_labels(features, context="H056 retest population")
    if missing := REQUIRED_FEATURES - set(features.columns):
        raise MachineGeometryError(f"feature frame missing: {sorted(missing)}")

    work = features.copy()
    work["session"] = pd.to_datetime(work["session"], errors="raise").dt.normalize()
    work["bar_end"] = pd.to_datetime(work["bar_end"], errors="raise")
    work["available_at"] = pd.to_datetime(work["available_at"], errors="raise")
    retest = (
        work["bullish_flip_retest"].fillna(False)
        | work["bearish_flip_retest"].fillna(False))
    work = work.loc[retest].sort_values(
        ["bar_end", "symbol_asof"], kind="stable").copy()
    if work.empty:
        return pd.DataFrame(columns=(
            "candidate_id", "symbol", "session", "decision_at", "direction",
            "eligible", "rejection_reasons"))

    number = lambda name: pd.to_numeric(work[name], errors="coerce")
    close = number("close_raw")
    atr = number("atr_20")
    is_long = work["bullish_flip_retest"].fillna(False)
    work["direction"] = np.where(is_long, "long", "short")

    zone_age = np.where(
        is_long, number("support_age_bars"), number("resistance_age_bars"))
    break_age = np.where(
        is_long, number("support_break_age_bars"),
        number("resistance_break_age_bars"))
    bleed_bars = np.where(
        is_long, number("support_bleed_bars"), number("resistance_bleed_bars"))
    cumulative_bleed = np.where(
        is_long, number("support_cumulative_bleed_atr"),
        number("resistance_cumulative_bleed_atr"))

    stop = np.where(
        is_long,
        number("support_zone_lower") - cfg.stop_buffer_atr * atr,
        number("resistance_zone_upper") + cfg.stop_buffer_atr * atr,
    )
    target = np.where(
        is_long, number("resistance_zone_lower"), number("support_zone_upper"))
    risk = np.where(is_long, close - stop, stop - close)
    reward = np.where(is_long, target - close, close - target)
    with np.errstate(divide="ignore", invalid="ignore"):
        rr = reward / risk
        target_bps = reward / close * 10_000.0

    ema20, ema50, ema_slope = (
        number("htf_ema_20"), number("htf_ema_50"),
        number("htf_ema_20_slope_pct"))
    trend_aligned = np.where(
        is_long,
        (close > ema20) & (ema20 > ema50) & (ema_slope > 0),
        (close < ema20) & (ema20 < ema50) & (ema_slope < 0),
    )
    clean_source = ~work["quality_flags"].fillna("").astype(str).str.contains(
        "invalid_price|invalid_ohlc|negative_volume|corporate_action", regex=True)

    checks = {
        "source_quality": clean_source.to_numpy(bool),
        "zone_mature": np.asarray(zone_age >= cfg.min_zone_age_bars),
        "retest_not_early": np.asarray(break_age >= cfg.min_break_to_retest_bars),
        "retest_not_stale": np.asarray(break_age <= cfg.max_break_to_retest_bars),
        "higher_timeframe_trend": np.asarray(trend_aligned),
        "level_not_bleeding": np.asarray(
            (bleed_bars <= cfg.max_bleed_bars)
            & (cumulative_bleed <= cfg.max_cumulative_bleed_atr)),
        "opposing_target_known": np.asarray(np.isfinite(target) & (reward > 0)),
        "structural_risk_positive": np.asarray(np.isfinite(risk) & (risk > 0)),
        "reward_risk": np.asarray(np.isfinite(rr) & (rr >= cfg.min_reward_risk)),
        "target_room": np.asarray(
            np.isfinite(target_bps) & (target_bps >= cfg.min_target_bps)),
    }
    passed = np.logical_and.reduce(list(checks.values()))

    # The cooldown is measured in decision bars along the symbol's own bar
    # index, so it suppresses genuinely overlapping holds and nothing else.
    bar_index = (
        features[["symbol_asof", "bar_end"]].drop_duplicates()
        .sort_values(["symbol_asof", "bar_end"], kind="stable"))
    bar_index["_position"] = bar_index.groupby("symbol_asof", sort=False).cumcount()
    positions = work.merge(
        bar_index, on=["symbol_asof", "bar_end"], how="left")["_position"].to_numpy()
    cooldown_ok = np.ones(len(work), dtype=bool)
    last_slot: dict[str, float] = {}
    for position, symbol in enumerate(work["symbol_asof"].astype(str)):
        if not passed[position]:
            continue
        slot = positions[position]
        if not np.isfinite(slot):
            continue
        if symbol in last_slot and slot <= last_slot[symbol] + cfg.cooldown_bars:
            cooldown_ok[position] = False
        else:
            last_slot[symbol] = float(slot)
    checks["cooldown"] = cooldown_ok
    passed &= cooldown_ok

    reasons = []
    for position in range(len(work)):
        reasons.append("|".join(
            name for name, values in checks.items() if not bool(values[position])))

    work["candidate_id"] = [
        _candidate_id(str(symbol), pd.Timestamp(decision), str(direction))
        for symbol, decision, direction in zip(
            work["symbol_asof"], work["available_at"], work["direction"])
    ]
    work["symbol"] = work["symbol_asof"].astype(str)
    work["decision_at"] = work["available_at"]
    work["entry_rule"] = "next_available_five_minute_open"
    work["stop_price_at_decision"] = stop
    work["target_price_at_decision"] = target
    work["decision_reward_risk"] = rr
    work["target_room_bps"] = target_bps
    work["zone_age_bars"] = zone_age
    work["break_to_retest_bars"] = break_age
    work["bleed_bars"] = bleed_bars
    work["cumulative_bleed_atr"] = cumulative_bleed
    work["trend_aligned"] = trend_aligned
    work["eligible"] = passed
    work["rejection_reasons"] = reasons
    work["case_status"] = np.where(clean_source, "pending", "source_failure")
    work["generator_score"] = np.where(np.isfinite(rr), rr, -np.inf)
    work["generator_reason"] = (
        "H056 completed role-reversal retest under frozen structural priors")

    columns = [
        "candidate_id", "symbol", "session", "decision_at", "direction",
        "eligible", "rejection_reasons", "case_status", "entry_rule",
        "stop_price_at_decision", "target_price_at_decision",
        "decision_reward_risk", "target_room_bps", "zone_age_bars",
        "break_to_retest_bars", "bleed_bars", "cumulative_bleed_atr",
        "trend_aligned", "generator_score", "generator_reason", "partition",
    ]
    return work[[column for column in columns if column in work.columns]] \
        .reset_index(drop=True)


def exit_policy_grid(prior: RetestPrior | None = None) -> list[dict[str, Any]]:
    """The declared H056 development grid; it is not a retrospective menu."""
    cfg = prior or RetestPrior()
    return [
        {
            "policy_id": f"structural_target_stop_stagnation_{bars}",
            "entry": "next_available_five_minute_open",
            "target": "nearest_opposing_zone_known_at_decision",
            "stop": f"far_edge_plus_{cfg.stop_buffer_atr:.2f}_atr",
            "stagnation_cut_after_completed_bars": bars,
            "stagnation_definition": "maximum_favourable_excursion_below_0.25R",
            "gap_policy": "first_available_price; never assume stop fill",
        }
        for bars in cfg.stagnation_bars
    ]


def development_fold_manifest(
    observations: pd.DataFrame,
    *,
    minimum_train_quarters: int = 8,
) -> pd.DataFrame:
    """Describe leave-one-market-out, expanding walk-forward outer folds.

    This function exposes identities and time only. It neither loads nor
    aggregates outcomes, so creating the manifest does not spend the sample.
    """
    required = {"market", "session"}
    if missing := required - set(observations.columns):
        raise MachineGeometryError(f"fold observations missing: {sorted(missing)}")
    meta = observations[list(required)].drop_duplicates().copy()
    meta["session"] = pd.to_datetime(meta["session"], errors="raise")
    meta["quarter"] = meta["session"].dt.to_period("Q").astype(str)
    quarters = sorted(meta["quarter"].unique())
    records: list[dict[str, Any]] = []
    for held_out in sorted(meta["market"].astype(str).unique()):
        development_markets = sorted(
            set(meta["market"].astype(str).unique()) - {held_out})
        for index in range(minimum_train_quarters, len(quarters)):
            records.append({
                "held_out_market": held_out,
                "development_markets": development_markets,
                "train_quarters": quarters[:index],
                "evaluate_quarter": quarters[index],
                "semantics": "outer market transfer; inner expanding walk-forward",
            })
    return pd.DataFrame(records)


__all__ = [
    "MachineGeometryError", "RetestPrior", "development_fold_manifest",
    "exit_policy_grid", "generate_retest_population",
]
