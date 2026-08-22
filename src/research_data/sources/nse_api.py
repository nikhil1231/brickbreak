"""The nseindia.com JSON/CSV API — cookie priming, throttling, raw caching.

`sources/nse.py` covers the *archive* host (`nsearchives.nseindia.com`), which
is a static file server: no cookies, no session, no rate limit worth the name.
This module covers the *website* host (`www.nseindia.com`), which is none of
those things and fails in ways that look like data rather than errors.

THREE THINGS THAT BITE, all measured against the live site on 2026-08-22:

  1. **Some endpoints truncate silently.** `bulk-block-short-deals` in JSON
     form returns exactly 70 rows for any range — one day or one year, no
     `total`, no cursor, `page`/`limit`/`start`/`length` all ignored — and the
     70 it keeps are the *earliest*. A caller that trusts it gets a plausible
     frame covering the first day of the window it asked for. The CSV form of
     the same endpoint is complete, so `csv=True` is the default here and the
     JSON form is reached only by asking for it.
  2. **Blocks are transient and look like content.** A rate-limited request
     returns 200-with-HTML or 503-with-HTML rather than 429. Anything that is
     not the content type we asked for is treated as a block: re-prime, back
     off, retry.
  3. **A dead route also answers 503**, which is indistinguishable from a
     block at the transport level. `/api/historical/bulk-deals` — the route
     every guide gives — is retired and 503s forever; the live route is
     `/api/historicalOR/bulk-block-short-deals`. Retrying through that is
     wasted work, so a persistent 503 is worth checking against the page's
     own network traffic before assuming it is rate limiting.

ON PRIMING, HONESTLY
Cookie priming is standard practice against this host and the existing
corporate-actions client does it, so it is kept here. But it was *not* what
fixed the deals endpoint, and this module does not claim otherwise: measured
on 2026-08-22 from this machine, the announcements, financial-results,
integrated-filing and CSV deals endpoints all answered a completely cold
session with no cookies at all, and priming with a deliberately mismatched
page changed nothing. The 503s that looked like a priming failure were the
dead route in note 3. Priming is retained as cheap insurance — NSE's tolerance
varies by IP reputation and over time, and the cost is two GETs per session —
not because it was demonstrated to be necessary. `area` mainly selects a
plausible `Referer`.

Raw payloads are cached verbatim under `data/raw/`, keyed by the request. That
is not a speed optimisation — NSE rewrites history (revised filings, restated
deals) and the cached bytes are the only evidence of what the site said on the
day we asked. Re-running a sync fetches only what is missing.
"""
from __future__ import annotations

import io
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import requests

from ...core import config

BASE = "https://www.nseindia.com"
HOME = f"{BASE}/"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "*/*", "Referer": HOME}
JSON_HEADERS = {**HEADERS, "Accept": "application/json, text/plain, */*"}
CSV_HEADERS = {**HEADERS, "Accept": "text/csv, */*"}

# The listing page each endpoint expects to have been reached from. Priming
# with the wrong one is a 503, so this mapping is load-bearing, not cosmetic.
PRIME_PAGES = {
    "deals": f"{BASE}/report-detail/display-bulk-and-block-deals",
    "announcements": f"{BASE}/companies-listing/corporate-filings-announcements",
    "results": f"{BASE}/companies-listing/corporate-filings-financial-results",
    "actions": f"{BASE}/companies-listing/corporate-filings-actions",
}


class NSEBlocked(RuntimeError):
    """The site answered, but with a challenge/error page instead of data."""


@dataclass
class Client:
    """A primed, throttled session against one area of the NSE website.

    `area` selects the priming page and the `Referer` header (see
    PRIME_PAGES). One client per area is the tidy arrangement rather than a
    measured requirement — see "ON PRIMING, HONESTLY" above.
    """

    area: str = "deals"
    throttle: float = 1.0
    max_retries: int = 3
    timeout: int = 90
    _session: requests.Session | None = field(default=None, init=False, repr=False)
    _last_call: float = field(default=0.0, init=False, repr=False)

    # ------------------------------------------------------------- priming

    def prime(self) -> requests.Session:
        """Open a fresh session and walk it to the page this area lives on.

        The home GET is expected to 403 from a scripted client; it still hands
        back the Akamai cookies the listing page sets against, so its status is
        deliberately not checked and neither is the listing page's.
        """
        s = requests.Session()
        try:
            s.get(HOME, headers=HEADERS, timeout=self.timeout)
        except requests.RequestException:
            pass
        page = PRIME_PAGES.get(self.area)
        if page:
            s.get(page, headers=HEADERS, timeout=self.timeout)
        self._session = s
        return s

    @property
    def session(self) -> requests.Session:
        return self._session or self.prime()

    def _referer(self) -> str:
        return PRIME_PAGES.get(self.area, HOME)

    def _wait(self) -> None:
        gap = time.monotonic() - self._last_call
        if gap < self.throttle:
            time.sleep(self.throttle - gap)
        self._last_call = time.monotonic()

    # -------------------------------------------------------------- fetching

    def get(self, url: str, params: dict, *, want: str = "json") -> bytes:
        """Fetch `url`, retrying through blocks, and return the raw body.

        `want` is the content type the caller expects ("json" or "csv"). A
        response of any other type is a block, not an empty result: NSE serves
        its challenge page with status 200 as readily as with 503, so the
        content type is the only reliable discriminator.
        """
        headers = {**(JSON_HEADERS if want == "json" else CSV_HEADERS),
                   "Referer": self._referer()}
        last = ""
        for attempt in range(self.max_retries):
            self._wait()
            try:
                r = self.session.get(url, params=params, headers=headers,
                                     timeout=self.timeout)
            except requests.RequestException as exc:
                last = f"{type(exc).__name__}: {exc}"
                self.prime()
                time.sleep(2 * (attempt + 1))
                continue
            ctype = (r.headers.get("content-type") or "").lower()
            if r.status_code == 200 and want in ctype:
                return r.content
            # An empty 200 is a real answer for a range with nothing in it;
            # the CSV endpoints return zero bytes rather than a header row.
            if r.status_code == 200 and not r.content.strip():
                return b""
            last = f"status={r.status_code} content-type={ctype!r}"
            self.prime()
            time.sleep(2 * (attempt + 1))
        raise NSEBlocked(f"{url} failed after {self.max_retries} attempts ({last})")

    def get_cached(self, path: Path, url: str, params: dict, *,
                   want: str = "json", force: bool = False) -> bytes:
        """`get`, but memoised on disk. The cached bytes are the evidence."""
        if path.exists() and not force:
            return path.read_bytes()
        body = self.get(url, params, want=want)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return body


# ----------------------------------------------------------------- decoding

def decode_json(body: bytes) -> list[dict]:
    """NSE returns either a bare list or `{"data": [...]}`, depending on route."""
    if not body.strip():
        return []
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        for key in ("data", "results", "rows"):
            if isinstance(payload.get(key), list):
                return payload[key]
        return []
    return payload if isinstance(payload, list) else []


def decode_csv(body: bytes) -> pd.DataFrame:
    """Read a CSV export, stripping the BOM and the padded header names.

    Every one of these exports ships a UTF-8 BOM and column names carrying a
    trailing space ("Date ", "Symbol "), and several carry cp1252 bytes inside
    company names, so the decode is latin-1 tolerant rather than strict.
    """
    if not body.strip():
        return pd.DataFrame()
    try:
        df = pd.read_csv(io.BytesIO(body), encoding="utf-8-sig")
    except UnicodeDecodeError:
        df = pd.read_csv(io.BytesIO(body), encoding="latin-1")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    df.columns = [str(c).strip() for c in df.columns]
    # object *and* str dtypes: pandas 3 splits them and select_dtypes
    # ("object") warns rather than covering both.
    for c in df.columns:
        if df[c].dtype == object or pd.api.types.is_string_dtype(df[c]):
            df[c] = df[c].astype(str).str.strip()
    return df


def raw_dir(name: str) -> Path:
    d = config.RAW_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    return d


__all__ = ["BASE", "Client", "NSEBlocked", "PRIME_PAGES", "decode_csv",
           "decode_json", "raw_dir"]
