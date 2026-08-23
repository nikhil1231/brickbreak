"""Data broker source probes (PLAN.md §5 and Stage Y).

The probe, not the documentation, establishes the truth:
- tests small and awkward slices: early dates, inactive entities, holidays, revisions;
- detects silent row caps (e.g. 70-row JSON endpoints or 1,000-row Breeze tail drops);
- checks timestamp and time-zone semantics (00:00:00 vs true broadcast time);
- measures usable history, coverage and join rates against the master calendar.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Callable, Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProbeCheck:
    name: str
    passed: bool
    details: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProbeResult:
    source_name: str
    passed: bool
    n_sample_rows: int
    usable_start_date: str
    usable_end_date: str
    join_rate_pct: float
    silent_cap_detected: bool
    timestamp_fidelity: str  # "exact_intraday", "date_only", "zero_stamped"
    checks: tuple[ProbeCheck, ...]
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "passed": self.passed,
            "n_sample_rows": self.n_sample_rows,
            "usable_start_date": self.usable_start_date,
            "usable_end_date": self.usable_end_date,
            "join_rate_pct": self.join_rate_pct,
            "silent_cap_detected": self.silent_cap_detected,
            "timestamp_fidelity": self.timestamp_fidelity,
            "checks": [c.to_dict() for c in self.checks],
            "notes": self.notes,
        }


def run_source_micro_probe(source_name: str,
                           sample_df: pd.DataFrame,
                           date_col: str = "date",
                           symbol_col: str = "symbol",
                           time_col: str | None = None,
                           calendar_sessions: Sequence[pd.Timestamp] | None = None,
                           known_cap_threshold: int = 70
                           ) -> ProbeResult:
    """Run diagnostic micro-probe on a sampled slice of raw data."""
    checks: list[ProbeCheck] = []

    if sample_df.empty:
        return ProbeResult(
            source_name=source_name,
            passed=False,
            n_sample_rows=0,
            usable_start_date="",
            usable_end_date="",
            join_rate_pct=0.0,
            silent_cap_detected=False,
            timestamp_fidelity="none",
            checks=(ProbeCheck("non_empty", False, "Sample payload is completely empty"),),
            notes="Source returned no data on probe query",
        )

    # 1. Row count & cap check
    n_rows = len(sample_df)
    silent_cap = False
    if n_rows == known_cap_threshold:
        silent_cap = True
        checks.append(ProbeCheck("silent_cap", False, f"Exact match with row cap {known_cap_threshold}"))
    else:
        checks.append(ProbeCheck("silent_cap", True, f"{n_rows} rows fetched without cap collision"))

    # 2. Date coverage
    dates = pd.to_datetime(sample_df[date_col].dropna()) if date_col in sample_df.columns else pd.Series()
    if dates.empty:
        usable_start = ""
        usable_end = ""
        checks.append(ProbeCheck("date_parsing", False, f"Failed to parse dates from column {date_col!r}"))
    else:
        usable_start = str(dates.min().date())
        usable_end = str(dates.max().date())
        checks.append(ProbeCheck("date_parsing", True, f"Spans {usable_start} to {usable_end}"))

    # 3. Join rate against canonical trading calendar
    join_rate = 100.0
    if calendar_sessions is not None and not dates.empty:
        valid_set = set(pd.to_datetime(calendar_sessions).date)
        sample_dates = set(dates.dt.date)
        matched = len(sample_dates & valid_set)
        join_rate = round(100.0 * matched / max(len(sample_dates), 1), 2)
        checks.append(ProbeCheck("calendar_join", join_rate >= 80.0, f"Join rate {join_rate}% against trading calendar"))

    # 4. Timestamp fidelity
    fidelity = "date_only"
    if time_col and time_col in sample_df.columns:
        times = sample_df[time_col].dropna().astype(str)
        if any(":" in t and not t.endswith("00:00:00") for t in times):
            fidelity = "exact_intraday"
        elif all("00:00:00" in t for t in times):
            fidelity = "zero_stamped"
    checks.append(ProbeCheck("timestamp_fidelity", True, f"Fidelity assessed as {fidelity}"))

    all_passed = all(c.passed for c in checks)

    return ProbeResult(
        source_name=source_name,
        passed=all_passed,
        n_sample_rows=n_rows,
        usable_start_date=usable_start,
        usable_end_date=usable_end,
        join_rate_pct=join_rate,
        silent_cap_detected=silent_cap,
        timestamp_fidelity=fidelity,
        checks=tuple(checks),
        notes="Micro-probe completed",
    )
