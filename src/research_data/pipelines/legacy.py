"""The 1995-2019 panel, adjusted without a corporate-actions feed.

WHY THIS IS A SEPARATE PIPELINE AND NOT A DATE ARGUMENT
`corporate_actions.build` adjusts the modern tape by **reconciling** two
independent sources — NSE's stated ratio and the step actually observed in the
prices — and adjusts only where they agree. That rule is the reason the 2020+
panel can be trusted, and it cannot be applied here: NSE's corporate-actions
feed only reaches back to 2020, so for 1995-2019 there is exactly one source.

Adjusting on an observed step alone is precisely what that module refuses to
do, and for a good reason: an Indian small cap falling 45% in a session looks
identical to a 1:2 split if all you have is the step. So this pipeline does not
pretend to the same standard. It does three things instead:

  ADJUST      only steps that snap tightly to a canonical ratio (1:2, 1:5,
              2:3 ...) *and* are corroborated by volume moving the opposite way
              by roughly the reciprocal, which is what a share count doing
              1/ratio produces and what a price crash does not.

  QUARANTINE  steps that are large and near-but-not-on a canonical ratio. These
              are the genuinely ambiguous ones and they are marked rather than
              guessed, so a caller can drop any window containing one.

  LEAVE       everything else. A 30% fall that resembles no ratio is a 30%
              fall, and turning it into a split would manufacture a return.

WHAT A CALLER MUST KNOW
`adjusted()` returns bars with `ca_confidence` per row. Anything downstream
that computes a forward return should exclude windows containing a quarantined
row; `drop_quarantined_windows` does it. This panel is for **price-and-volume
work only** — the legacy bhavcopy carries no delivery percentage and no VWAP
before 2015, so nothing that depends on those can be extended backwards.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from ...core import config
from ..sources import nse
from . import corporate_actions as CA

logger = logging.getLogger(__name__)

LEGACY_BARS_ADJ = config.NORMALIZED_DIR / "legacy_bars_adj.parquet"

# Ratios an Indian split, bonus or consolidation actually produces. Expressed
# as the multiplier applied to prices *before* the ex-date, matching
# `corporate_actions.Parsed.ratio`.
# Only ratios a normal session cannot imitate. A 1:2 split halves the price;
# nothing an Indian small cap does on an ordinary day halves it. Ratios closer
# to 1.0 live in AMBIGUOUS_RATIOS below and are never adjusted, because a first
# version of this list included 4:5 and 5:4 and "adjusted" 5,722 perfectly
# ordinary 20-25% moves into corporate actions — which does not lose data, it
# manufactures it, and would have been invisible downstream.
STRUCTURAL_RATIOS = np.array([
    1/100, 1/50, 1/20, 1/10, 1/5, 1/4, 1/3, 2/5, 1/2,
    2.0, 5/2, 3.0, 4.0, 5.0, 10.0, 20.0, 50.0, 100.0,
])
# Real corporate actions live here too — a 1:2 bonus is 2/3 and is common — but
# so does every ordinary 25-40% session, and no test on this data separates
# them. Marked, never adjusted.
AMBIGUOUS_RATIOS = np.array([3/5, 2/3, 3/4, 4/5, 5/4, 4/3, 3/2, 5/3])
# How close a step must sit to a canonical ratio to be called one.
SNAP_TOLERANCE = 0.03
MIN_STEP = 0.15


def _nearest(obs: np.ndarray, ratios: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    rel = np.abs(obs[:, None] / ratios[None, :] - 1.0)
    j = np.nanargmin(rel, axis=1)
    return ratios[j], rel[np.arange(len(obs)), j]


def _snap(steps: pd.DataFrame) -> pd.DataFrame:
    """Distance to the nearest structural ratio, and to the nearest ambiguous one."""
    s = steps.copy()
    obs = s["step"].to_numpy(dtype="float64")
    s["snapped_ratio"], s["snap_error"] = _nearest(obs, STRUCTURAL_RATIOS)
    _, s["ambiguous_error"] = _nearest(obs, AMBIGUOUS_RATIOS)
    return s


def _volume_corroborates(bars: pd.DataFrame, steps: pd.DataFrame) -> pd.Series:
    """Did the share count move the way a split implies?

    A 1:2 split halves the price and doubles the number of shares, so volume
    should rise by roughly 1/ratio. A price crash does the opposite of nothing
    in particular — volume usually rises too, but not by the reciprocal — so
    this is a weak test used only to *confirm* an already-tight snap, never to
    find one on its own.
    """
    v = bars[["symbol", "date", "volume"]].drop_duplicates(
        subset=["symbol", "date"]).sort_values(["symbol", "date"])
    v["prior_volume"] = v.groupby("symbol", sort=False)["volume"].shift(1)
    m = steps.merge(v, on=["symbol", "date"], how="left")
    with np.errstate(divide="ignore", invalid="ignore"):
        got = m["volume"] / m["prior_volume"]
        want = 1.0 / m["snapped_ratio"]
    # Generous: within a factor of four of the implied change, and on the
    # correct side of 1. Volume is noisy; the ratio test is doing the work.
    ok = ((got / want).between(0.25, 4.0)
          & (np.sign(np.log(got.where(got > 0))) == np.sign(np.log(want))))
    return ok.fillna(False).to_numpy()


def classify_steps(bars: pd.DataFrame) -> pd.DataFrame:
    """Every large discontinuity, labelled adjust / quarantine / leave."""
    steps = _snap(CA.detect_steps(bars, min_step=MIN_STEP))
    if steps.empty:
        return steps
    steps["volume_ok"] = _volume_corroborates(bars, steps)
    # Only a step that lands ON a ratio is a candidate at all. An earlier
    # version also quarantined a wide band *around* each ratio and caught
    # 70,375 rows against 359 left alone — with twenty ratios spanning the
    # range, almost any move is within 12% of one, so the band said nothing.
    # The discriminator is not proximity to a ratio, it is whether the share
    # count moved to match.
    on_structural = steps["snap_error"] <= SNAP_TOLERANCE
    on_ambiguous = steps["ambiguous_error"] <= SNAP_TOLERANCE
    steps["action"] = np.select(
        [on_structural & steps["volume_ok"], on_structural, on_ambiguous],
        ["adjust", "quarantine", "quarantine"], default="leave")
    return steps


LEGACY_ACTIONS = config.METADATA_DIR / "corporate_actions_legacy.parquet"


def adjusted(bars: pd.DataFrame | None = None, save: bool = False,
             actions: pd.DataFrame | None = None
             ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Back-adjusted legacy bars, reconciled against NSE's own stated ratios.

    The first version of this function adjusted on the tape alone, because the
    corporate-actions feed was assumed to start in 2020. **It does not** — the
    endpoint serves 2003 onward, and 26,222 legacy actions including 416 splits
    and 391 bonuses are now on disk. So this uses the same two-source rule as
    the modern panel: `reconcile` accepts a stated ratio only where the tape
    actually stepped by roughly that much.

    That matters because the tape-only version failed, and failed quietly. It
    adjusted 889 events, left the −48% to −52% band running at nine times the
    modern rate, and flagged fewer than half of those. Adjusting a real 20%
    fall into a corporate action does not lose data, it manufactures it.

    `classify_steps` is retained for the residue: a step with no stated ratio
    is still quarantined rather than trusted, since the feed is thin before
    2005 (70 actions in 2003 against 2,147 in 2019).
    """
    if bars is None:
        bars = nse.load_range(root=nse.LEGACY_BHAV_DIR)
    if "series" in bars.columns:
        bars = bars[bars["series"].isin(["EQ", "BE"])]
        # A symbol can print on two series in one session. EQ is the rolling
        # settlement line and the one every other pipeline means; keeping both
        # would give the symbol two bars a day and silently double its history.
        bars = bars.sort_values(
            ["symbol", "date", "series"],
            key=lambda s: s.map({"EQ": 0, "BE": 1}) if s.name == "series" else s)
        bars = bars.drop_duplicates(subset=["symbol", "date"], keep="first")
    bars = bars.sort_values(["symbol", "date"]).reset_index(drop=True)

    if actions is None:
        if not LEGACY_ACTIONS.exists():
            raise FileNotFoundError(
                f"{LEGACY_ACTIONS.name} missing. Run:\n"
                f"  python -m src.cli family bulk-deals legacy-actions")
        actions = pd.read_parquet(LEGACY_ACTIONS)

    recon = CA.reconcile(bars, actions)
    factors = CA.build_factors(bars, recon)
    out = CA.adjust_bars(bars, factors)

    # Whatever the feed did not explain is marked, never guessed.
    steps = classify_steps(out)
    matched = recon[recon["status"] == "matched"][["symbol", "ex_date"]].rename(
        columns={"ex_date": "date"}) if not recon.empty else pd.DataFrame(
            columns=["symbol", "date"])
    unexplained = steps[steps["action"].isin(("adjust", "quarantine"))][
        ["symbol", "date"]].merge(matched.assign(_m=True), on=["symbol", "date"],
                                  how="left")
    unexplained = unexplained[unexplained["_m"].isna()][["symbol", "date"]]

    out = out.merge(unexplained.assign(_q=True), on=["symbol", "date"], how="left")
    out["ca_confidence"] = np.where(out.pop("_q").notna(), "quarantined", "clean")

    if save:
        config.NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
        out.to_parquet(LEGACY_BARS_ADJ, index=False)
    return out, recon


def drop_quarantined_windows(bars: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Remove rows whose forward window contains an unresolved discontinuity.

    A quarantined step inside the window would show up as a return of tens of
    percent that never happened. Dropping the window is the honest treatment:
    it costs observations and cannot manufacture one.
    """
    d = bars.sort_values(["symbol", "date"]).copy()
    bad = (d["ca_confidence"] == "quarantined").astype(int)
    ahead = bad.groupby(d["symbol"], sort=False).transform(
        lambda s: s.iloc[::-1].rolling(horizon + 1, min_periods=1).sum().iloc[::-1])
    return d[ahead == 0].drop(columns=[]).reset_index(drop=True)


def summarise(steps: pd.DataFrame) -> dict[str, Any]:
    if steps.empty:
        return {"steps": 0}
    v = steps["action"].value_counts()
    return {
        "steps_over_%d%%" % int(MIN_STEP * 100): int(len(steps)),
        "adjusted": int(v.get("adjust", 0)),
        "quarantined": int(v.get("quarantine", 0)),
        "left_alone": int(v.get("leave", 0)),
        "symbols_adjusted": int(steps.loc[steps["action"] == "adjust", "symbol"].nunique()),
    }
