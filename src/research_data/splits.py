"""Deterministic, versioned, purged dataset splits.

WHY THIS REPLACES THE OLD HOLDOUT
The previous arrangement was backwards. The holdout (2020-04 -> 2023-08) sat
*before* the exploration window (2023-08 -> present), so every rule was
developed on recent data and tested on older data. That inverts the direction
of any real deployment, and it hands each side a different regime: the holdout
window's market compounded at 41.78% at a Sharpe of 2.25, which is why H026
could beat the same-day pool at t=4.98 and still fail the portfolio clause of
its own frozen bar. One window, one regime, one shot, and no way to tell a
regime effect from a decay effect.

THE DESIGN
Whole calendar quarters are assigned to train / validation / test by a seeded
draw. Chronological order is preserved *within* each quarter; only the
assignment of quarters is randomised. That buys regime diversity in every
partition without the leakage of shuffling individual symbol-days.

Three properties matter more than the mechanism:

- **Purging.** A forward return computed on the last day of a quarter reaches
  into the next one. Where those quarters belong to different sets, the
  overlapping rows are dropped, and they are always dropped from the
  lower-priority set (test > validation > train). Evaluation sample is the
  scarce resource; training rows are not. It is not free: on this panel the
  purge costs about a fifth of train and nothing at all of test.
- **The test set is drawn once.** Re-shuffling to get a second opinion reads
  test twice, which is exactly how 2020-2023 was spent. Train and validation
  may be re-drawn within the remainder under a sub-seed; test may not.
- **`forward` is not shuffled.** A shuffled test set is interleaved with
  training in time, so alpha decay is invisible to it. `forward` is every
  session after the dataset version was created, strictly chronological,
  growing by one session a day. The two answer different questions and are
  never averaged.

WHY THE DRAW IS CONSTRAINED AND NOT MERELY SEEDED
The panel holds 27 quarters. A blind shuffle over 27 blocks can put all of 2020
in test, or hand test a set that never sees a drawdown, and with ~5 test
quarters there is no averaging that away afterwards without reading test again.
So the draw is seeded *and* constrained: seeds are tried in order until an
assignment satisfies stated balance constraints, and the accepted seed, the
constraints and the resulting assignment all go in the manifest. Reproducible,
and honest about not being uniformly random.

ON USING REALISED MARKET DATA TO LABEL QUARTERS
The regime labels that constrain the draw are computed from full-quarter
realised data. That is not a lookahead: a split is a fixed partition of history
decided once, not a decision taken at a point in time, and no experiment ever
sees the label as a feature. It does mean the split cannot be reconstructed
"as of" some past date, which is a property worth knowing rather than a defect.

PRIOR EXPOSURE
2020-2023 has been read twice — against the opening-window family (H033, FAIL)
and against the frozen resilience spec (H037). Rather than discard 55% of the
history, exposure is recorded per quarter with the family and the role it was
read in. The ledger blocks a hypothesis from scoring on quarters its own
lineage has already consumed; an unrelated signal may use them with the caveat
attached. **When lineage is ambiguous, block.**
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from ..core import config

SPLIT_DIR = config.METADATA_DIR
BARS_PATH = config.NORMALIZED_DIR / "daily_bars_adj.parquet"
MARKET_PATH = config.NORMALIZED_DIR / "market_regime.parquet"

SETS = ("train", "validation", "test")

# Higher wins a boundary: purged rows come out of the lower-priority side.
# `forward` outranks everything — it is the only unqualified confirmatory
# evidence this project has left, and the panel gives way to it.
PRIORITY = {"train": 1, "validation": 2, "test": 3, "forward": 4}


class SplitError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# prior exposure — what has already been spent, and by whom
# ---------------------------------------------------------------------------

# Recorded as (first_session, last_session, family, role). `role` is what the
# window was read *as*, and it decides how badly it is spent: a confirmatory
# read burns a window for that family permanently, while an exploratory read
# means any test result there is contaminated by hypothesis generation.
#
# Dates are the spans actually read, not the spans available. See FINDINGS.md
# Phase 3 (H033) and Phase 4 (H037).
PRIOR_EXPOSURE: tuple[tuple[str, str, str, str], ...] = (
    ("2020-12-29", "2023-08-18", "opening_window", "confirmatory"),   # H033
    # H033 froze and ran *H024 and H026* against the holdout, and both are
    # filed under `discovery`. Recording only `opening_window` left the two
    # rules that actually spent 2020-2023 as the two the ledger would let
    # back in — the gate reported ALLOWED for a confirmatory H024 read.
    ("2020-12-29", "2023-08-18", "discovery", "confirmatory"),        # H033
    ("2020-04-27", "2023-08-18", "resilience", "confirmatory"),       # H037
    ("2023-08-21", "2026-08-18", "opening_window", "exploratory"),
    ("2023-08-21", "2026-08-18", "resilience", "exploratory"),
    ("2023-08-21", "2026-08-18", "discovery", "exploratory"),
    ("2023-08-21", "2026-08-18", "phase2_discovery", "exploratory"),
)


def exposure_version() -> str:
    """Fingerprint of the exposure table.

    Exposure is *knowledge about what was read*, and knowledge gets corrected —
    unlike the split assignment, which is a commitment. So the frozen manifest
    keeps a readable snapshot of it, but the ledger reseeds from this table
    whenever the fingerprint changes, and the table is the authority.
    """
    raw = json.dumps(PRIOR_EXPOSURE, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()[:12]


@dataclass(frozen=True)
class SplitConfig:
    """Everything the draw depends on. Changing any of it is a new version.

    `max_horizon` is the longest forward return this version supports, and it
    sets the purge length. An experiment asking for a longer horizon than the
    version was purged for is an error, not a warning — its labels would cross
    a boundary the purge did not cover.

    `embargo` is deliberately shorter than the purge, and the asymmetry is not
    laziness. The two block different things:

    - the **purge** removes rows whose *labels* land in a neighbouring set.
      That is first-order leakage — the outcome itself — and it gets the full
      `max_horizon`.
    - the **embargo** removes rows whose *features* overlap a neighbour's
      label window. Second-order: a lookback aggregate that partly spans the
      neighbour's outcome path, not the outcome.

    Measured on this panel at `max_horizon=20`: a full-horizon embargo costs
    33.0% of train sessions against 20.6% at five, for the second-order case
    only. Five sessions (one week) is the default. A version that wants the
    paranoid setting can pass `embargo=max_horizon` and pay for it knowingly.

    `max_consecutive` is 3 rather than 2, and this was measured too. Forcing
    alternation *raises* the purge cost, because a more alternating assignment
    has more cross-set boundaries: 21 boundaries and 26.4% of train lost at
    two, against 17 and 20.6% at three. Three consecutive quarters is nine
    contiguous months, which is nowhere near rebuilding a chronological split.
    """
    version: str = "v1"
    seed: int = 0
    ratios: tuple[float, float, float] = (0.6, 0.2, 0.2)
    max_horizon: int = 20
    embargo: int | None = None      # None -> max_horizon // 4, see docstring
    forward_start: str = "2026-08-19"
    min_years_per_set: int = 3
    max_consecutive: int = 3
    vol_quantile: float = 0.67      # a quarter above this is "high volatility"
    trend_quantile: float = 0.67    # ... and above this is "trending"
    max_seed_attempts: int = 10_000

    @property
    def embargo_sessions(self) -> int:
        if self.embargo is not None:
            return self.embargo
        return max(1, self.max_horizon // 4)


# ---------------------------------------------------------------------------
# the session calendar and its quarters
# ---------------------------------------------------------------------------

def sessions(path: Path | None = None) -> pd.DatetimeIndex:
    """Every session in the panel, sorted and unique.

    The calendar is read from the bars rather than generated, because NSE
    trades on some weekends (budget Saturdays, Muhurat, DR drills) and skips
    some weekdays. A generated calendar would be wrong in both directions.
    """
    p = path or BARS_PATH
    if not p.exists():
        raise SplitError(f"panel not found: {p}")
    d = pd.read_parquet(p, columns=["date"])
    s = pd.to_datetime(d["date"]).drop_duplicates().sort_values()
    return pd.DatetimeIndex(s.to_numpy())


def calendar_hash(sess: pd.DatetimeIndex) -> str:
    """Fingerprint of the calendar the split was drawn against.

    The split depends on the *calendar*, not on the price values, so this is
    the honest dependency to hash — and it costs milliseconds rather than
    hashing 234MB of bars. A recovered missing session changes it, which is
    correct: that is a different partition of history.
    """
    raw = ",".join(sess.strftime("%Y-%m-%d")).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def quarters(sess: pd.DatetimeIndex) -> pd.DataFrame:
    """One row per calendar quarter present in the calendar."""
    q = pd.PeriodIndex(sess, freq="Q")
    df = pd.DataFrame({"date": sess, "quarter": q})
    g = df.groupby("quarter", observed=True)["date"]
    out = pd.DataFrame({
        "start": g.min(), "end": g.max(), "n_sessions": g.count(),
    }).reset_index()
    out["quarter"] = out["quarter"].astype(str)
    return out.sort_values("start").reset_index(drop=True)


def quarter_regimes(qs: pd.DataFrame, cfg: SplitConfig,
                    market: pd.DataFrame | None = None) -> pd.DataFrame:
    """Label each quarter by realised volatility and trendiness.

    Reuses `context.market_regime`'s equal-weighted market series rather than
    inventing a second definition of "the market". `mkt_trend_eff` is the net
    move over the summed absolute moves: an index that rose 6% in twenty small
    steps scores near 1, one that rose 6% via two round trips scores near 0.

    Labels are terciles of this panel, not absolute thresholds. They exist to
    stop the draw producing a degenerate assignment, not to describe the world.
    """
    if market is None:
        if not MARKET_PATH.exists():
            raise SplitError(
                f"{MARKET_PATH} not found — run `python -m src.cli context` first")
        market = pd.read_parquet(MARKET_PATH)
    m = market.copy()
    m["date"] = pd.to_datetime(m["date"])
    m["quarter"] = pd.PeriodIndex(m["date"], freq="Q").astype(str)

    agg = m.groupby("quarter").agg(
        vol=("mkt_vol_20d", "mean"),
        trend_eff=("mkt_trend_eff", "mean"),
        ret=("mkt_ret_20d", "mean"),
    ).reset_index()

    out = qs.merge(agg, on="quarter", how="left")
    if out[["vol", "trend_eff"]].isna().all().any():
        raise SplitError("market series does not cover the panel's quarters")
    vcut = out["vol"].quantile(cfg.vol_quantile)
    tcut = out["trend_eff"].quantile(cfg.trend_quantile)
    out["high_vol"] = out["vol"] >= vcut
    out["trending"] = out["trend_eff"] >= tcut
    out["year"] = out["start"].dt.year
    return out


# ---------------------------------------------------------------------------
# the draw
# ---------------------------------------------------------------------------

def _target_counts(n: int, ratios: tuple[float, float, float]) -> dict[str, int]:
    """Largest-remainder allocation, so the counts always sum to `n`."""
    if abs(sum(ratios) - 1.0) > 1e-9:
        raise SplitError(f"ratios must sum to 1, got {ratios}")
    raw = {s: n * r for s, r in zip(SETS, ratios)}
    base = {s: int(np.floor(v)) for s, v in raw.items()}
    left = n - sum(base.values())
    for s in sorted(SETS, key=lambda s: raw[s] - base[s], reverse=True)[:left]:
        base[s] += 1
    if min(base.values()) < 1:
        raise SplitError(f"ratios {ratios} leave an empty set over {n} quarters")
    return base


def _assign(order: np.ndarray, counts: dict[str, int]) -> list[str]:
    """Map a permutation of quarter indices onto set labels."""
    out = [""] * len(order)
    i = 0
    for s in SETS:
        for j in order[i:i + counts[s]]:
            out[j] = s
        i += counts[s]
    return out


def _check(labels: list[str], meta: pd.DataFrame,
           cfg: SplitConfig) -> list[str]:
    """Return the list of violated constraints — empty means the draw stands."""
    bad: list[str] = []
    lab = pd.Series(labels, index=meta.index)

    for s in SETS:
        sub = meta[lab == s]
        if sub["year"].nunique() < cfg.min_years_per_set:
            bad.append(f"{s}: spans {sub['year'].nunique()} calendar years")
        if not sub["high_vol"].any():
            bad.append(f"{s}: no high-volatility quarter")
        if not sub["trending"].any():
            bad.append(f"{s}: no trending quarter")

    run, prev = 0, None
    for s in labels:                       # meta is in chronological order
        run = run + 1 if s == prev else 1
        prev = s
        if run > cfg.max_consecutive:
            bad.append(f"{s}: {run} consecutive quarters")
            break
    return bad


def draw(meta: pd.DataFrame, cfg: SplitConfig) -> tuple[list[str], int, int]:
    """Seeded, constrained assignment of quarters to sets.

    Seeds are tried in order from `cfg.seed`. The first that satisfies every
    constraint is accepted and recorded; the search is deterministic, so the
    manifest's `seed_accepted` reproduces the assignment exactly.
    """
    counts = _target_counts(len(meta), cfg.ratios)
    for k in range(cfg.max_seed_attempts):
        seed = cfg.seed + k
        order = np.random.default_rng(seed).permutation(len(meta))
        labels = _assign(order, counts)
        if not _check(labels, meta, cfg):
            return labels, seed, k + 1
    raise SplitError(
        f"no assignment satisfied the constraints in {cfg.max_seed_attempts} "
        "attempts — loosen SplitConfig rather than dropping a constraint "
        "silently")


# ---------------------------------------------------------------------------
# purging
# ---------------------------------------------------------------------------

def purge(sess: pd.DatetimeIndex, qmeta: pd.DataFrame,
          cfg: SplitConfig) -> tuple[pd.Series, pd.Series, list[dict]]:
    """Drop the sessions whose labels or features cross a cross-set boundary.

    Returns the per-session labels before purging, the labels after (`""` for
    a purged session), and a record of every boundary — so the manifest can
    state the cost instead of leaving it to be discovered later.

    Direction matters. At a boundary between quarters A (earlier) and B:

    - A's last `max_horizon` sessions carry labels that land inside B;
    - B's first `embargo` sessions carry features overlapping A's labels.

    Both are dropped, and both come out of whichever side has lower priority.

    The panel's own tail is purged the same way, because `forward` begins where
    the panel ends. A train row dated five sessions before the cutoff carries a
    +20d label determined by sessions inside the forward lane — training on it
    and then evaluating on forward is the same leak as any other boundary, and
    it is the one boundary that exists in every split regardless of the draw.
    Those rows have truncated labels anyway until the data arrives.
    """
    lab = pd.Series("", index=sess, dtype=object)
    for _, q in qmeta.iterrows():
        lab.loc[(sess >= q["start"]) & (sess <= q["end"])] = q["set"]

    boundaries: list[dict] = []
    drop = pd.Series(False, index=sess)
    for a, b in zip(qmeta.itertuples(), qmeta.iloc[1:].itertuples()):
        if a.set == b.set:
            continue
        lower = a if PRIORITY[a.set] <= PRIORITY[b.set] else b
        if lower is a:
            n = cfg.max_horizon
            span = sess[(sess >= a.start) & (sess <= a.end)][-n:]
            side = "label overlap into the next quarter"
        else:
            n = cfg.embargo_sessions
            span = sess[(sess >= b.start) & (sess <= b.end)][:n]
            side = "feature overlap with the previous quarter's labels"
        drop.loc[span] = True
        boundaries.append({
            "between": f"{a.quarter}({a.set}) | {b.quarter}({b.set})",
            "purged_from": lower.set, "purged_quarter": lower.quarter,
            "n_sessions": int(len(span)), "reason": side,
        })

    tail = sess[-cfg.max_horizon:] if cfg.max_horizon else sess[:0]
    if len(tail):
        drop.loc[tail] = True
        boundaries.append({
            "between": f"{qmeta.iloc[-1]['quarter']}"
                       f"({qmeta.iloc[-1]['set']}) | forward",
            "purged_from": str(qmeta.iloc[-1]["set"]),
            "purged_quarter": str(qmeta.iloc[-1]["quarter"]),
            "n_sessions": int(len(tail)),
            "reason": "label overlap into the forward lane",
        })

    purged = lab.copy()
    purged[drop.to_numpy()] = ""
    return lab, purged, boundaries


# ---------------------------------------------------------------------------
# prior exposure
# ---------------------------------------------------------------------------

def exposure_for(start: pd.Timestamp, end: pd.Timestamp) -> list[dict]:
    """Which families have already read any part of this span, and how."""
    out = []
    for lo, hi, family, role in PRIOR_EXPOSURE:
        if pd.Timestamp(lo) <= end and pd.Timestamp(hi) >= start:
            out.append({"family": family, "role": role})
    return out


# ---------------------------------------------------------------------------
# build / save / load
# ---------------------------------------------------------------------------

def build(cfg: SplitConfig | None = None, sess: pd.DatetimeIndex | None = None,
          market: pd.DataFrame | None = None) -> dict:
    """Draw a split and return its manifest. Pure — writes nothing."""
    cfg = cfg or SplitConfig()
    sess = sessions() if sess is None else sess
    fwd = pd.Timestamp(cfg.forward_start)

    panel = sess[sess < fwd]
    forward = sess[sess >= fwd]
    if len(panel) == 0:
        raise SplitError(f"no sessions before forward_start={cfg.forward_start}")

    qs = quarters(panel)
    meta = quarter_regimes(qs, cfg, market=market)
    labels, seed_accepted, attempts = draw(meta, cfg)
    meta = meta.assign(set=labels)

    raw, part, boundaries = purge(panel, meta, cfg)

    counts = {s: int((part == s).sum()) for s in SETS}
    before = {s: int((raw == s).sum()) for s in SETS}
    q_counts = {s: int((meta["set"] == s).sum()) for s in SETS}

    # NOTE: `prior_exposure` below is a snapshot for readability. The ledger
    # reseeds from `PRIOR_EXPOSURE` live (see `exposure_version`), so a
    # correction to what was read does not require redrawing a frozen split.
    qrows = []
    for q in meta.itertuples():
        qrows.append({
            "quarter": q.quarter, "start": str(q.start.date()),
            "end": str(q.end.date()), "n_sessions": int(q.n_sessions),
            "set": q.set, "high_vol": bool(q.high_vol),
            "trending": bool(q.trending),
            "mkt_vol_20d": round(float(q.vol), 3),
            "mkt_trend_eff": round(float(q.trend_eff), 4),
            "prior_exposure": exposure_for(q.start, q.end),
        })

    manifest = {
        "version": cfg.version,
        "created": datetime.now().strftime("%Y-%m-%d"),
        "config": asdict(cfg),
        "seed_accepted": seed_accepted,
        "seed_attempts": attempts,
        "panel": {
            "first_session": str(panel[0].date()),
            "last_session": str(panel[-1].date()),
            "n_sessions": int(len(panel)),
            "n_quarters": int(len(meta)),
            "calendar_hash": calendar_hash(sess),
        },
        "forward": {
            "start": cfg.forward_start,
            "n_sessions": int(len(forward)),
            "note": "grows by one session a day; empty is the normal state at "
                    "version creation",
        },
        "quarter_counts": q_counts,
        "session_counts": counts,
        "purge": {
            "max_horizon": cfg.max_horizon,
            "embargo": cfg.embargo_sessions,
            "n_boundaries": len(boundaries),
            "sessions_dropped": int((part == "").sum()),
            "dropped_pct_of_panel": round(
                100 * float((part == "").sum()) / len(panel), 2),
            "dropped_by_set": {
                s: int(before[s] - counts[s]) for s in SETS},
            "boundaries": boundaries,
        },
        "quarters": qrows,
    }
    manifest["hash"] = _hash(manifest)
    return manifest


def _hash(manifest: dict) -> str:
    payload = {k: v for k, v in manifest.items() if k != "hash"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def path_for(version: str) -> Path:
    return SPLIT_DIR / f"split_{version}_frozen.json"


def save(manifest: dict, overwrite: bool = False) -> Path:
    """Freeze a split. Refuses to overwrite: a split is a commitment.

    Re-drawing test is what spends it. If a genuinely new partition is wanted,
    it gets a new version and a stated reason, so the two can never be confused
    in a manifest after the fact.
    """
    p = path_for(manifest["version"])
    if p.exists() and not overwrite:
        raise SplitError(
            f"{p.name} already exists. A split is frozen once — create a new "
            "version rather than redrawing this one (the refactor plan §5.2).")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest, indent=2) + "\n")
    return p


def load(version: str = "v1") -> dict:
    p = path_for(version)
    if not p.exists():
        raise SplitError(f"no frozen split at {p}")
    m = json.loads(p.read_text())
    if m.get("hash") != _hash(m):
        raise SplitError(
            f"{p.name} has been edited since it was frozen (hash mismatch). "
            "A split manifest is evidence; restore it from git rather than "
            "patching it.")
    return m


# ---------------------------------------------------------------------------
# using a split
# ---------------------------------------------------------------------------

def session_partitions(manifest: dict,
                       sess: pd.DatetimeIndex | None = None) -> pd.Series:
    """Session -> partition (`train`/`validation`/`test`/`forward`/`""`).

    `""` means purged, and purged is not a partition: it is a row no
    experiment may use for anything.
    """
    cfg = SplitConfig(**manifest["config"])
    sess = sessions() if sess is None else sess
    fwd = pd.Timestamp(cfg.forward_start)
    panel = sess[sess < fwd]

    meta = pd.DataFrame(manifest["quarters"])
    meta["start"] = pd.to_datetime(meta["start"])
    meta["end"] = pd.to_datetime(meta["end"])
    _, part, _ = purge(panel, meta, cfg)

    out = pd.Series("", index=sess, dtype=object)
    out.loc[part.index] = part.to_numpy()
    out.loc[sess >= fwd] = "forward"
    return out


def partition(name: str, manifest: dict | None = None,
              version: str = "v1") -> pd.DatetimeIndex:
    """The sessions belonging to one partition."""
    if name not in SETS + ("forward",):
        raise SplitError(f"unknown partition {name!r}")
    m = manifest or load(version)
    s = session_partitions(m)
    return pd.DatetimeIndex(s.index[s == name])


def assign(df: pd.DataFrame, manifest: dict | None = None, version: str = "v1",
           date_col: str = "date", drop_purged: bool = True) -> pd.DataFrame:
    """Attach a `partition` column to any dated frame.

    This is the only supported way to select rows for an experiment. A
    hand-written date range is how a holdout gets read twice.
    """
    m = manifest or load(version)
    s = session_partitions(m)
    out = df.copy()
    d = pd.to_datetime(out[date_col])
    out["partition"] = pd.Series(d.map(s).to_numpy(), index=out.index).fillna("")
    if drop_purged:
        out = out[out["partition"] != ""]
    return out


def check_horizon(horizon: int, manifest: dict) -> None:
    """Raise if a forward horizon exceeds what this version was purged for."""
    mh = manifest["purge"]["max_horizon"]
    if horizon > mh:
        raise SplitError(
            f"horizon {horizon} exceeds split {manifest['version']}'s "
            f"max_horizon of {mh}. Its labels would cross a boundary this "
            "split did not purge. Build a longer-horizon version instead.")


def blocked_families(manifest: dict, name: str,
                     partitions: tuple[str, ...] = ("test",)) -> list[str]:
    """Quarters in `partitions` that family `name` has already read.

    The ledger's job in one function: if this returns anything, the hypothesis
    may not be scored on that partition.
    """
    out = []
    for q in manifest["quarters"]:
        if q["set"] not in partitions:
            continue
        if any(e["family"] == name for e in q["prior_exposure"]):
            out.append(q["quarter"])
    return out


def summary(manifest: dict) -> str:
    """A short human-readable description of a frozen split."""
    p, pu = manifest["panel"], manifest["purge"]
    lines = [
        f"split {manifest['version']}  hash={manifest['hash']}  "
        f"seed={manifest['seed_accepted']} (attempt {manifest['seed_attempts']})",
        f"panel {p['first_session']} -> {p['last_session']}  "
        f"{p['n_sessions']} sessions, {p['n_quarters']} quarters",
        f"quarters  " + "  ".join(
            f"{s}={manifest['quarter_counts'][s]}" for s in SETS),
        f"sessions  " + "  ".join(
            f"{s}={manifest['session_counts'][s]}" for s in SETS),
        f"purged    {pu['sessions_dropped']} sessions "
        f"({pu['dropped_pct_of_panel']}% of panel) over {pu['n_boundaries']} "
        f"boundaries; horizon={pu['max_horizon']} embargo={pu['embargo']}",
        f"          by set: " + "  ".join(
            f"{s}={pu['dropped_by_set'][s]}" for s in SETS),
        f"forward   from {manifest['forward']['start']}: "
        f"{manifest['forward']['n_sessions']} sessions",
    ]
    return "\n".join(lines)
