"""Environment/config loading for the Breeze feasibility spike."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
NORMALIZED_DIR = DATA_DIR / "normalized"
METADATA_DIR = DATA_DIR / "metadata"

# Every API call this project makes is appended here. This file is the
# evidence base for the findings, so it is never overwritten.
CALL_LOG = METADATA_DIR / "api_calls.jsonl"

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


def ensure_dirs() -> None:
    for d in (RAW_DIR, NORMALIZED_DIR, METADATA_DIR):
        d.mkdir(parents=True, exist_ok=True)
