"""Thin, instrumented wrapper around the Breeze SDK.

Deliberately thin: it authenticates, forwards historical-data requests, and
measures every call. Measurement is the point of this spike, so each call is
timed and appended to data/metadata/api_calls.jsonl regardless of outcome.

Interval support (read out of breeze_connect 1.0.69's own config, not the docs):
  v1 get_historical_data    : 1minute, 5minute, 30minute, 1day
  v2 get_historical_data_v2 : 1second, 1minute, 5minute, 30minute, 1day
So 1-second data is only reachable through the v2 endpoint.
"""
from __future__ import annotations

import json
import random
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

from ...core import config

V1_INTERVALS = ("1minute", "5minute", "30minute", "1day")
V2_INTERVALS = ("1second", "1minute", "5minute", "30minute", "1day")

# Breeze wants ISO-ish stamps with a literal .000Z suffix. It treats them as
# IST wall-clock despite the Z; that assumption is tested in validate_data.
TS_FMT = "%Y-%m-%dT%H:%M:%S.000Z"
_CALL_LOG_LOCK = threading.Lock()


def _new_sdk_client(api_key: str):
    """Import the network-active SDK only when a Breeze client is requested.

    ``breeze_connect`` downloads its security master while its top-level module
    is imported.  Keeping that import out of module scope is therefore required
    for offline research-data imports, CLI help, and test collection.
    """
    try:
        from breeze_connect import BreezeConnect
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError(
            "Breeze access requires the optional 'breeze-connect' package"
        ) from exc
    return BreezeConnect(api_key=api_key)


def fmt_ts(dt: datetime) -> str:
    return dt.strftime(TS_FMT)


@dataclass
class CallResult:
    """One API call and everything we measured about it."""
    call_id: str
    endpoint: str          # "v1" | "v2"
    interval: str
    stock_code: str
    exchange_code: str
    from_date: str
    to_date: str
    started_at: str
    duration_s: float
    ok: bool
    status: Any = None
    error: str | None = None
    n_rows: int = 0
    attempts: int = 1
    raw: list[dict] | None = field(default=None, repr=False)
    response_keys: list[str] | None = None

    def log_record(self) -> dict:
        d = asdict(self)
        d.pop("raw", None)  # payload is stored separately as parquet
        return d


class BreezeClient:
    def __init__(self, creds: config.BreezeCredentials, min_interval_s: float = 0.6,
                 max_retries: int = 4):
        """min_interval_s throttles us client-side; we do not hammer the API.

        The throttle is lock-guarded because the fetchers run several worker
        threads: without the lock each thread reads a stale _last_call_at and
        the effective request rate silently overshoots the configured pace,
        which is exactly how we tripped Breeze's 429 limiter.
        """
        self.creds = creds
        self.min_interval_s = min_interval_s
        self.max_retries = max_retries
        self._throttle_lock = threading.Lock()
        self._last_call_at = 0.0
        self.breeze = _new_sdk_client(creds.api_key)
        self.session_error: str | None = None
        self.customer: dict | None = None

    # ---------------- auth ----------------

    def authenticate(self) -> dict:
        """Exchange the browser-obtained session token for an API session."""
        try:
            resp = self.breeze.generate_session(
                api_secret=self.creds.api_secret,
                session_token=self.creds.session_token,
            )
        except Exception as exc:  # SDK raises on bad/expired tokens
            self.session_error = f"{type(exc).__name__}: {exc}"
            raise
        self.customer = resp if isinstance(resp, dict) else {"raw": resp}
        return self.customer

    # ---------------- plumbing ----------------

    def _throttle(self) -> None:
        """Serialize pacing across threads: reserve the next slot under a lock."""
        with self._throttle_lock:
            now = time.monotonic()
            wait = self._last_call_at + self.min_interval_s - now
            if wait <= 0:
                self._last_call_at = now
                wait = 0.0
            else:
                self._last_call_at += self.min_interval_s
        if wait > 0:
            time.sleep(wait)

    @staticmethod
    def _is_rate_limited(status, error) -> bool:
        return status == 429 or (error is not None and "rate limit" in str(error).lower())

    @staticmethod
    def _extract_rows(resp: Any) -> tuple[list[dict], Any, str | None, list[str] | None]:
        """Breeze returns {"Success": [...], "Status": int, "Error": str|None}."""
        if resp is None:
            # The SDK catches its own exceptions and returns None, which in
            # practice means an unestablished/expired session.
            return [], None, "None response from SDK (usually an expired or missing session)", None
        if not isinstance(resp, dict):
            return [], None, f"non-dict response: {type(resp).__name__}", None
        keys = sorted(resp.keys())
        status = resp.get("Status")
        error = resp.get("Error") or None
        success = resp.get("Success")
        if isinstance(success, list):
            rows = [r for r in success if isinstance(r, dict)]
        elif isinstance(success, dict):
            rows = [success]
        else:
            rows = []
        return rows, status, error, keys

    def _call(
        self,
        endpoint: str,
        interval: str,
        stock_code: str,
        exchange_code: str,
        from_date: str,
        to_date: str,
        product_type: str | None = None,
    ) -> CallResult:
        fn = (
            self.breeze.get_historical_data_v2
            if endpoint == "v2"
            else self.breeze.get_historical_data
        )
        kwargs: dict[str, Any] = dict(
            interval=interval,
            from_date=from_date,
            to_date=to_date,
            stock_code=stock_code,
            exchange_code=exchange_code,
        )
        if product_type:
            kwargs["product_type"] = product_type

        started = datetime.now(timezone.utc)
        attempts = 0
        total_elapsed = 0.0
        while True:
            self._throttle()
            t0 = time.perf_counter()
            try:
                resp = fn(**kwargs)
                elapsed = time.perf_counter() - t0
                rows, status, error, keys = self._extract_rows(resp)
                ok = error is None and bool(rows)
            except Exception as exc:
                elapsed = time.perf_counter() - t0
                rows, status, error, keys, ok = [], None, f"{type(exc).__name__}: {exc}", None, False
            total_elapsed += elapsed
            attempts += 1
            # 429s are transient: back off and retry rather than silently
            # dropping the symbol/date from the dataset.
            if self._is_rate_limited(status, error) and attempts <= self.max_retries:
                backoff = (2 ** (attempts - 1)) * 1.5 + random.uniform(0, 0.5)
                time.sleep(backoff)
                continue
            break
        elapsed = total_elapsed

        result = CallResult(
            call_id=uuid.uuid4().hex[:12],
            endpoint=endpoint,
            interval=interval,
            stock_code=stock_code,
            exchange_code=exchange_code,
            from_date=from_date,
            to_date=to_date,
            started_at=started.isoformat(),
            duration_s=round(elapsed, 4),
            ok=ok,
            status=status,
            error=error,
            n_rows=len(rows),
            raw=rows,
            response_keys=keys,
        )
        result.attempts = attempts
        self._append_log(result)
        return result

    @staticmethod
    def _append_log(result: CallResult) -> None:
        config.ensure_dirs()
        with _CALL_LOG_LOCK:
            with config.CALL_LOG.open("a") as fh:
                fh.write(json.dumps(result.log_record()) + "\n")

    # ---------------- public surface ----------------

    def daily(self, stock_code: str, from_date: str, to_date: str,
              exchange_code: str = "NSE", endpoint: str = "v2") -> CallResult:
        pt = "cash" if endpoint == "v2" else None
        return self._call(endpoint, "1day", stock_code, exchange_code, from_date, to_date, pt)

    def minute(self, stock_code: str, from_date: str, to_date: str,
               exchange_code: str = "NSE", endpoint: str = "v2") -> CallResult:
        pt = "cash" if endpoint == "v2" else None
        return self._call(endpoint, "1minute", stock_code, exchange_code, from_date, to_date, pt)

    def second(self, stock_code: str, from_date: str, to_date: str,
               exchange_code: str = "NSE") -> CallResult:
        """1-second bars: v2 only."""
        return self._call("v2", "1second", stock_code, exchange_code, from_date, to_date, "cash")

    def raw(self, interval: str, stock_code: str, from_date: str, to_date: str,
            exchange_code: str = "NSE", endpoint: str = "v2") -> CallResult:
        pt = "cash" if endpoint == "v2" else None
        return self._call(endpoint, interval, stock_code, exchange_code, from_date, to_date, pt)
