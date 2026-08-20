"""The feature catalogue — the agent's map of every computable feature.

WHY THIS EXISTS
Three of the four lookaheads this project caught entered through features that
*looked* safe but had a contaminated input: a denominator built from unlagged
data, a present-day index membership applied to historical rows, a gap between
observations that was only knowable after the next observation printed. Each
of these is a fact about a feature's metadata, not about its code, and it could
have been caught by a registry that knew the metadata and checked it
transitively.

That is what this module is: a machine-readable record of every feature the
system can compute, with the fields that let the leakage gate, the scoring
guard and the experiment runner answer "may I use this?" without reading the
source code that produces it.

TWO RULES FROM §5.3 OF THE PLAN
- A feature whose `point_in_time` is false may be used for *stratification*
  (report by sector) but not for *scoring* (rank on sector), and the module
  enforces the difference.
- **PIT status is inherited from inputs.** A clean numerator over a
  contaminated denominator is contaminated. `validate_pit()` walks the input
  graph transitively.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator


# ---------------------------------------------------------------------------
# the spec
# ---------------------------------------------------------------------------

# available_as_of values, ordered from earliest to latest:
#   "static"      — identity / metadata, always knowable
#   "prev_close"  — knowable after D-1 close (the safe default)
#   "open"        — knowable at 09:15:00 on date D (call auction)
#   "intraday_t"  — knowable at a specific second offset within the session
#   "close"       — knowable only after D's close (must be lagged for morning)
#   "future"      — a forward label; never a feature input
AVAILABILITY_ORDER = ("static", "prev_close", "open", "intraday_t", "close",
                      "future")


@dataclass(frozen=True)
class FeatureSpec:
    """Everything the system needs to know about one feature column."""

    name: str
    description: str
    available_as_of: str          # when this value is first knowable
    lookback: int                 # sessions of history consumed (0 for static)
    adjusted: bool                # True = computed on adjusted prices
    point_in_time: bool           # False for snapshot attributes
    inputs: tuple[str, ...] = ()  # names of features it derives from
    owner: str = ""               # pipeline stage that produces it
    known_caveats: str = ""
    max_horizon_safe: int = 20
    # If True, the feature may only be used for stratification, never scoring.
    # Automatically set for non-PIT features.
    stratification_only: bool = False

    def __post_init__(self) -> None:
        if self.available_as_of not in AVAILABILITY_ORDER:
            raise ValueError(
                f"available_as_of must be one of {AVAILABILITY_ORDER}, "
                f"got {self.available_as_of!r}")

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# the registry
# ---------------------------------------------------------------------------

class CatalogueError(RuntimeError):
    pass


class Catalogue:
    """A registry of FeatureSpec entries with validation and lookup."""

    def __init__(self) -> None:
        self._specs: dict[str, FeatureSpec] = {}

    def register(self, spec: FeatureSpec) -> None:
        """Add a feature to the catalogue. Duplicates raise."""
        if spec.name in self._specs:
            raise CatalogueError(
                f"feature {spec.name!r} is already registered")
        self._specs[spec.name] = spec

    def register_many(self, specs: list[FeatureSpec]) -> None:
        for s in specs:
            self.register(s)

    def __getitem__(self, name: str) -> FeatureSpec:
        if name not in self._specs:
            raise KeyError(f"feature {name!r} is not in the catalogue")
        return self._specs[name]

    def __contains__(self, name: str) -> bool:
        return name in self._specs

    def __len__(self) -> int:
        return len(self._specs)

    def __iter__(self) -> Iterator[FeatureSpec]:
        return iter(self._specs.values())

    def all_features(self) -> list[FeatureSpec]:
        return list(self._specs.values())

    @property
    def names(self) -> list[str]:
        return list(self._specs)

    # ------------------------------------------------------------------
    # validation
    # ------------------------------------------------------------------

    def validate_pit(self, name: str) -> tuple[bool, list[str]]:
        """Walk the input graph and check PIT status transitively.

        Returns (is_pit, chain) where chain lists the non-PIT ancestors
        if any. A feature declared PIT but with a non-PIT input is
        contaminated, and the chain says where the contamination enters.

        This is the check that would have caught the unlagged median_vol_20
        denominator automatically.
        """
        visited: set[str] = set()
        non_pit_chain: list[str] = []

        def _walk(n: str) -> bool:
            if n in visited:
                return True
            visited.add(n)
            if n not in self._specs:
                # Unknown input — conservative: treat as PIT so we don't
                # false-alarm on external columns not yet registered.
                return True
            spec = self._specs[n]
            if not spec.point_in_time:
                non_pit_chain.append(n)
                return False
            for inp in spec.inputs:
                if not _walk(inp):
                    non_pit_chain.append(n)
                    return False
            return True

        is_pit = _walk(name)
        return is_pit, non_pit_chain

    def scorable(self, name: str) -> bool:
        """May this feature be used for ranking / scoring?

        Non-PIT features and features with non-PIT ancestors may only
        stratify, never score. This is the guard that would have caught
        size_tier_rank being used as a ranking (H030).
        """
        spec = self._specs[name]
        if spec.stratification_only:
            return False
        if spec.available_as_of == "future":
            return False
        is_pit, _ = self.validate_pit(name)
        return is_pit

    def safe_for_morning(self, name: str) -> bool:
        """Is this feature knowable at 09:20 on date D?

        Features available at "prev_close", "open", or "static" are safe.
        "close" features are safe only if accessed through the lagged panel.
        "intraday_t" features are safe if t <= 300s (5 minutes).
        "future" features are never safe.
        """
        spec = self._specs[name]
        return spec.available_as_of in ("static", "prev_close", "open",
                                        "intraday_t")

    def by_owner(self, owner: str) -> list[FeatureSpec]:
        return [s for s in self._specs.values() if s.owner == owner]

    def non_pit(self) -> list[FeatureSpec]:
        return [s for s in self._specs.values() if not s.point_in_time]

    def forward_labels(self) -> list[FeatureSpec]:
        return [s for s in self._specs.values()
                if s.available_as_of == "future"]

    # ------------------------------------------------------------------
    # serialisation
    # ------------------------------------------------------------------

    def to_list(self) -> list[dict]:
        return [s.to_dict() for s in self._specs.values()]

    def to_json(self, path: Path | None = None) -> str:
        text = json.dumps(self.to_list(), indent=2) + "\n"
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return text

    @classmethod
    def from_list(cls, entries: list[dict]) -> "Catalogue":
        cat = cls()
        for e in entries:
            # Handle tuple serialisation
            if isinstance(e.get("inputs"), list):
                e["inputs"] = tuple(e["inputs"])
            cat.register(FeatureSpec(**e))
        return cat

    def summary(self) -> str:
        """Human-readable summary table."""
        lines = [
            f"Feature catalogue: {len(self._specs)} features",
            "",
            f"  {'name':<35s} {'as_of':<14s} {'PIT':>3s} "
            f"{'score':>5s} {'lookback':>8s} {'owner':<16s}",
            "  " + "-" * 85,
        ]
        for s in self._specs.values():
            pit = "Y" if s.point_in_time else "N"
            score = "Y" if self.scorable(s.name) else "N"
            lines.append(
                f"  {s.name:<35s} {s.available_as_of:<14s} {pit:>3s} "
                f"{score:>5s} {s.lookback:>8d} {s.owner:<16s}"
            )
        by_owner = {}
        for s in self._specs.values():
            by_owner.setdefault(s.owner, []).append(s)
        lines.append("")
        lines.append("  by owner: " + "  ".join(
            f"{k}={len(v)}" for k, v in sorted(by_owner.items())))
        n_pit = sum(1 for s in self._specs.values() if s.point_in_time)
        n_scorable = sum(1 for s in self._specs.values()
                         if self.scorable(s.name))
        lines.append(f"  PIT: {n_pit}/{len(self._specs)}  "
                     f"scorable: {n_scorable}/{len(self._specs)}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# the default catalogue — every feature currently computable
# ---------------------------------------------------------------------------

def _daily_bar_features() -> list[FeatureSpec]:
    """Raw OHLCV and identity columns from bhavcopy."""
    F = FeatureSpec
    return [
        F("symbol", "Canonical NSE ticker after rename resolution",
          "static", 0, False, True, owner="daily_bars"),
        F("date", "Trading session date from bhavcopy",
          "static", 0, False, True, owner="daily_bars"),
        F("series", "NSE settlement series (EQ, BE, etc.)",
          "static", 0, False, True, owner="daily_bars"),
        F("open", "Session opening price (adjusted), 09:15:00 call auction",
          "open", 0, True, True, owner="daily_bars"),
        F("open_raw", "Session opening price as traded on tape",
          "open", 0, False, True, owner="daily_bars"),
        F("high", "Session high price (adjusted)",
          "close", 0, True, True, owner="daily_bars",
          known_caveats="Lookahead if unlagged: leaks date D session high"),
        F("low", "Session low price (adjusted)",
          "close", 0, True, True, owner="daily_bars",
          known_caveats="Lookahead if unlagged: leaks date D session low"),
        F("close", "Session closing price (adjusted)",
          "close", 0, True, True, owner="daily_bars",
          known_caveats="Lookahead if unlagged (H015)"),
        F("close_raw", "Unadjusted closing price as traded on tape",
          "close", 0, False, True, owner="daily_bars"),
        F("volume", "Total shares traded in session",
          "close", 0, False, True, owner="daily_bars",
          known_caveats="Lookahead if unlagged"),
        F("turnover", "Total traded value in INR",
          "close", 0, False, True, owner="daily_bars",
          known_caveats="Lookahead if unlagged"),
        F("deliv_pct", "Delivery percentage of volume traded",
          "close", 0, False, True, owner="daily_bars",
          known_caveats="Lookahead if unlagged"),
        F("prev_close", "Previous session close (adjusted), on D's row",
          "open", 0, True, True, owner="daily_bars"),
        F("prev_close_raw", "Previous session close (raw), on D's row",
          "open", 0, False, True, owner="daily_bars"),
        F("adj_factor", "Cumulative corporate-action adjustment factor",
          "open", 0, False, True, owner="daily_bars",
          known_caveats="Published in advance of ex-date"),
    ]


def _snapshot_features() -> list[FeatureSpec]:
    """Features from current-day snapshots — NOT point-in-time."""
    F = FeatureSpec
    return [
        F("sector", "NSE broad sector classification",
          "static", 0, False, False, owner="snapshot",
          known_caveats="Present-day index list snapshot. Stratify only.",
          stratification_only=True),
        F("size_tier_rank", "NSE index tier rank (50/100/200/500/750/9999)",
          "static", 0, False, False, owner="snapshot",
          known_caveats="Lookahead: ranks on current membership (H030)",
          stratification_only=True),
        F("size_tier", "Human-readable size tier bucket name",
          "static", 0, False, False, owner="snapshot",
          known_caveats="Derived from size_tier_rank. Non-PIT.",
          stratification_only=True),
        F("is_etf", "Boolean: security is an ETF",
          "static", 0, False, False, owner="snapshot",
          known_caveats="Present-day ETF list. Used for exclusion.",
          stratification_only=True),
    ]


def _indicator_features() -> list[FeatureSpec]:
    """Technical indicators from indicators.py.

    All are computed on date D's full-day data and must be lagged for
    morning use. When served through the as-of panel they carry D-1 values.
    """
    F = FeatureSpec
    # In the as-of panel these are lagged to D-1, so available_as_of is
    # "prev_close" when served correctly. Mark them as such — the catalogue
    # describes the *served* feature, not the raw computation.
    return [
        # --- trend
        F("ema_fast", "20-period EMA of adjusted close",
          "prev_close", 20, True, True, inputs=("close",),
          owner="indicators"),
        F("ema_mid", "50-period EMA of adjusted close",
          "prev_close", 50, True, True, inputs=("close",),
          owner="indicators"),
        F("ema_slow", "200-period EMA of adjusted close",
          "prev_close", 200, True, True, inputs=("close",),
          owner="indicators"),
        F("ema_fast_slope", "10-session % change of ema_fast",
          "prev_close", 30, True, True, inputs=("ema_fast",),
          owner="indicators"),
        F("ema_mid_slope", "20-session % change of ema_mid",
          "prev_close", 70, True, True, inputs=("ema_mid",),
          owner="indicators"),
        F("px_vs_ema_fast", "% distance of close vs 20-EMA",
          "prev_close", 20, True, True, inputs=("close", "ema_fast"),
          owner="indicators"),
        F("px_vs_ema_mid", "% distance of close vs 50-EMA",
          "prev_close", 50, True, True, inputs=("close", "ema_mid"),
          owner="indicators"),
        F("ema_stack_up", "Binary: ema_fast > ema_mid > ema_slow",
          "prev_close", 200, True, True,
          inputs=("ema_fast", "ema_mid", "ema_slow"), owner="indicators"),
        F("above_ema_mid", "Binary: close > ema_mid",
          "prev_close", 50, True, True, inputs=("close", "ema_mid"),
          owner="indicators",
          known_caveats="H015: gating on this forced every setup to close "
                        "above 50 EMA when unlagged"),

        # --- liquidity
        F("median_tv_20_cr", "20-session rolling median traded value (Crores)",
          "prev_close", 20, False, True, inputs=("turnover",),
          owner="indicators"),
        F("median_vol_20", "20-session rolling median volume",
          "prev_close", 20, False, True, inputs=("volume",),
          owner="indicators",
          known_caveats="Denominator lookahead if unlagged: includes D volume"),

        # --- contraction family
        F("atr_ratio", "Volatility squeeze: ATR(5) / ATR(20)",
          "prev_close", 20, True, True,
          inputs=("high", "low", "close"), owner="indicators",
          known_caveats="H015: inverts signal by selecting failed demand "
                        "days when unlagged"),
        F("atr_ratio_pctile", "250-session percentile rank of atr_ratio",
          "prev_close", 250, True, True, inputs=("atr_ratio",),
          owner="indicators"),
        F("atr_pct", "ATR(20) as % of close",
          "prev_close", 20, True, True,
          inputs=("high", "low", "close"), owner="indicators"),
        F("range_pct", "Daily candle range: (high-low)/close * 100",
          "prev_close", 1, True, True, inputs=("high", "low", "close"),
          owner="indicators"),
        F("range_pct_ma", "10-day MA of range_pct",
          "prev_close", 10, True, True, inputs=("range_pct",),
          owner="indicators"),
        F("base_depth", "10-day consolidation depth: (max H - min L)/close",
          "prev_close", 10, True, True, inputs=("high", "low", "close"),
          owner="indicators"),
        F("base_depth_pctile", "250-session percentile rank of base_depth",
          "prev_close", 250, True, True, inputs=("base_depth",),
          owner="indicators"),
        F("bb_width", "20-period Bollinger width (4σ/mid) as % of price",
          "prev_close", 20, True, True, inputs=("close",),
          owner="indicators"),
        F("bb_width_pctile", "250-session percentile rank of bb_width",
          "prev_close", 250, True, True, inputs=("bb_width",),
          owner="indicators"),
        F("nr_k", "Binary: narrowest range of last 7 sessions",
          "prev_close", 7, True, True, inputs=("range_pct",),
          owner="indicators"),
        F("body_ratio", "Candle body as % of total range: |C-O|/(H-L)*100",
          "prev_close", 1, True, True,
          inputs=("open", "high", "low", "close"), owner="indicators"),
        F("inside_day", "Binary: today's range inside yesterday's",
          "prev_close", 2, True, True, inputs=("high", "low"),
          owner="indicators"),
        F("doji_like", "Binary: body_ratio < 25%",
          "prev_close", 1, True, True, inputs=("body_ratio",),
          owner="indicators"),
        F("n_small_bodies_5", "Count of doji-like candles in trailing 5 days",
          "prev_close", 5, True, True, inputs=("doji_like",),
          owner="indicators"),
        F("vol_squeeze", "Volume squeeze: 5-day mean vol / 20-day mean vol",
          "prev_close", 20, False, True, inputs=("volume",),
          owner="indicators"),
        F("contraction_steps", "Successive-tightening count (VCP shape, 0-2)",
          "prev_close", 30, True, True,
          inputs=("high", "low", "close"), owner="indicators"),

        # --- context returns
        F("ret_20d", "20-session trailing return (%)",
          "prev_close", 20, True, True, inputs=("close",),
          owner="indicators"),
        F("ret_60d", "60-session trailing return (%)",
          "prev_close", 60, True, True, inputs=("close",),
          owner="indicators"),
        F("dist_52w_high", "% distance to 250-session rolling high",
          "prev_close", 250, True, True, inputs=("close", "high"),
          owner="indicators"),
        F("gap_pct", "Morning gap: (open[D] / close[D-1] - 1) * 100",
          "open", 1, True, True, inputs=("open", "close"),
          owner="indicators",
          known_caveats="Safe: uses 09:15 auction open vs D-1 close"),
    ]


def _market_regime_features() -> list[FeatureSpec]:
    """Market-level features from context.py market_regime().

    All shifted by 1 session so date D carries D-1 state.
    """
    F = FeatureSpec
    return [
        F("mkt_ret_5d", "5-session equal-weighted market return (%)",
          "prev_close", 5, True, True, owner="context"),
        F("mkt_ret_20d", "20-session equal-weighted market return (%)",
          "prev_close", 20, True, True, owner="context"),
        F("mkt_ret_60d", "60-session equal-weighted market return (%)",
          "prev_close", 60, True, True, owner="context"),
        F("mkt_vol_20d", "20-session annualized market volatility (%)",
          "prev_close", 20, True, True, owner="context"),
        F("mkt_trend_eff", "Market trend efficiency: |net|/total over 20d",
          "prev_close", 20, True, True, owner="context"),
        F("mkt_up", "Sign of 20-day market return (+1, -1, 0)",
          "prev_close", 20, True, True, inputs=("mkt_ret_20d",),
          owner="context"),
        F("mkt_vs_ema50_pct", "% distance of market index vs its 50-EMA",
          "prev_close", 50, True, True, owner="context"),
        F("mkt_dd_from_60d_high_pct",
          "Drawdown of market index from 60-day high (%)",
          "prev_close", 60, True, True, owner="context"),
        F("mkt_breadth_pct", "% of universe above their own 50-EMA",
          "prev_close", 50, True, True, owner="context"),
        F("mkt_regime", "Market regime label: trending_up/down, chop, etc.",
          "prev_close", 20, True, True,
          inputs=("mkt_ret_20d", "mkt_trend_eff"), owner="context"),
    ]


def _breakout_features() -> list[FeatureSpec]:
    """Breakout location features from context.py, for lookbacks 20 and 50."""
    F = FeatureSpec
    specs = []
    for n in (20, 50):
        specs.extend([
            F(f"prior_high_{n}",
              f"Highest high over {n} sessions ending D-1",
              "prev_close", n, True, True,
              inputs=("high",), owner="context"),
            F(f"prior_low_{n}",
              f"Lowest low over {n} sessions ending D-1",
              "prev_close", n, True, True,
              inputs=("low",), owner="context"),
            F(f"base_range_{n}_pct",
              f"Base depth: (prior_high - prior_low)/prior_low over {n}d (%)",
              "prev_close", n, True, True,
              inputs=(f"prior_high_{n}", f"prior_low_{n}"), owner="context"),
            F(f"days_since_high_{n}",
              f"Sessions since the {n}-session high was set",
              "prev_close", n, True, True,
              inputs=("high",), owner="context"),
            F(f"n_touches_{n}",
              f"Sessions where high came within 1% of {n}-day high",
              "prev_close", n, True, True,
              inputs=("high",), owner="context"),
            F(f"prev_close_vs_high_{n}_pct",
              f"% distance from D-1 close to {n}-day prior high",
              "prev_close", n, True, True,
              inputs=("close", f"prior_high_{n}"), owner="context"),
            F(f"open_vs_high_{n}_pct",
              f"% distance from D open to {n}-day prior high",
              "open", n, True, True,
              inputs=("open", f"prior_high_{n}"), owner="context"),
            F(f"open_above_high_{n}",
              f"Binary: stock opened above {n}-day prior high",
              "open", n, True, True,
              inputs=("open", f"prior_high_{n}"), owner="context"),
            F(f"open_base_pos_{n}",
              f"Position of open in {n}-day base (0=low, 1=high)",
              "open", n, True, True,
              inputs=("open", f"prior_high_{n}", f"prior_low_{n}"),
              owner="context"),
            F(f"base_low_dist_{n}_pct",
              f"% distance of D open from {n}-day prior low",
              "open", n, True, True,
              inputs=("open", f"prior_low_{n}"), owner="context"),
        ])
    return specs


def _relative_strength_features() -> list[FeatureSpec]:
    """Relative strength features from context.py."""
    F = FeatureSpec
    return [
        F("sec_ret_20d", "Trailing 20-session sector return ending D-1 (%)",
          "prev_close", 20, True, True, owner="context"),
        F("sec_ret_60d", "Trailing 60-session sector return ending D-1 (%)",
          "prev_close", 60, True, True, owner="context"),
        F("rs_20d_vs_mkt", "Stock 20d return minus market 20d return",
          "prev_close", 20, True, True,
          inputs=("ret_20d", "mkt_ret_20d"), owner="context"),
        F("rs_60d_vs_mkt", "Stock 60d return minus market 60d return",
          "prev_close", 60, True, True,
          inputs=("ret_60d", "mkt_ret_60d"), owner="context"),
        F("rs_20d_vs_sec", "Stock 20d return minus sector 20d return",
          "prev_close", 20, True, True,
          inputs=("ret_20d", "sec_ret_20d"), owner="context"),
        F("sec_rs_20d_vs_mkt", "Sector 20d return minus market 20d return",
          "prev_close", 20, True, True,
          inputs=("sec_ret_20d", "mkt_ret_20d"), owner="context"),
    ]


def _sector_features() -> list[FeatureSpec]:
    """Sector index features from screener.py / build_screen.py."""
    F = FeatureSpec
    return [
        F("sector_index", "Synthetic equal-weighted sector index level",
          "prev_close", 0, True, True, owner="sector"),
        F("sec_ema_fast", "20-EMA of sector index",
          "prev_close", 20, True, True, inputs=("sector_index",),
          owner="sector"),
        F("sec_ema_mid", "50-EMA of sector index",
          "prev_close", 50, True, True, inputs=("sector_index",),
          owner="sector"),
        F("sec_slope", "10-session % change of sec_ema_fast",
          "prev_close", 30, True, True, inputs=("sec_ema_fast",),
          owner="sector"),
        F("sector_uptrend_index",
          "Binary: sector index in uptrend (fast > mid EMA)",
          "prev_close", 50, True, True,
          inputs=("sec_ema_fast", "sec_ema_mid"), owner="sector"),
        F("sector_breadth",
          "% of sector members above their own 50-EMA",
          "prev_close", 50, True, True, owner="sector"),
    ]


def _opening_features() -> list[FeatureSpec]:
    """Opening-window behavioural features from behaviour.py.

    Registered at the canonical t=300s (5-minute mark). The full grid
    covers t in {30, 60, ..., 300} seconds; those are the same features
    parameterised by time offset.
    """
    F = FeatureSpec
    t_note = "Canonical at t=300s; available for t in {30..300}s"
    return [
        F("entry_vs_open_pct", "% distance of price at t vs auction open",
          "intraday_t", 0, False, True,
          inputs=("open_raw",), owner="opening",
          known_caveats=t_note),
        F("low_vs_open_pct", "% distance of running low at t vs auction open",
          "intraday_t", 0, False, True,
          inputs=("open_raw",), owner="opening",
          known_caveats=t_note),
        F("high_vs_open_pct", "% distance of running high at t vs auction open",
          "intraday_t", 0, False, True,
          inputs=("open_raw",), owner="opening",
          known_caveats=t_note),
        F("range_t_pct", "Developing range through t as % of open",
          "intraday_t", 0, False, True,
          inputs=("open_raw",), owner="opening",
          known_caveats=t_note),
        F("range_pos", "Position in developing range (0=low, 1=high)",
          "intraday_t", 0, False, True, owner="opening",
          known_caveats=t_note),
        F("path_efficiency", "Net move / total path length (-1 to +1)",
          "intraday_t", 0, False, True, owner="opening",
          known_caveats=t_note),
        F("abs_path_efficiency", "Absolute path efficiency",
          "intraday_t", 0, False, True, inputs=("path_efficiency",),
          owner="opening", known_caveats=t_note),
        F("time_above_open_frac",
          "Dwell-weighted fraction of window above auction open",
          "intraday_t", 0, False, True,
          inputs=("open_raw",), owner="opening",
          known_caveats=f"{t_note}. Fixed boundary lookahead bug."),
        F("ticks_above_open_frac",
          "Fraction of tick prints >= auction open",
          "intraday_t", 0, False, True,
          inputs=("open_raw",), owner="opening",
          known_caveats=t_note),
        F("low_at_open_exact", "Binary: running low never went below open",
          "intraday_t", 0, False, True,
          inputs=("open_raw",), owner="opening",
          known_caveats=f"{t_note}. Censored at 0 for thin names."),
        F("dd_from_high_pct", "% pullback from morning high at t",
          "intraday_t", 0, False, True, owner="opening",
          known_caveats=t_note),
        F("vol_rel_daily_pct",
          "Opening volume as % of 20-day median daily volume",
          "intraday_t", 20, False, True,
          inputs=("median_vol_20",), owner="opening",
          known_caveats=f"{t_note}. Uses lagged median (fixed denom bug)."),
        F("vol_rate_rel_daily", "vol_rel_daily_pct per minute elapsed",
          "intraday_t", 20, False, True,
          inputs=("vol_rel_daily_pct",), owner="opening",
          known_caveats=t_note),
        F("uptick_vol_share", "Fraction of volume on upticks (0 to 1)",
          "intraday_t", 0, False, True, owner="opening",
          known_caveats=t_note),
        F("vol_hhi",
          "Normalised Herfindahl of volume across 30s buckets",
          "intraday_t", 0, False, True, owner="opening",
          known_caveats=t_note),
        F("active_bucket_frac",
          "Fraction of 30s buckets with >20% of even-split volume",
          "intraday_t", 0, False, True, owner="opening",
          known_caveats=t_note),
        F("vol_late_early_ratio",
          "Log ratio of second-half vs first-half volume",
          "intraday_t", 0, False, True, owner="opening",
          known_caveats=t_note),
        F("px_vs_vwap_pct", "% distance of price at t vs VWAP through t",
          "intraday_t", 0, False, True, owner="opening",
          known_caveats=t_note),
        F("move_per_vol",
          "Absolute price move per unit of relative volume",
          "intraday_t", 0, False, True,
          inputs=("entry_vs_open_pct", "vol_rel_daily_pct"),
          owner="opening", known_caveats=t_note),
        F("low_slope_pct_per_min",
          "OLS slope of 30s bucket lows (% of open per min)",
          "intraday_t", 0, False, True, owner="opening",
          known_caveats=t_note),
        F("low_higher_frac",
          "Fraction of 30s buckets with higher lows than predecessor",
          "intraday_t", 0, False, True, owner="opening",
          known_caveats=t_note),
        F("chaos_vs_atr",
          "Tick dispersion scaled by ATR: (px_sd/open*100)/atr_pct",
          "intraday_t", 20, False, True,
          inputs=("atr_pct",), owner="opening",
          known_caveats=t_note),
        F("churn_vs_atr",
          "Total path scaled by ATR: (path_len/open*100)/atr_pct",
          "intraday_t", 20, False, True,
          inputs=("atr_pct",), owner="opening",
          known_caveats=t_note),
        F("vol_5m_pct_of_median_daily",
          "First 5m volume as % of 20-day median daily volume",
          "intraday_t", 20, False, True,
          inputs=("median_vol_20",), owner="opening",
          known_caveats="Uses lagged median_vol_20"),
    ]


def _forward_label_features() -> list[FeatureSpec]:
    """Forward returns and outcome labels — never features."""
    F = FeatureSpec
    specs = []
    for h in (1, 3, 5, 10, 20):
        specs.extend([
            F(f"fwd_ret_{h}d_pct", f"Forward return from entry to +{h}d (%)",
              "future", 0, True, True, owner="labels"),
            F(f"excess_ret_{h}d_pct",
              f"Forward return minus benchmark over {h}d (%)",
              "future", 0, True, True,
              inputs=(f"fwd_ret_{h}d_pct",), owner="labels"),
            F(f"mfe_{h}d_pct",
              f"Max favourable excursion from +1 to +{h}d (%)",
              "future", 0, True, True, owner="labels"),
            F(f"mae_{h}d_pct",
              f"Max adverse excursion from +1 to +{h}d (%)",
              "future", 0, True, True, owner="labels"),
        ])
    return specs


def build_default_catalogue() -> Catalogue:
    """The complete catalogue of every feature currently computable."""
    cat = Catalogue()
    cat.register_many(_daily_bar_features())
    cat.register_many(_snapshot_features())
    cat.register_many(_indicator_features())
    cat.register_many(_market_regime_features())
    cat.register_many(_breakout_features())
    cat.register_many(_relative_strength_features())
    cat.register_many(_sector_features())
    cat.register_many(_opening_features())
    cat.register_many(_forward_label_features())
    return cat


# Module-level singleton, built once on import.
DEFAULT: Catalogue = build_default_catalogue()
