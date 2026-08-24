"""Environment/config loading for the Breeze feasibility spike."""
from __future__ import annotations

import os
import json
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
NORMALIZED_DIR = DATA_DIR / "normalized"
METADATA_DIR = DATA_DIR / "metadata"

# Every API call this project makes is appended here. This file is the
# evidence base for the findings, so it is never overwritten.
CALL_LOG = METADATA_DIR / "api_calls.jsonl"
BREEZE_AUTH_STATE = METADATA_DIR / "breeze_auth.json"

LOGIN_URL = "https://api.icicidirect.com/apiuser/login?api_key={api_key}"

IST = "Asia/Kolkata"


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class BreezeCredentials:
    api_key: str
    api_secret: str
    session_token: str | None

    @property
    def login_url(self) -> str:
        return LOGIN_URL.format(api_key=quote_plus(self.api_key))


def load_credentials(require_session: bool = True) -> BreezeCredentials:
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = (os.getenv("BREEZE_API_KEY") or "").strip()
    api_secret = (os.getenv("BREEZE_API_SECRET") or "").strip()
    session_token = (os.getenv("BREEZE_SESSION_TOKEN") or "").strip() or None

    missing = [n for n, v in (("BREEZE_API_KEY", api_key), ("BREEZE_API_SECRET", api_secret)) if not v]
    if missing:
        raise ConfigError(
            f"Missing env var(s): {', '.join(missing)}. Copy .env.example to .env and fill them in."
        )
    if require_session and not session_token:
        raise ConfigError(
            "BREEZE_SESSION_TOKEN is empty. Breeze session tokens expire daily.\n"
            "Run `python -m src.cli login-url`, log in, and paste the apisession value into .env."
        )
    return BreezeCredentials(api_key, api_secret, session_token)


def save_breeze_session_token(
    token: str,
    env_path: Path | None = None,
    metadata_path: Path | None = None,
) -> str:
    """Atomically update only ``BREEZE_SESSION_TOKEN`` in the project env file.

    The backend stays alive after the browser callback, so the process
    environment is updated as well as ``.env``.  Otherwise python-dotenv's
    default no-override behaviour would leave the server using yesterday's
    token until it was restarted.
    """
    value = token.strip()
    if not value or any(ch in value for ch in ("\n", "\r", "\0")):
        raise ConfigError("Breeze returned an invalid session token.")

    path = env_path or (PROJECT_ROOT / ".env")
    old = path.read_text() if path.exists() else ""
    pattern = re.compile(r"^\s*(?:export\s+)?BREEZE_SESSION_TOKEN\s*=.*$")
    lines = old.splitlines(keepends=True)
    replacement = f"BREEZE_SESSION_TOKEN={value}\n"
    updated: list[str] = []
    replaced = False
    for line in lines:
        if pattern.match(line.rstrip("\r\n")):
            if not replaced:
                updated.append(replacement)
                replaced = True
            # Drop duplicate definitions so a later stale value cannot win.
            continue
        updated.append(line)
    if not replaced:
        if updated and not updated[-1].endswith(("\n", "\r")):
            updated[-1] += "\n"
        updated.append(replacement)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
            delete=False,
        ) as fh:
            fh.writelines(updated)
            tmp_name = fh.name
        if path.exists():
            os.chmod(tmp_name, path.stat().st_mode)
        os.replace(tmp_name, path)
    finally:
        if tmp_name and os.path.exists(tmp_name):
            os.unlink(tmp_name)

    os.environ["BREEZE_SESSION_TOKEN"] = value
    refreshed_at = datetime.now(timezone.utc).isoformat()
    state_path = metadata_path or BREEZE_AUTH_STATE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_tmp: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=state_path.parent,
            prefix=f".{state_path.name}.", delete=False,
        ) as fh:
            json.dump({"session_refreshed_at": refreshed_at}, fh, indent=2)
            fh.write("\n")
            state_tmp = fh.name
        os.replace(state_tmp, state_path)
    finally:
        if state_tmp and os.path.exists(state_tmp):
            os.unlink(state_tmp)
    return refreshed_at


def load_breeze_session_refreshed_at(
    metadata_path: Path | None = None,
) -> str | None:
    """Return the persisted UTC refresh time, if the token came through UI."""
    path = metadata_path or BREEZE_AUTH_STATE
    try:
        value = json.loads(path.read_text()).get("session_refreshed_at")
        if not isinstance(value, str):
            return None
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def load_breeze_totp_secret() -> str | None:
    """Load the optional authenticator seed without exposing it to callers."""
    load_dotenv(PROJECT_ROOT / ".env")
    return (os.getenv("BREEZE_TOTP_SECRET") or "").strip() or None


def ensure_dirs() -> None:
    for d in (RAW_DIR, NORMALIZED_DIR, METADATA_DIR):
        d.mkdir(parents=True, exist_ok=True)
