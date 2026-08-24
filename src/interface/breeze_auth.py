"""Local-browser Breeze authentication support for the primary web app."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import struct
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from typing import Mapping
from urllib.parse import urlparse

from ..core import config

CALLBACK_PATH = "/auth/breeze/callback"
LOGIN_PATH = "/auth/breeze/login"
COOKIE_NAME = "brickbreak_breeze_login"


class BreezeAuthError(RuntimeError):
    pass


class PendingLogins:
    """One-use login intents, kept only for this local server process."""

    def __init__(self, ttl_s: float = 600.0):
        self.ttl_s = ttl_s
        self._items: dict[str, tuple[float, str | None]] = {}
        self._lock = threading.Lock()

    def begin(self, opener_origin: str | None = None) -> str:
        now = time.monotonic()
        nonce = secrets.token_urlsafe(24)
        with self._lock:
            self._items = {
                key: item for key, item in self._items.items()
                if item[0] > now
            }
            self._items[nonce] = (now + self.ttl_s, opener_origin)
        return nonce

    def consume_cookie(self, cookie_header: str | None) -> tuple[bool, str | None]:
        if not cookie_header:
            return False, None
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
        except Exception:
            return False, None
        morsel = cookie.get(COOKIE_NAME)
        if morsel is None:
            return False, None
        nonce = morsel.value
        now = time.monotonic()
        with self._lock:
            item = self._items.pop(nonce, None)
        if item is None or item[0] <= now:
            return False, None
        return True, item[1]

    def consume_latest(self) -> tuple[bool, str | None]:
        """Consume the newest intent when a cross-site POST omits Lax cookies.

        ICICI's form POST is a top-level cross-site POST, for which browsers do
        not send ``SameSite=Lax`` cookies.  The server is loopback-only, so an
        unexpired intent plus successful Breeze token verification is the
        fallback proof that this callback belongs to a login just initiated
        from Settings.
        """
        now = time.monotonic()
        with self._lock:
            live = {key: item for key, item in self._items.items()
                    if item[0] > now}
            self._items = live
            if not live:
                return False, None
            nonce = max(live, key=lambda key: live[key][0])
            _, opener_origin = self._items.pop(nonce)
        return True, opener_origin


PENDING_LOGINS = PendingLogins()


def callback_url(port: int) -> str:
    return f"http://127.0.0.1:{port}{CALLBACK_PATH}"


def login_url(port: int) -> str:
    return f"http://127.0.0.1:{port}{LOGIN_PATH}"


def safe_local_origin(value: str | None) -> str | None:
    """Accept only an HTTP loopback origin for popup completion messages."""
    if not value:
        return None
    parsed = urlparse(value)
    if (parsed.scheme != "http" or parsed.hostname not in
            {"127.0.0.1", "localhost", "::1"} or not parsed.netloc):
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def settings_payload(port: int) -> dict:
    totp_configured = bool(config.load_breeze_totp_secret())
    try:
        creds = config.load_credentials(require_session=False)
    except config.ConfigError as exc:
        return {
            "configured": False,
            "has_session_token": False,
            "session_refreshed_at": None,
            "totp_configured": totp_configured,
            "callback_url": callback_url(port),
            "login_path": LOGIN_PATH,
            "login_url": login_url(port),
            "error": str(exc),
        }
    return {
        "configured": True,
        "has_session_token": bool(creds.session_token),
        "session_refreshed_at": (
            config.load_breeze_session_refreshed_at()
            if creds.session_token else None
        ),
        "totp_configured": totp_configured,
        "callback_url": callback_url(port),
        "login_path": LOGIN_PATH,
        "login_url": login_url(port),
        "error": None,
    }


def generate_totp(
    secret: str,
    now: float | None = None,
    period: int = 30,
    digits: int = 6,
) -> dict:
    """Generate one RFC 6238 SHA-1 code from a Base32 authenticator seed."""
    if period <= 0 or not 6 <= digits <= 8:
        raise BreezeAuthError("Invalid TOTP configuration.")
    normalized = "".join(secret.split()).upper()
    if not normalized:
        raise BreezeAuthError("BREEZE_TOTP_SECRET is empty.")
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    try:
        key = base64.b32decode(normalized + padding, casefold=True)
    except (ValueError, binascii.Error) as exc:
        raise BreezeAuthError(
            "BREEZE_TOTP_SECRET must be a valid Base32 authenticator seed."
        ) from exc

    timestamp = time.time() if now is None else float(now)
    counter = int(timestamp // period)
    digest = hmac.new(
        key, struct.pack(">Q", counter), hashlib.sha1,
    ).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    code = str(binary % (10 ** digits)).zfill(digits)
    expires_ts = (counter + 1) * period
    return {
        "code": code,
        "period_seconds": period,
        "valid_for_seconds": max(1, int(expires_ts - timestamp)),
        "expires_at": datetime.fromtimestamp(
            expires_ts, tz=timezone.utc,
        ).isoformat(),
    }


def totp_payload() -> dict:
    secret = config.load_breeze_totp_secret()
    if not secret:
        raise BreezeAuthError(
            "Add BREEZE_TOTP_SECRET to .env and restart the server."
        )
    return generate_totp(secret)


def extract_session_token(query: Mapping[str, list[str]]) -> str | None:
    accepted = {"apisession", "api_session", "session_token"}
    for key, values in query.items():
        if key.lower() in accepted and values:
            token = values[0].strip()
            if token:
                return token
    return None


def login_cookie(nonce: str) -> str:
    return (
        f"{COOKIE_NAME}={nonce}; Path=/auth/breeze; HttpOnly; "
        "SameSite=Lax; Max-Age=600"
    )


def clear_login_cookie() -> str:
    return (
        f"{COOKIE_NAME}=; Path=/auth/breeze; HttpOnly; "
        "SameSite=Lax; Max-Age=0"
    )


def validate_session_token(
    creds: config.BreezeCredentials, token: str,
) -> None:
    """Ask Breeze customer-details to verify the callback token.

    ``generate_session`` in breeze-connect 1.0.69 only configures the SDK and
    returns ``None``; it does not prove the token works.  The authenticated
    customer-details call is therefore the actual acceptance check.
    """
    try:
        # Lazy by design: importing breeze-connect downloads its security
        # master, so an ordinary dashboard import must remain offline-safe.
        from ..research_data.sources.breeze import BreezeClient

        candidate = replace(creds, session_token=token)
        client = BreezeClient(candidate)
        client.authenticate()
        response = client.breeze.get_customer_details(api_session=token)
    except Exception as exc:
        raise BreezeAuthError(
            f"Unable to verify the Breeze session ({type(exc).__name__})."
        ) from exc

    if not isinstance(response, dict):
        raise BreezeAuthError("Breeze did not return a customer-details response.")
    error = response.get("Error")
    if error or response.get("Success") is None:
        raise BreezeAuthError("Breeze rejected the session token.")
