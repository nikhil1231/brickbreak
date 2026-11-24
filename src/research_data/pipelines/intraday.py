"""Versioned, resumable intraday acquisition and dataset construction.

The remote worker is deliberately a byte collector.  A frozen request manifest
is created locally from a point-in-time universe, fetched remotely, and admitted
to a canonical dataset only after every response passes the cap, span, schema,
and timestamp checks in this module.

Experiments never import this module to read bars.  Their only door is
``research_data.frame.load_intraday_panel``.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ...core import config
from ..sources.breeze import BreezeClient
from . import storage


SCHEMA_VERSION = "intraday.v1"
SUPPORTED_INTERVALS = {"1minute": 1, "5minute": 5, "30minute": 30}
REQUEST_COLUMNS = (
    "request_id", "instrument_id", "symbol_asof", "from_session",
    "to_session", "from_ts", "to_ts", "interval", "dataset_version",
    "requested_sessions", "expected_max_rows",
)
BAR_COLUMNS = (
    "instrument_id", "symbol_asof", "session", "bar_start", "bar_end",
    "available_at", "open_raw", "high_raw", "low_raw", "close_raw",
    "volume_raw", "source", "source_interval", "request_id",
    "quality_flags", "dataset_version",
)
SETTLED_STATUSES = frozenset({"ok", "empty", "partial"})


class IntradayError(RuntimeError):
    pass


def acquisition_root(version: str) -> Path:
    _safe_token(version, "dataset version")
    return config.DATA_DIR / "intraday_acquisition" / version


def dataset_root(version: str, interval: str) -> Path:
    _safe_token(version, "dataset version")
    _validate_interval(interval)
    return (config.NORMALIZED_DIR / "intraday" / f"version={version}"
            / f"interval={interval}")


def dataset_manifest_path(version: str, interval: str) -> Path:
    return dataset_root(version, interval) / "dataset_manifest.json"


def _safe_token(value: str, label: str) -> None:
    if not value or not all(c.isalnum() or c in "._-" for c in value):
        raise IntradayError(f"unsafe {label}: {value!r}")


def _validate_interval(interval: str) -> None:
    if interval not in SUPPORTED_INTERVALS:
        raise IntradayError(
            f"unsupported interval {interval!r}; choose from "
            f"{sorted(SUPPORTED_INTERVALS)}")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def acquisition_code_fingerprint() -> str:
    """Content identity of the code that can alter acquired source bytes."""
    project = Path(__file__).resolve().parents[3]
    paths = (
        Path(__file__).resolve(),
        project / "src/research_data/sources/breeze.py",
        project / "src/research_data/pipelines/storage.py",
        project / "scripts/server_intraday_pull.py",
    )
    h = hashlib.sha256()
    for path in paths:
        if not path.exists():
            raise IntradayError(f"acquisition code file missing: {path}")
        h.update(str(path.relative_to(project)).encode())
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _normalise_sessions(values: Iterable[Any]) -> list[str]:
    sessions = pd.to_datetime(list(values), errors="raise")
    return sorted(set(pd.DatetimeIndex(sessions).strftime("%Y-%m-%d")))


def request_id(record: dict[str, Any]) -> str:
    identity = {
        key: record[key] for key in (
            "instrument_id", "symbol_asof", "from_ts", "to_ts", "interval",
            "dataset_version", "requested_sessions",
        )
    }
    return _sha256_bytes(_canonical_json(identity).encode())[:20]


def build_request_manifest(
    pairs: pd.DataFrame,
    *,
    version: str,
    interval: str = "5minute",
    all_sessions: Iterable[Any] | None = None,
    row_budget: int = 900,
) -> pd.DataFrame:
    """Build non-overlapping capped requests from PIT symbol/session pairs.

    ``pairs`` must already have point-in-time identity resolution.  Missing
    mappings belong in the separate coverage report and must not be passed as
    empty instrument IDs here.
    """
    _safe_token(version, "dataset version")
    _validate_interval(interval)
    required = {"instrument_id", "symbol_asof", "session"}
    if missing := required - set(pairs.columns):
        raise IntradayError(f"request pairs missing columns: {sorted(missing)}")
    if not 0 < row_budget < 1000:
        raise IntradayError("row_budget must be between 1 and 999")

    work = pairs[list(required)].copy()
    if work[list(required)].isna().any().any():
        raise IntradayError("request pairs contain missing identity/session values")
    work["instrument_id"] = work["instrument_id"].astype(str).str.strip()
    work["symbol_asof"] = work["symbol_asof"].astype(str).str.upper().str.strip()
    work["session"] = pd.to_datetime(work["session"], errors="raise").dt.normalize()
    work = work.drop_duplicates().sort_values(
        ["instrument_id", "symbol_asof", "session"])

    calendar = pd.DatetimeIndex(
        pd.to_datetime(list(all_sessions), errors="raise")).normalize().unique().sort_values() \
        if all_sessions is not None else pd.DatetimeIndex(work["session"].unique()).sort_values()
    bars_per_session = (375 + SUPPORTED_INTERVALS[interval] - 1) // SUPPORTED_INTERVALS[interval]

    records: list[dict[str, Any]] = []
    for (instrument_id, symbol), group in work.groupby(
            ["instrument_id", "symbol_asof"], sort=True):
        wanted = pd.DatetimeIndex(group["session"].unique()).sort_values()
        chunk: list[pd.Timestamp] = []

        def flush() -> None:
            if not chunk:
                return
            first, last = chunk[0], chunk[-1]
            requested = _normalise_sessions(chunk)
            record = {
                "instrument_id": instrument_id,
                "symbol_asof": symbol,
                "from_session": first.strftime("%Y-%m-%d"),
                "to_session": last.strftime("%Y-%m-%d"),
                "from_ts": f"{first.strftime('%Y-%m-%d')}T09:15:00.000Z",
                "to_ts": f"{last.strftime('%Y-%m-%d')}T15:30:00.000Z",
                "interval": interval,
                "dataset_version": version,
                "requested_sessions": _canonical_json(requested),
                "expected_max_rows": int(
                    calendar[(calendar >= first) & (calendar <= last)].size
                    * bars_per_session),
            }
            record["request_id"] = request_id(record)
            records.append(record)
            chunk.clear()

        for session in wanted:
            candidate = [*chunk, session]
            first, last = candidate[0], candidate[-1]
            n_market_sessions = calendar[(calendar >= first) & (calendar <= last)].size
            too_wide = n_market_sessions * bars_per_session > row_budget
            too_far = bool(chunk) and (session - chunk[-1]).days > 7
            if chunk and (too_wide or too_far):
                flush()
            chunk.append(session)
        flush()

    out = pd.DataFrame(records, columns=REQUEST_COLUMNS)
    validate_request_manifest(out)
    return out


def validate_request_manifest(frame: pd.DataFrame) -> None:
    missing = set(REQUEST_COLUMNS) - set(frame.columns)
    if missing:
        raise IntradayError(f"request manifest missing columns: {sorted(missing)}")
    if frame.empty:
        raise IntradayError("request manifest is empty")
    if frame["request_id"].duplicated().any():
        raise IntradayError("request IDs are not unique")
    if frame["dataset_version"].nunique() != 1:
        raise IntradayError("one request manifest may contain only one dataset version")
    if frame["interval"].nunique() != 1:
        raise IntradayError("one request manifest may contain only one interval")
    _safe_token(str(frame["dataset_version"].iloc[0]), "dataset version")
    _validate_interval(str(frame["interval"].iloc[0]))
    if (pd.to_numeric(frame["expected_max_rows"], errors="coerce") >= 1000).any():
        raise IntradayError("a request can reach the Breeze 1,000-row cap")
    if (pd.to_numeric(frame["expected_max_rows"], errors="coerce") <= 0).any():
        raise IntradayError("expected_max_rows must be positive")

    seen: set[tuple[str, str]] = set()
    for row in frame.itertuples(index=False):
        sessions = json.loads(row.requested_sessions)
        if not sessions:
            raise IntradayError(f"request {row.request_id} has no sessions")
        if sessions != _normalise_sessions(sessions):
            raise IntradayError(f"request {row.request_id} sessions are not canonical")
        expected = request_id(row._asdict())
        if row.request_id != expected:
            raise IntradayError(f"request ID/hash mismatch: {row.request_id}")
        for session in sessions:
            key = (str(row.instrument_id), session)
            if key in seen:
                raise IntradayError(f"overlapping instrument/session request: {key}")
            seen.add(key)


def manifest_fingerprint(frame: pd.DataFrame) -> str:
    validate_request_manifest(frame)
    records = frame[list(REQUEST_COLUMNS)].sort_values("request_id").to_dict("records")
    return _sha256_bytes(_canonical_json(records).encode())


def write_request_manifest(frame: pd.DataFrame, root: Path | None = None) -> tuple[Path, Path]:
    """Freeze a manifest and its independently verifiable metadata."""
    validate_request_manifest(frame)
    version = str(frame["dataset_version"].iloc[0])
    dest = root or acquisition_root(version)
    dest.mkdir(parents=True, exist_ok=True)
    parquet = dest / "requests.parquet"
    metadata = dest / "requests.json"
    if parquet.exists() or metadata.exists():
        existing = load_request_manifest(dest)
        if manifest_fingerprint(existing) != manifest_fingerprint(frame):
            raise IntradayError(f"a different frozen request manifest exists at {dest}")
        return parquet, metadata
    frame.to_parquet(parquet, index=False)
    meta = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_version": version,
        "interval": str(frame["interval"].iloc[0]),
        "n_requests": int(len(frame)),
        "n_instruments": int(frame["instrument_id"].nunique()),
        "n_symbol_asof": int(frame["symbol_asof"].nunique()),
        "manifest_hash": manifest_fingerprint(frame),
        "parquet_sha256": file_sha256(parquet),
        "acquisition_code_hash": acquisition_code_fingerprint(),
    }
    metadata.write_text(json.dumps(meta, indent=2) + "\n")
    return parquet, metadata


def load_request_manifest(root: Path) -> pd.DataFrame:
    parquet, metadata = root / "requests.parquet", root / "requests.json"
    if not parquet.exists() or not metadata.exists():
        raise IntradayError(f"frozen request manifest missing under {root}")
    meta = json.loads(metadata.read_text())
    if meta.get("schema_version") != SCHEMA_VERSION:
        raise IntradayError("request metadata schema version mismatch")
    if file_sha256(parquet) != meta.get("parquet_sha256"):
        raise IntradayError("request parquet hash does not match its metadata")
    frame = pd.read_parquet(parquet)
    if manifest_fingerprint(frame) != meta.get("manifest_hash"):
        raise IntradayError("request content hash does not match its metadata")
    return frame


def assert_acquisition_code(root: Path) -> str:
    metadata = root / "requests.json"
    if not metadata.exists():
        raise IntradayError(f"request metadata missing under {root}")
    expected = json.loads(metadata.read_text()).get("acquisition_code_hash")
    actual = acquisition_code_fingerprint()
    if not expected or expected != actual:
        raise IntradayError(
            f"remote acquisition code hash mismatch: expected={expected}, actual={actual}")
    return actual


def _attempt_path(root: Path, req_id: str) -> Path:
    return root / "attempts" / f"{req_id}.json"


def load_attempts(root: Path) -> pd.DataFrame:
    rows = []
    for path in sorted((root / "attempts").glob("*.json")):
        try:
            rows.append(json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError) as exc:
            raise IntradayError(f"invalid attempt artifact {path}: {exc}") from exc
    return pd.DataFrame(rows)


def pending_requests(frame: pd.DataFrame, root: Path) -> pd.DataFrame:
    attempts = load_attempts(root)
    if attempts.empty:
        return frame.copy()
    settled = set(attempts.loc[
        attempts["status"].isin(SETTLED_STATUSES), "request_id"].astype(str))
    return frame[~frame["request_id"].astype(str).isin(settled)].copy()


def _authentication_error(value: Any) -> bool:
    message = str(value or "").lower()
    return any(fragment in message for fragment in (
        "session key is expired", "sessionkey_expired", "expired session",
        "missing session", "authentication failed",
    ))


def _quality_flags(frame: pd.DataFrame) -> pd.Series:
    flags: list[str] = []
    for row in frame.itertuples(index=False):
        current: list[str] = []
        prices = [row.open_raw, row.high_raw, row.low_raw, row.close_raw]
        if any(pd.isna(x) or float(x) <= 0 for x in prices):
            current.append("invalid_price")
        elif float(row.high_raw) < max(float(row.open_raw), float(row.close_raw)) \
                or float(row.low_raw) > min(float(row.open_raw), float(row.close_raw)):
            current.append("invalid_ohlc")
        if pd.isna(row.volume_raw) or float(row.volume_raw) < 0:
            current.append("negative_volume")
        flags.append("|".join(current))
    return pd.Series(flags, index=frame.index, dtype="string")


def normalise_response(rows: list[dict], request: dict[str, Any]) -> pd.DataFrame:
    """Convert a Breeze payload to canonical, causal bar timestamps."""
    base = storage.normalize(rows, str(request["instrument_id"]),
                             str(request["symbol_asof"]))
    if base.empty:
        return pd.DataFrame(columns=BAR_COLUMNS)
    minutes = SUPPORTED_INTERVALS[str(request["interval"])]
    out = pd.DataFrame(index=base.index)
    out["instrument_id"] = base["security_id"].astype(str)
    out["symbol_asof"] = base["symbol"].astype(str)
    out["bar_start"] = pd.to_datetime(base["timestamp"], errors="coerce")
    out["bar_end"] = out["bar_start"] + pd.to_timedelta(minutes, unit="m")
    out["available_at"] = out["bar_end"]
    out["session"] = out["bar_start"].dt.normalize()
    for src, dest in (("open", "open_raw"), ("high", "high_raw"),
                      ("low", "low_raw"), ("close", "close_raw"),
                      ("volume", "volume_raw")):
        out[dest] = base[src].to_numpy()
    out["source"] = "breeze_v2"
    out["source_interval"] = str(request["interval"])
    out["request_id"] = str(request["request_id"])
    out["dataset_version"] = str(request["dataset_version"])
    out["quality_flags"] = _quality_flags(out)
    return out[list(BAR_COLUMNS)]


def _write_frame_once(frame: pd.DataFrame, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    frame.to_parquet(tmp, index=False)
    digest = file_sha256(tmp)
    if path.exists():
        existing = file_sha256(path)
        tmp.unlink()
        if existing != digest:
            raise IntradayError(f"immutable shard changed: {path}")
        return existing
    os.replace(tmp, path)
    return digest


def _write_json_once(value: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, sort_keys=True, default=str) + "\n"
    if path.exists():
        old = json.loads(path.read_text())
        if old.get("status") in SETTLED_STATUSES and old != value:
            raise IntradayError(f"settled attempt changed: {path}")
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def fetch_requests(
    requests: pd.DataFrame,
    client: BreezeClient,
    root: Path,
    *,
    workers: int = 4,
    max_calls: int | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Fetch pending requests and checkpoint every request independently."""
    validate_request_manifest(requests)
    todo = pending_requests(requests, root).sort_values("request_id")
    if max_calls is not None:
        todo = todo.head(max_calls)
    for directory in ("raw", "normalised", "session_markers", "attempts"):
        (root / directory).mkdir(parents=True, exist_ok=True)

    totals = {"attempted": 0, "ok": 0, "empty": 0, "errors": 0,
              "capped": 0, "partial": 0, "auth_failed": 0, "rows": 0}
    lock = threading.Lock()
    started = time.perf_counter()

    def one(row) -> tuple[dict[str, Any], list[dict] | None]:
        request = row._asdict()
        result = client.raw(
            str(row.interval), str(row.instrument_id), str(row.from_ts),
            str(row.to_ts), endpoint="v2")
        status = "ok"
        reason = ""
        raw = result.raw or []
        if result.error:
            reason = str(result.error)
            status = "auth_failed" if _authentication_error(reason) else "error"
        elif not raw:
            status = "empty"
        elif len(raw) >= 1000:
            status, reason = "capped", "response reached Breeze 1,000-row cap"

        canonical = normalise_response(raw, request) if raw else pd.DataFrame(columns=BAR_COLUMNS)
        requested_sessions = set(json.loads(str(row.requested_sessions)))
        regular_mask = (
            canonical["bar_start"].dt.time.ge(
                datetime.strptime("09:15", "%H:%M").time())
            & canonical["bar_end"].dt.time.le(
                datetime.strptime("15:30", "%H:%M").time())
        ) if not canonical.empty else pd.Series(False, index=canonical.index)
        session_markers = canonical.loc[~regular_mask].copy()
        if not session_markers.empty:
            times = session_markers["bar_start"].dt.time
            before_open = times < datetime.strptime("09:15", "%H:%M").time()
            close_marker = (
                (times >= datetime.strptime("15:30", "%H:%M").time())
                & (times < datetime.strptime("16:00", "%H:%M").time()))
            session_markers["quality_flags"] = np.select(
                [before_open, close_marker],
                ["preopen_marker", "terminal_close_marker"],
                default="special_session_bar")
        n_session_marker_rows = int(len(session_markers))
        observed_sessions = set(
            canonical["session"].dt.strftime("%Y-%m-%d")
        ) if not canonical.empty else set()
        canonical = canonical.loc[regular_mask].copy()
        if status in ("ok", "partial"):
            if canonical["bar_start"].isna().any():
                status, reason = "error", "unparseable timestamps"
            elif canonical.duplicated(["instrument_id", "bar_start"]).any():
                status, reason = "error", "duplicate instrument/bar timestamps"
            elif session_markers["bar_start"].isna().any():
                status, reason = "error", "unparseable marker timestamps"
            elif session_markers.duplicated(["instrument_id", "bar_start"]).any():
                status, reason = "error", "duplicate instrument/marker timestamps"
        missing_sessions = sorted(requested_sessions - observed_sessions)
        unexpected_sessions = sorted(observed_sessions - requested_sessions)
        if status == "ok" and unexpected_sessions:
            status, reason = (
                "error",
                f"response contains {len(unexpected_sessions)} unrequested session(s)",
            )
        elif status == "ok" and missing_sessions:
            status, reason = (
                "partial",
                f"response is missing {len(missing_sessions)} requested session(s)",
            )

        raw_hash = None
        if raw:
            raw_hash = _write_frame_once(
                pd.DataFrame(raw).astype(str), root / "raw" / f"{row.request_id}.parquet")
        normalised_hash = None
        session_markers_hash = None
        kept = canonical[
            canonical["session"].dt.strftime("%Y-%m-%d").isin(requested_sessions)
        ].copy() if not canonical.empty else canonical
        if status in ("ok", "partial"):
            normalised_hash = _write_frame_once(
                kept, root / "normalised" / f"{row.request_id}.parquet")
            kept_markers = session_markers[
                session_markers["session"].dt.strftime("%Y-%m-%d").isin(
                    requested_sessions)
            ].copy() if not session_markers.empty else session_markers
            if not kept_markers.empty:
                session_markers_hash = _write_frame_once(
                    kept_markers,
                    root / "session_markers" / f"{row.request_id}.parquet")

        attempt = {
            "request_id": str(row.request_id),
            "status": status,
            "error": reason,
            "source_status": result.status,
            "source_call_id": result.call_id,
            "n_source_rows": int(len(raw)),
            "n_kept_rows": int(len(kept)),
            "n_session_marker_rows_excluded": n_session_marker_rows,
            "missing_sessions": missing_sessions,
            "unexpected_sessions": unexpected_sessions,
            "raw_sha256": raw_hash,
            "normalised_sha256": normalised_hash,
            "session_markers_sha256": session_markers_hash,
            "attempted_at": datetime.now(timezone.utc).isoformat(),
            "duration_s": result.duration_s,
        }
        _write_json_once(attempt, _attempt_path(root, str(row.request_id)))
        return attempt, raw

    rows = iter(todo.itertuples(index=False))
    stop_for_auth = False
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = set()
        for _ in range(min(max(1, workers), len(todo))):
            futures.add(executor.submit(one, next(rows)))
        while futures:
            completed, futures = wait(futures, return_when=FIRST_COMPLETED)
            for future in completed:
                try:
                    attempt, _ = future.result()
                except Exception as exc:
                    attempt = {
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                        "n_kept_rows": 0,
                    }
                with lock:
                    totals["attempted"] += 1
                    status = attempt["status"]
                    if status in totals:
                        totals[status] += 1
                    else:
                        totals["errors"] += 1
                    totals["rows"] += int(attempt.get("n_kept_rows", 0))
                    snapshot = {**totals, "pending_before_run": int(len(todo)),
                                "elapsed_s": round(time.perf_counter() - started, 1)}
                    if progress:
                        progress(snapshot)
                stop_for_auth = stop_for_auth or status == "auth_failed"
                if not stop_for_auth:
                    try:
                        futures.add(executor.submit(one, next(rows)))
                    except StopIteration:
                        pass
            if stop_for_auth:
                for future in futures:
                    future.cancel()
                futures = {future for future in futures if not future.cancelled()}
    totals["elapsed_s"] = round(time.perf_counter() - started, 1)
    totals["remaining"] = int(len(pending_requests(requests, root)))
    return totals


def verify_acquisition(
    acquisition: Path,
    *,
    require_complete: bool = True,
) -> dict[str, Any]:
    """Verify every checkpoint and shard against the frozen request set."""
    requests = load_request_manifest(acquisition)
    attempts = load_attempts(acquisition)
    if attempts.empty:
        if require_complete:
            raise IntradayError("acquisition has no attempt checkpoints")
        return {"requests": int(len(requests)), "attempts": 0, "pending": int(len(requests))}
    required_attempt = {
        "request_id", "status", "n_source_rows", "n_kept_rows",
        "raw_sha256", "normalised_sha256",
    }
    if missing := required_attempt - set(attempts.columns):
        raise IntradayError(f"attempt checkpoints missing fields: {sorted(missing)}")
    if not ({"session_markers_sha256", "closing_markers_sha256"}
            & set(attempts.columns)):
        raise IntradayError("attempt checkpoints missing session-marker hash field")
    if attempts["request_id"].astype(str).duplicated().any():
        raise IntradayError("duplicate attempt checkpoint request IDs")
    known = set(requests["request_id"].astype(str))
    observed = set(attempts["request_id"].astype(str))
    if extra := observed - known:
        raise IntradayError(f"attempts exist for unknown requests: {sorted(extra)[:5]}")

    for attempt in attempts.to_dict("records"):
        req_id = str(attempt["request_id"])
        has_new_marker = (
            "session_markers_sha256" in attempt
            and not pd.isna(attempt.get("session_markers_sha256")))
        marker_field = (
            "session_markers_sha256" if has_new_marker
            or "closing_markers_sha256" not in attempt
            else "closing_markers_sha256")
        marker_directory = (
            "session_markers" if marker_field == "session_markers_sha256"
            else "closing_markers")
        for directory, field in (
            ("raw", "raw_sha256"),
            ("normalised", "normalised_sha256"),
            (marker_directory, marker_field),
        ):
            expected = attempt.get(field)
            if pd.isna(expected):
                expected = None
            path = acquisition / directory / f"{req_id}.parquet"
            if expected:
                if not path.exists() or file_sha256(path) != str(expected):
                    raise IntradayError(f"{directory} shard hash mismatch: {path}")
            elif path.exists():
                raise IntradayError(
                    f"unregistered {directory} shard exists for request {req_id}")
        raw_path = acquisition / "raw" / f"{req_id}.parquet"
        normalised_path = acquisition / "normalised" / f"{req_id}.parquet"
        if raw_path.exists() and len(pd.read_parquet(raw_path)) != int(attempt["n_source_rows"]):
            raise IntradayError(f"raw row count mismatch: {raw_path}")
        if normalised_path.exists() \
                and len(pd.read_parquet(normalised_path)) != int(attempt["n_kept_rows"]):
            raise IntradayError(f"normalised row count mismatch: {normalised_path}")
        if attempt["status"] in ("ok", "partial") and not normalised_path.exists():
            raise IntradayError(f"successful request has no normalised shard: {req_id}")

    settled = set(attempts.loc[
        attempts["status"].isin(SETTLED_STATUSES), "request_id"].astype(str))
    pending = known - settled
    bad = attempts[~attempts["status"].isin(SETTLED_STATUSES)]
    if require_complete and (pending or not bad.empty):
        raise IntradayError(
            f"acquisition incomplete: pending={len(pending)}, bad={len(bad)}")
    requested_sessions = int(sum(
        len(json.loads(value)) for value in requests["requested_sessions"]))
    missing_sessions = int(sum(
        len(value) if isinstance(value, list) else 0
        for value in attempts.get("missing_sessions", pd.Series(dtype=object))))
    return {
        "requests": int(len(requests)),
        "attempts": int(len(attempts)),
        "pending": int(len(pending)),
        "bad": int(len(bad)),
        "ok": int(attempts["status"].eq("ok").sum()),
        "empty": int(attempts["status"].eq("empty").sum()),
        "partial": int(attempts["status"].eq("partial").sum()),
        "source_rows": int(pd.to_numeric(
            attempts["n_source_rows"], errors="raise").sum()),
        "kept_rows": int(pd.to_numeric(
            attempts["n_kept_rows"], errors="raise").sum()),
        "requested_sessions": requested_sessions,
        "missing_sessions": missing_sessions,
        "session_coverage_pct": round(
            (requested_sessions - missing_sessions) / requested_sessions * 100.0, 6)
            if requested_sessions else 0.0,
    }


def build_dataset(
    acquisition: Path,
    *,
    split_version: str = "v1",
    split_hash: str,
    declared_failure_session_pct: float = 0.0,
) -> Path:
    """Consolidate verified shards into an immutable, versioned data product.

    `declared_failure_session_pct` is the share of requested symbol-sessions the
    caller is prepared to lose to hard source failures. It defaults to zero, so
    an incomplete acquisition is refused unless the caller states a tolerance.

    WHY A TOLERANCE EXISTS AT ALL, AND WHY IT IS NOT A FLAG
    Some Breeze responses are deterministically bad: duplicate bar timestamps,
    sessions outside the requested span, or a payload that reached the 1,000-row
    cap. The source repeats them byte-for-byte, so retrying is not a fix and
    waiting does not help. The choice is therefore between abandoning an
    otherwise complete panel and admitting it with the loss measured.

    Admitting it is only legitimate when the loss is *stated, bounded, and
    carried into the dataset manifest* — PLAN.md §11 forbids a failed request
    quietly leaving the evaluated population. So the failures are counted, the
    surviving coverage is recorded in `acquisition_report`, and a build that
    exceeds the stated tolerance raises rather than trimming the manifest to fit.
    """
    requests = load_request_manifest(acquisition)
    if declared_failure_session_pct <= 0:
        acquisition_report = verify_acquisition(acquisition, require_complete=True)
    else:
        acquisition_report = verify_acquisition(acquisition, require_complete=False)
        attempts = load_attempts(acquisition)
        settled = set(attempts.loc[
            attempts["status"].isin(SETTLED_STATUSES), "request_id"].astype(str))
        unsettled = requests.loc[~requests["request_id"].astype(str).isin(settled)]
        lost = int(sum(
            len(json.loads(value)) for value in unsettled["requested_sessions"]))
        total = int(sum(
            len(json.loads(value)) for value in requests["requested_sessions"]))
        lost_pct = (lost / total * 100.0) if total else 0.0
        if lost_pct > declared_failure_session_pct:
            raise IntradayError(
                f"hard source failures cost {lost_pct:.3f}% of requested "
                f"symbol-sessions, above the declared "
                f"{declared_failure_session_pct:.3f}% tolerance")
        failure_kinds = (
            attempts.loc[~attempts["status"].isin(SETTLED_STATUSES), "status"]
            .value_counts().to_dict() if not attempts.empty else {})
        acquisition_report = dict(acquisition_report) | {
            "declared_failure_session_pct": declared_failure_session_pct,
            "unsettled_requests": int(len(unsettled)),
            "unsettled_symbol_sessions": lost,
            "unsettled_symbol_session_pct": round(lost_pct, 6),
            "unsettled_symbols": sorted(
                unsettled["symbol_asof"].astype(str).unique().tolist()),
            "failure_status_counts": {
                str(key): int(value) for key, value in failure_kinds.items()},
        }

    version = str(requests["dataset_version"].iloc[0])
    interval = str(requests["interval"].iloc[0])
    destination = dataset_root(version, interval)
    if destination.exists():
        raise IntradayError(f"immutable dataset already exists: {destination}")
    staging = destination.with_name(f".{destination.name}.building-{uuid.uuid4().hex[:8]}")
    staging.mkdir(parents=True, exist_ok=False)
    writers: dict[int, pq.ParquetWriter] = {}
    output_paths: dict[int, Path] = {}
    rows = 0
    first_session: pd.Timestamp | None = None
    last_session: pd.Timestamp | None = None
    try:
        for req_id in requests.sort_values("request_id")["request_id"]:
            path = acquisition / "normalised" / f"{req_id}.parquet"
            if not path.exists():
                continue  # a valid empty response has no shard
            frame = pd.read_parquet(path)
            if tuple(frame.columns) != BAR_COLUMNS:
                raise IntradayError(f"canonical schema mismatch in {path}")
            frame = frame.sort_values(["session", "instrument_id", "bar_start"])
            if frame.duplicated(["instrument_id", "bar_start"]).any():
                raise IntradayError(f"duplicate bar in {path}")
            rows += len(frame)
            if not frame.empty:
                lo, hi = frame["session"].min(), frame["session"].max()
                first_session = lo if first_session is None else min(first_session, lo)
                last_session = hi if last_session is None else max(last_session, hi)
            for year, group in frame.groupby(frame["session"].dt.year):
                table = pa.Table.from_pandas(group.reset_index(drop=True), preserve_index=False)
                if int(year) not in writers:
                    output_paths[int(year)] = staging / f"part-{int(year)}.parquet"
                    writers[int(year)] = pq.ParquetWriter(
                        output_paths[int(year)], table.schema, compression="zstd")
                writers[int(year)].write_table(table)
        for writer in writers.values():
            writer.close()
        writers.clear()
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "status": "ready",
            "dataset_version": version,
            "base_interval": interval,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "request_manifest_hash": manifest_fingerprint(requests),
            "parent_split_version": split_version,
            "parent_split_hash": split_hash,
            "rows": int(rows),
            "acquisition_report": acquisition_report,
            "first_session": None if first_session is None else str(first_session.date()),
            "last_session": None if last_session is None else str(last_session.date()),
            "parts": {path.name: file_sha256(path) for path in output_paths.values()},
            "columns": list(BAR_COLUMNS),
            "outcome_columns": [],
        }
        (staging / "dataset_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, destination)
    except Exception:
        for writer in writers.values():
            writer.close()
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination


def load_dataset_manifest(version: str, interval: str) -> dict[str, Any]:
    path = dataset_manifest_path(version, interval)
    if not path.exists():
        raise IntradayError(f"intraday dataset manifest missing: {path}")
    manifest = json.loads(path.read_text())
    if manifest.get("status") != "ready":
        raise IntradayError(f"intraday dataset is not ready: {path}")
    if manifest.get("dataset_version") != version or manifest.get("base_interval") != interval:
        raise IntradayError("intraday dataset identity does not match requested identity")
    for name, digest in manifest.get("parts", {}).items():
        part = path.parent / name
        if not part.exists() or file_sha256(part) != digest:
            raise IntradayError(f"intraday dataset part hash mismatch: {part}")
    return manifest


__all__ = [
    "BAR_COLUMNS", "IntradayError", "REQUEST_COLUMNS", "SCHEMA_VERSION",
    "SUPPORTED_INTERVALS", "acquisition_code_fingerprint", "acquisition_root",
    "assert_acquisition_code", "build_dataset",
    "build_request_manifest", "dataset_manifest_path", "dataset_root",
    "fetch_requests", "file_sha256", "load_attempts", "load_dataset_manifest",
    "load_request_manifest", "manifest_fingerprint", "normalise_response",
    "pending_requests", "request_id", "validate_request_manifest",
    "verify_acquisition", "write_request_manifest",
]
