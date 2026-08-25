"""Do price levels interrupt the path more than matched fake levels do?

WHAT THIS IS FOR
Price reacts everywhere. It is always pausing, turning and overshooting, so
anyone who draws a line and then looks for reactions at it will find them — and
will remember the ones that worked. That is not weak evidence for support and
resistance; it is no evidence at all, because the procedure has no way to fail.
The only way to get an answer is to run the identical measurement against lines
that are *not* levels and compare.

So this module measures one thing: when price arrives at a line, how often does
it turn back before it carries on? It measures that at real levels and at two
kinds of fake level, and reports the difference.

WHY IT IS THE RIGHT FIRST QUESTION
It is cheap, it is decisive in the negative, and it separates two failures that
look identical from the outside. If real and fake lines behave the same, levels
carry no information and no amount of contextual selection or AI judgement can
recover any — the thing being selected is noise. If real lines do interrupt the
path, the premise survives and the open question becomes whether the effect is
big enough to pay costs, which is a different and much later argument.

Under H056 the level's job is to make risk cheap rather than to predict
direction, so the statistic here is deliberately a *path* statistic and not a
return: which of two symmetric barriers is touched first, measured in the frame
of the approach. That is the excursion question PLAN.md §10 E1 permits — "the
probability of reaching either side of a predeclared barrier" — and it inspects
no sign, no hit rate and no payoff.

THE TWO CONTROLS, AND WHY ONE IS NOT ENOUGH
`random_price` puts fake lines at uniformly drawn prices around the same
reference. It answers "is a level better than *any* price?".

That control is too easy on its own, because real levels are not uniformly
placed: they sit at particular distances from where price already is, and
distance alone changes how often a barrier race resolves. So `permuted_geometry`
takes the real level *offsets* — distance from the reference close in lagged ATR
units — from a different randomly chosen symbol-session and replays them here.
The fake book then has the same distance distribution, the same widths and the
same volatility scaling as the real one, and differs only in being unrelated to
this symbol's own history. That is the pseudo-zone PLAN.md §9 requires, and it
is the control that can actually kill the hypothesis.

WHAT IS HELD CONSTANT
Every contrast is paired inside one symbol-session: same stock, same day, same
volatility, same market direction, same time-of-day mix. Real and fake lines are
scored by the same functions over the same bars, so nothing differs except which
prices the lines sit at.

EXPOSURE
This reads the future price path and is therefore real, logged sample exposure,
not an outcome-free preflight. It does not read directional payoff, and it must
be registered before it is run.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from ...research_data.pipelines import levels as levels_pipeline

APPROACH_COLUMNS = (
    "symbol", "session", "level_id", "detector", "book", "approach_at",
    "approach_from", "reference_price", "atr", "distance_atr",
)


class ReactionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReactionConfig:
    """The frozen measurement grid. Every cell is declared before the run."""

    # A touch is a decision-timeframe bar whose range overlaps the level while
    # the previous bar's range did not.
    barrier_atr: float = 0.50
    horizon_bars: int = 24
    # Declared secondary grid. The reported result is the maximum over this
    # neighbourhood judged against the permuted maximum, not a best cell.
    barrier_grid: tuple[float, ...] = (0.35, 0.50, 0.75)
    horizon_grid: tuple[int, ...] = (12, 24, 48)
    pseudo_per_real: int = 20
    min_level_age_bars: int = 1
    seed: int = 20260825

    def __post_init__(self) -> None:
        if self.barrier_atr <= 0 or self.horizon_bars < 1:
            raise ValueError("barrier and horizon must be positive")
        if not self.barrier_grid or min(self.barrier_grid) <= 0:
            raise ValueError("barrier grid must be positive")
        if not self.horizon_grid or min(self.horizon_grid) < 1:
            raise ValueError("horizon grid must be positive")
        if self.pseudo_per_real < 1:
            raise ValueError("need at least one pseudo level per real level")

    def cells(self) -> list[tuple[float, int]]:
        return [(barrier, horizon)
                for barrier in self.barrier_grid
                for horizon in self.horizon_grid]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _reference_frame(bars: pd.DataFrame,
                     config: levels_pipeline.LevelConfig) -> pd.DataFrame:
    """Per symbol-session lagged ATR and prior close — the scaling reference.

    Both are lagged by construction in `levels.session_atr`, so a pseudo level
    built from them uses nothing from the session it will be tested in.
    """
    reference = levels_pipeline.session_atr(bars, config.atr_window)
    return reference[["symbol", "session", "session_atr", "prior_close"]].rename(
        columns={"session_atr": "atr"})


def find_approaches(decision_bars: pd.DataFrame, book: pd.DataFrame,
                    reference: pd.DataFrame,
                    config: ReactionConfig | None = None,
                    book_label: str = "real") -> pd.DataFrame:
    """Locate every first-touch of a knowable level on the decision timeframe.

    A touch is the bar whose range overlaps the level when the previous bar's
    range did not, so a level that price sits inside for an hour produces one
    approach rather than twelve correlated ones.
    """
    cfg = config or ReactionConfig()
    if book.empty:
        return pd.DataFrame(columns=list(APPROACH_COLUMNS))
    bars = decision_bars.sort_values(["symbol", "bar_end"], kind="stable").copy()
    bars["session"] = pd.to_datetime(bars["session"], errors="raise").dt.normalize()
    bars = bars.merge(reference, on=["symbol", "session"], how="left")

    records: list[dict[str, Any]] = []
    grouped_levels = {
        symbol: group for symbol, group in book.groupby("symbol", sort=False)}

    for symbol, group in bars.groupby("symbol", sort=False):
        symbol_levels = grouped_levels.get(symbol)
        if symbol_levels is None or symbol_levels.empty:
            continue
        group = group.reset_index(drop=True)
        highs = group["high"].to_numpy(float)
        lows = group["low"].to_numpy(float)
        closes = group["close"].to_numpy(float)
        times = pd.to_datetime(group["bar_end"]).to_numpy()
        sessions = group["session"].to_numpy()
        atrs = group["atr"].to_numpy(float)

        for level in symbol_levels.itertuples(index=False):
            lower, upper = float(level.lower), float(level.upper)
            known = np.datetime64(pd.Timestamp(level.known_at))
            expiry = np.datetime64(pd.Timestamp(level.valid_until))
            # Only bars inside the level's own validity window are compared.
            # Scanning a level against the symbol's whole history is both wrong
            # — it lets a level match long after it stopped being a level — and
            # quadratic, which is what made the first version unusable at panel
            # scale.
            start = int(np.searchsorted(times, known, side="left"))
            stop = int(np.searchsorted(times, expiry, side="right"))
            if stop - start < 2:
                continue
            window_highs = highs[start:stop]
            window_lows = lows[start:stop]
            touching = (window_highs >= lower) & (window_lows <= upper)
            if not touching.any():
                continue
            previous = np.roll(touching, 1)
            previous[0] = False
            first = touching & ~previous
            for offset in np.flatnonzero(first):
                position = start + int(offset)
                if position + 1 >= len(group) or position == 0:
                    continue
                atr = atrs[position]
                if not np.isfinite(atr) or atr <= 0:
                    continue
                previous_close = closes[position - 1]
                center = (lower + upper) / 2.0
                if previous_close > upper:
                    approach_from = "above"
                elif previous_close < lower:
                    approach_from = "below"
                else:
                    # Price was already inside the band on the prior bar; there
                    # is no approach direction to speak of, so the event is not
                    # a touch and is dropped rather than assigned a guess.
                    continue
                records.append({
                    "symbol": symbol, "session": sessions[position],
                    "level_id": level.level_id, "detector": level.detector,
                    "book": book_label, "approach_at": times[position],
                    "approach_from": approach_from,
                    "reference_price": float(closes[position]), "atr": float(atr),
                    "distance_atr": float(abs(previous_close - center) / atr),
                })
    if not records:
        return pd.DataFrame(columns=list(APPROACH_COLUMNS))
    return pd.DataFrame(records)[list(APPROACH_COLUMNS)]


def _path_index(path_bars: pd.DataFrame) -> dict[str, Any]:
    """Flatten the path panel into one contiguous array plus symbol bounds.

    Every symbol's bars live in one global array so a window can be taken by
    fancy indexing rather than by slicing a DataFrame per event. The per-symbol
    end bound is what stops a window running off the end of one symbol and into
    the next one's prices.
    """
    path = path_bars.sort_values(["symbol", "bar_end"], kind="stable").reset_index(drop=True)
    symbols = path["symbol"].to_numpy()
    bounds: dict[str, tuple[int, int]] = {}
    if len(path):
        changes = np.flatnonzero(symbols[1:] != symbols[:-1]) + 1
        starts = np.concatenate([[0], changes])
        stops = np.concatenate([changes, [len(path)]])
        bounds = {str(symbols[begin]): (int(begin), int(stop))
                  for begin, stop in zip(starts, stops)}
    return {
        "high": path["high"].to_numpy(float),
        "low": path["low"].to_numpy(float),
        "time": pd.to_datetime(path["bar_end"]).to_numpy("datetime64[ns]"),
        "bounds": bounds,
    }


def race_grid(approaches: pd.DataFrame, path_bars: pd.DataFrame,
              barriers: tuple[float, ...], horizons: tuple[int, ...],
              chunk_size: int = 200_000) -> pd.DataFrame:
    """Which symmetric barrier is touched first, for every declared cell.

    `rejection` is movement back the way price came; `penetration` is movement
    onward through the line. Both are measured from the approach bar's close, so
    the barriers are symmetric by construction and a coin flip is 0.5.

    The race runs on five-minute bars even though the approach was detected on
    the hourly series. This is the whole reason the intraday pull exists: an
    hourly bar reports a high and a low but not their order, so an hourly-only
    race cannot say which barrier came first whenever both sit inside one bar's
    range — and with a barrier under one ATR, that is most of them.

    Every cell is resolved from a single scan out to the longest horizon: the
    first crossing index does not depend on the horizon, only on the barrier, so
    a shorter horizon is a comparison against that index rather than a re-scan.
    """
    columns = list(approaches.columns) + ["barrier_atr", "horizon_bars", "outcome"]
    if approaches.empty:
        return pd.DataFrame(columns=columns)
    index = _path_index(path_bars)
    max_horizon = int(max(horizons))

    events = approaches.reset_index(drop=True)
    starts = np.full(len(events), -1, dtype=np.int64)
    limits = np.zeros(len(events), dtype=np.int64)
    for symbol, positions in events.groupby("symbol", sort=False).groups.items():
        bound = index["bounds"].get(str(symbol))
        rows = np.asarray(positions, dtype=np.int64)
        if bound is None:
            continue
        begin, stop = bound
        times = index["time"][begin:stop]
        wanted = pd.to_datetime(
            events.loc[rows, "approach_at"]).to_numpy("datetime64[ns]")
        offsets = np.searchsorted(times, wanted, side="right")
        starts[rows] = begin + offsets
        limits[rows] = stop

    reference = events["reference_price"].to_numpy(float)
    atr = events["atr"].to_numpy(float)
    from_below = events["approach_from"].to_numpy() == "below"

    frames: list[pd.DataFrame] = []
    offsets = np.arange(max_horizon, dtype=np.int64)
    for begin in range(0, len(events), chunk_size):
        stop = min(begin + chunk_size, len(events))
        rows = slice(begin, stop)
        start_chunk = starts[rows]
        limit_chunk = limits[rows]
        usable = start_chunk >= 0

        window = start_chunk[:, None] + offsets[None, :]
        inside = (window < limit_chunk[:, None]) & usable[:, None]
        clipped = np.clip(window, 0, max(len(index["high"]) - 1, 0))
        highs = np.where(inside, index["high"][clipped], -np.inf)
        lows = np.where(inside, index["low"][clipped], np.inf)

        for barrier in barriers:
            offset = barrier * atr[rows]
            up_level = reference[rows] + offset
            down_level = reference[rows] - offset
            hit_up = highs >= up_level[:, None]
            hit_down = lows <= down_level[:, None]
            # `argmax` on an all-False row returns 0, so absence is recorded
            # explicitly rather than read as "crossed on the first bar".
            first_up = np.where(hit_up.any(axis=1), hit_up.argmax(axis=1), max_horizon)
            first_down = np.where(
                hit_down.any(axis=1), hit_down.argmax(axis=1), max_horizon)
            below = from_below[rows]
            first_rejection = np.where(below, first_down, first_up)
            first_penetration = np.where(below, first_up, first_down)
            for horizon in horizons:
                rejected = first_rejection < horizon
                penetrated = first_penetration < horizon
                outcome = np.full(stop - begin, "neither", dtype=object)
                outcome[rejected & ~penetrated] = "rejection"
                outcome[penetrated & ~rejected] = "penetration"
                both = rejected & penetrated
                outcome[both & (first_rejection < first_penetration)] = "rejection"
                outcome[both & (first_penetration < first_rejection)] = "penetration"
                # Both barriers inside one five-minute bar: the order is not
                # knowable at this resolution, so it is not guessed.
                outcome[both & (first_rejection == first_penetration)] = "ambiguous"
                outcome[~usable] = "no_path"
                chunk = events.iloc[rows].copy()
                chunk["barrier_atr"] = barrier
                chunk["horizon_bars"] = horizon
                chunk["outcome"] = outcome
                frames.append(chunk)
    return pd.concat(frames, ignore_index=True)[columns]


def race_barriers(approaches: pd.DataFrame, path_bars: pd.DataFrame,
                  barrier_atr: float, horizon_bars: int) -> pd.DataFrame:
    """Single-cell view of `race_grid`, kept as the readable entry point."""
    scored = race_grid(approaches, path_bars, (barrier_atr,), (horizon_bars,))
    if scored.empty:
        return approaches.assign(outcome=pd.Series(dtype=str))
    return scored.drop(columns=["barrier_atr", "horizon_bars"])


def build_pseudo_book(book: pd.DataFrame, reference: pd.DataFrame, mode: str,
                      config: ReactionConfig | None = None) -> pd.DataFrame:
    """Fake level books matched to a real one.

    `random_price` draws centres uniformly within the ATR band the real levels
    of that symbol-session occupy. `permuted_geometry` replays another
    symbol-session's real offsets here, so distance, width and volatility
    scaling are preserved and only the link to this symbol's history is broken.
    """
    cfg = config or ReactionConfig()
    if mode not in ("random_price", "permuted_geometry"):
        raise ReactionError(f"unknown pseudo-level mode: {mode!r}")
    if book.empty:
        return book.copy()

    rng = np.random.default_rng(cfg.seed)
    work = book.copy()
    work["known_session"] = pd.to_datetime(work["known_at"]).dt.normalize()
    merged = work.merge(
        reference.rename(columns={"session": "known_session"}),
        on=["symbol", "known_session"], how="left")
    merged = merged.loc[merged["atr"].gt(0) & merged["prior_close"].gt(0)]
    if merged.empty:
        return levels_pipeline._empty_book()

    merged["offset_atr"] = (
        (merged["center"] - merged["prior_close"]) / merged["atr"])
    merged["width_atr"] = (merged["upper"] - merged["lower"]) / 2.0 / merged["atr"]

    groups = list(merged.groupby(["symbol", "known_session", "detector"], sort=True))
    donor_pool = {key: group["offset_atr"].to_numpy(float) for key, group in groups}
    donor_keys = list(donor_pool)

    rows: list[dict[str, Any]] = []
    for (symbol, known_session, detector), group in groups:
        prior_close = float(group["prior_close"].iloc[0])
        atr = float(group["atr"].iloc[0])
        known_at = group["known_at"].iloc[0]
        # The control must live exactly as long as the level it controls for.
        valid_until = group["valid_until"].max()
        widths = group["width_atr"].to_numpy(float)
        count = len(group) * cfg.pseudo_per_real

        if mode == "random_price":
            span = float(np.nanmax(np.abs(group["offset_atr"].to_numpy(float))))
            span = span if np.isfinite(span) and span > 0 else 1.0
            offsets = rng.uniform(-span, span, size=count)
        else:
            candidates = [key for key in donor_keys
                          if key[0] != symbol and key[2] == detector]
            if not candidates:
                continue
            picks = rng.integers(0, len(candidates), size=count)
            offsets = np.array([
                float(rng.choice(donor_pool[candidates[pick]])) for pick in picks])

        chosen_widths = rng.choice(widths, size=count, replace=True)
        for index, (offset, width_atr) in enumerate(zip(offsets, chosen_widths)):
            center = prior_close + offset * atr
            if not np.isfinite(center) or center <= 0:
                continue
            half = max(float(width_atr) * atr, center * 1e-4)
            rows.append({
                "level_id": f"PSEUDO_{mode[:4].upper()}_{symbol}_"
                            f"{pd.Timestamp(known_session).date()}_{detector}_{index}",
                "symbol": symbol, "detector": detector, "kind": "both",
                "origin_at": known_at, "known_at": known_at,
                "valid_until": valid_until,
                "center": float(center), "lower": float(center - half),
                "upper": float(center + half), "significance": 0.0,
                "source_sessions": 0,
            })
    if not rows:
        return levels_pipeline._empty_book()
    return pd.DataFrame(rows)[list(levels_pipeline.LEVEL_COLUMNS)]


def rejection_rate(scored: pd.DataFrame) -> pd.DataFrame:
    """Per symbol-session, detector and book: share of resolved races rejected.

    Unresolved races (`neither`, `ambiguous`, `no_path`) are excluded from the
    rate but kept in `n_events`, so a book that mostly fails to resolve cannot
    hide behind a clean-looking rate.
    """
    if scored.empty:
        return pd.DataFrame(columns=[
            "symbol", "session", "detector", "book", "n_events", "n_resolved",
            "rejection_rate"])
    work = scored.copy()
    work["session"] = pd.to_datetime(work["session"]).dt.normalize()
    work["resolved"] = work["outcome"].isin(["rejection", "penetration"])
    work["is_rejection"] = work["outcome"].eq("rejection")
    summary = work.groupby(["symbol", "session", "detector", "book"], sort=True).agg(
        n_events=("outcome", "size"), n_resolved=("resolved", "sum"),
        n_rejection=("is_rejection", "sum")).reset_index()
    summary["rejection_rate"] = np.where(
        summary["n_resolved"] > 0,
        summary["n_rejection"] / summary["n_resolved"], np.nan)
    return summary


def paired_contrast(summary: pd.DataFrame, control: str) -> pd.DataFrame:
    """Real minus control, paired inside each symbol-session.

    Pairing within the symbol-session is what removes market direction,
    volatility regime and time-of-day mix. A symbol-session that produced
    resolved races for only one of the two books contributes nothing, because
    an unpaired difference is not a difference.
    """
    real = summary.loc[summary["book"] == "real"]
    fake = summary.loc[summary["book"] == control]
    keys = ["symbol", "session", "detector"]
    merged = real.merge(fake, on=keys, how="inner", suffixes=("_real", "_pseudo"))
    merged = merged.loc[
        merged["rejection_rate_real"].notna()
        & merged["rejection_rate_pseudo"].notna()].copy()
    merged["contrast"] = (
        merged["rejection_rate_real"] - merged["rejection_rate_pseudo"])
    merged["control"] = control
    return merged


def session_clustered_estimate(contrast: pd.DataFrame) -> dict[str, Any]:
    """Mean contrast with the session as the independent unit.

    Symbols move together inside a session, so the symbol-session is not an
    independent trial and the session is. Collapsing to a session mean first is
    the conservative reading the lab already uses everywhere.
    """
    if contrast.empty:
        return {"n_sessions": 0, "n_symbol_sessions": 0, "mean_contrast": None,
                "std_error": None, "t_stat": None}
    by_session = contrast.groupby("session", sort=True)["contrast"].mean()
    values = by_session.to_numpy(float)
    count = len(values)
    mean = float(np.mean(values))
    if count < 2:
        return {"n_sessions": count, "n_symbol_sessions": int(len(contrast)),
                "mean_contrast": mean, "std_error": None, "t_stat": None}
    error = float(np.std(values, ddof=1) / np.sqrt(count))
    return {
        "n_sessions": count, "n_symbol_sessions": int(len(contrast)),
        "mean_contrast": mean, "std_error": error,
        "t_stat": float(mean / error) if error > 0 else None,
    }


def permutation_maximum(contrast_by_cell: dict[str, pd.DataFrame],
                        draws: int = 2000, seed: int = 20260825) -> dict[str, Any]:
    """Null distribution of the largest |t| across the declared grid.

    The search here is a grid of detectors, barriers and horizons, so the honest
    comparison is the observed maximum against the maximum a null world would
    have produced over the *same* grid. Signs are flipped at the session level,
    which preserves the correlation between cells — a per-cell null would
    reward a grid whose cells agree.
    """
    if not contrast_by_cell:
        return {"draws": 0, "observed_max_t": None, "null_p": None}
    sessions = sorted({
        session for frame in contrast_by_cell.values()
        for session in frame["session"].unique()})
    if len(sessions) < 2:
        return {"draws": 0, "observed_max_t": None, "null_p": None}
    index = {session: position for position, session in enumerate(sessions)}

    prepared: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for name, frame in contrast_by_cell.items():
        by_session = frame.groupby("session", sort=True)["contrast"].mean()
        positions = np.array([index[session] for session in by_session.index])
        prepared[name] = (positions, by_session.to_numpy(float))

    def statistic(signs: np.ndarray) -> float:
        best = 0.0
        for positions, values in prepared.values():
            flipped = values * signs[positions]
            count = len(flipped)
            if count < 2:
                continue
            error = np.std(flipped, ddof=1) / np.sqrt(count)
            if error <= 0:
                continue
            best = max(best, abs(float(np.mean(flipped) / error)))
        return best

    observed = statistic(np.ones(len(sessions)))
    rng = np.random.default_rng(seed)
    null = np.array([
        statistic(rng.choice([-1.0, 1.0], size=len(sessions)))
        for _ in range(draws)])
    return {
        "draws": draws, "observed_max_t": observed,
        "null_max_t_p95": float(np.quantile(null, 0.95)),
        "null_p": float((null >= observed).mean()),
    }


def _accumulate(contrast: pd.DataFrame, barrier: float, horizon: int,
                control: str) -> pd.DataFrame:
    """Collapse a batch's paired contrasts to per-session sums and counts.

    The session-clustered estimate and the permutation null both need only the
    *per-session mean* contrast, so a batch can be reduced to sums and counts
    and then discarded. That is what makes the study memory-bounded: the panel
    generates hundreds of millions of approach events, but the state carried
    between batches is a few tens of thousands of rows.
    """
    if contrast.empty:
        return pd.DataFrame(columns=[
            "session", "detector", "control", "barrier_atr", "horizon_bars",
            "contrast_sum", "n_symbol_sessions", "real_sum", "pseudo_sum"])
    out = contrast.groupby(["session", "detector"], sort=False).agg(
        contrast_sum=("contrast", "sum"),
        n_symbol_sessions=("contrast", "size"),
        real_sum=("rejection_rate_real", "sum"),
        pseudo_sum=("rejection_rate_pseudo", "sum"),
    ).reset_index()
    out["control"] = control
    out["barrier_atr"] = float(barrier)
    out["horizon_bars"] = int(horizon)
    return out


def run_reaction_study(five_minute_bars: pd.DataFrame,
                       detectors: tuple[str, ...] | None = None,
                       controls: tuple[str, ...] = ("random_price",
                                                    "permuted_geometry"),
                       config: ReactionConfig | None = None,
                       level_config: levels_pipeline.LevelConfig | None = None,
                       symbol_batch: int = 8,
                       progress: Any = None,
                       ) -> dict[str, Any]:
    """The whole study: decisions hourly, path five-minute, real against fake.

    Symbols are processed in batches. `permuted_geometry` donates offsets from a
    *different symbol*, so a batch must hold more than one symbol for that
    control to exist at all; the batch is also the unit that bounds memory.

    Returns a report rather than a verdict. Reading it is what spends the
    exposure; the frozen bar lives in the hypothesis, not here.
    """
    cfg = config or ReactionConfig()
    level_cfg = level_config or levels_pipeline.LevelConfig()
    names = detectors or tuple(levels_pipeline.DETECTORS)
    if symbol_batch < 2:
        raise ReactionError(
            "symbol_batch must be at least 2 or permuted_geometry has no donor")

    symbols = sorted(five_minute_bars["symbol"].astype(str).unique())
    batches = [symbols[index:index + symbol_batch]
               for index in range(0, len(symbols), symbol_batch)]

    accumulated: list[pd.DataFrame] = []
    book_sizes: dict[str, int] = {name: 0 for name in names}
    event_counts: dict[str, int] = {}
    outcome_counts: dict[str, int] = {}

    for number, batch in enumerate(batches, start=1):
        panel = five_minute_bars.loc[
            five_minute_bars["symbol"].astype(str).isin(batch)].copy()
        if panel.empty:
            continue
        hourly = levels_pipeline.resample_hourly(panel)
        decisions = hourly.loc[hourly["complete"]].copy()
        reference = _reference_frame(panel, level_cfg)
        path = levels_pipeline._normalise_bars(panel)

        approaches: list[pd.DataFrame] = []
        for name in names:
            real = levels_pipeline.DETECTORS[name](panel, level_cfg)
            book_sizes[name] += int(len(real))
            if real.empty:
                continue
            approaches.append(
                find_approaches(decisions, real, reference, cfg, "real"))
            for control in controls:
                fake = build_pseudo_book(real, reference, control, cfg)
                if fake.empty:
                    continue
                approaches.append(
                    find_approaches(decisions, fake, reference, cfg, control))
        approaches = [frame for frame in approaches if not frame.empty]
        if not approaches:
            continue
        events = pd.concat(approaches, ignore_index=True)
        for key, value in events["book"].value_counts().items():
            event_counts[str(key)] = event_counts.get(str(key), 0) + int(value)

        scored = race_grid(events, path, cfg.barrier_grid, cfg.horizon_grid)
        for key, value in scored["outcome"].value_counts().items():
            outcome_counts[str(key)] = outcome_counts.get(str(key), 0) + int(value)
        for (barrier, horizon), cell in scored.groupby(
                ["barrier_atr", "horizon_bars"], sort=True):
            summary = rejection_rate(cell)
            for control in controls:
                accumulated.append(_accumulate(
                    paired_contrast(summary, control), barrier, horizon, control))
        del events, scored, approaches
        if progress is not None:
            progress(number, len(batches), batch)

    if not accumulated:
        return {"status": "no_approaches", "config": cfg.to_dict()}

    totals = pd.concat(accumulated, ignore_index=True)
    totals = totals.groupby(
        ["session", "detector", "control", "barrier_atr", "horizon_bars"],
        sort=False).agg(contrast_sum=("contrast_sum", "sum"),
                        n_symbol_sessions=("n_symbol_sessions", "sum"),
                        real_sum=("real_sum", "sum"),
                        pseudo_sum=("pseudo_sum", "sum")).reset_index()
    totals["contrast"] = totals["contrast_sum"] / totals["n_symbol_sessions"]

    cells: dict[str, pd.DataFrame] = {}
    rows: list[dict[str, Any]] = []
    for (detector, control, barrier, horizon), cell in totals.groupby(
            ["detector", "control", "barrier_atr", "horizon_bars"], sort=True):
        estimate = session_clustered_estimate(cell)
        primary = (barrier == cfg.barrier_atr and horizon == cfg.horizon_bars)
        rows.append({
            "detector": detector, "control": control,
            "barrier_atr": float(barrier), "horizon_bars": int(horizon),
            "primary": bool(primary),
            "n_symbol_sessions": int(cell["n_symbol_sessions"].sum()),
            "real_rejection_rate": float(
                cell["real_sum"].sum() / cell["n_symbol_sessions"].sum()),
            "pseudo_rejection_rate": float(
                cell["pseudo_sum"].sum() / cell["n_symbol_sessions"].sum()),
            **{key: value for key, value in estimate.items()
               if key != "n_symbol_sessions"},
        })
        if len(cell) >= 2:
            cells[f"{detector}|{control}|{barrier}|{horizon}"] = cell
    return {
        "status": "complete",
        "config": cfg.to_dict(),
        "level_config": asdict(level_cfg),
        "detectors": list(names),
        "controls": list(controls),
        "symbol_batches": len(batches),
        "book_sizes": book_sizes,
        "events": {"total": int(sum(event_counts.values())),
                   "by_book": event_counts},
        "outcomes": outcome_counts,
        "grid": rows,
        "multiplicity": permutation_maximum(cells, seed=cfg.seed),
    }


__all__ = [
    "APPROACH_COLUMNS", "ReactionConfig", "ReactionError", "build_pseudo_book",
    "find_approaches", "paired_contrast", "permutation_maximum", "race_barriers",
    "rejection_rate", "run_reaction_study", "session_clustered_estimate",
]
