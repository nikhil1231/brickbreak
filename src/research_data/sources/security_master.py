"""Download and parse ICICI's public NSE scrip master.

The master is served without authentication, which makes it a cheap way to
size the NSE universe and to map NSE ticker symbols to the ISEC "short name"
codes that the Breeze historical endpoints actually require.

Key columns (quotes and stray spaces in the header are cleaned on load):
  Token        - ISEC numeric token; "0" appears to mark inactive/delisted stubs
  ShortName    - ISEC internal code, e.g. RELIND. This is Breeze's `stock_code`.
  ExchangeCode - NSE trading symbol, e.g. RELIANCE.
  Series       - EQ / BE / SM / ... ; EQ is the normal cash-equity series.
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

from ...core import config

SECURITY_MASTER_URL = "https://directlink.icicidirect.com/MotherAppMaster/SecurityMaster.zip"
NSE_MEMBER = "NSEScripMaster.txt"
LOCAL_ZIP = config.METADATA_DIR / "SecurityMaster.zip"
LOCAL_PARQUET = config.METADATA_DIR / "nse_scrip_master.parquet"


@dataclass(frozen=True)
class Security:
    isec_code: str      # Breeze stock_code (ShortName)
    nse_symbol: str     # ExchangeCode
    company: str
    series: str
    token: str
    isin: str

    @property
    def looks_inactive(self) -> bool:
        """Token "0" is the only inactivity signal the master actually carries."""
        return self.token.strip() in ("", "0")


def download(force: bool = False) -> Path:
    config.ensure_dirs()
    if LOCAL_ZIP.exists() and not force:
        return LOCAL_ZIP
    resp = requests.get(SECURITY_MASTER_URL, timeout=180)
    resp.raise_for_status()
    LOCAL_ZIP.write_bytes(resp.content)
    return LOCAL_ZIP


def load(force_download: bool = False) -> pd.DataFrame:
    path = download(force=force_download)
    with zipfile.ZipFile(path) as zf:
        with zf.open(NSE_MEMBER) as fh:
            raw = fh.read()
    df = pd.read_csv(
        io.BytesIO(raw),
        skipinitialspace=True,
        dtype=str,
        keep_default_na=False,
        engine="python",
    )
    df.columns = [c.strip().strip('"').strip() for c in df.columns]
    for col in ("Token", "ShortName", "ExchangeCode", "CompanyName", "Series", "ISINCode"):
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
    return df


def to_securities(df: pd.DataFrame) -> list[Security]:
    return [
        Security(
            isec_code=r["ShortName"],
            nse_symbol=r["ExchangeCode"],
            company=r["CompanyName"],
            series=r["Series"],
            token=r["Token"],
            isin=r.get("ISINCode", ""),
        )
        for _, r in df.iterrows()
    ]


def resolve(df: pd.DataFrame, symbol: str) -> Security | None:
    """Look a security up by NSE symbol or ISEC short code (case-insensitive)."""
    s = symbol.strip().upper()
    hit = df[(df["ExchangeCode"].str.upper() == s) | (df["ShortName"].str.upper() == s)]
    if hit.empty:
        return None
    # Prefer an active EQ row when a code is ambiguous across series.
    active_eq = hit[(hit["Series"] == "EQ") & (hit["Token"] != "0")]
    row = (active_eq if not active_eq.empty else hit).iloc[0]
    return Security(
        isec_code=row["ShortName"],
        nse_symbol=row["ExchangeCode"],
        company=row["CompanyName"],
        series=row["Series"],
        token=row["Token"],
        isin=row.get("ISINCode", ""),
    )


def summarize(df: pd.DataFrame) -> dict:
    """Universe stats, plus which 'delisted' signals the master really provides."""
    eq = df[df["Series"] == "EQ"]
    inactive = df[df["Token"] == "0"]
    return {
        "source_url": SECURITY_MASTER_URL,
        "requires_auth": False,
        "total_rows": int(len(df)),
        "n_columns": int(len(df.columns)),
        "series_counts": df["Series"].value_counts().head(20).to_dict(),
        "eq_rows": int(len(eq)),
        "eq_active_token": int(len(eq[eq["Token"] != "0"])),
        "eq_token_zero": int(len(eq[eq["Token"] == "0"])),
        "token_zero_rows_total": int(len(inactive)),
        # These two fields exist in the schema but are empty in practice.
        "rows_with_delisting_date": int((df.get("DateOfDeListing", pd.Series(dtype=str)).str.strip() != "").sum())
        if "DateOfDeListing" in df.columns else None,
        "rows_with_delete_flag": int((df.get("DeleteFlag", pd.Series(dtype=str)).str.strip() != "").sum())
        if "DeleteFlag" in df.columns else None,
        "token_zero_examples": inactive[["ShortName", "ExchangeCode", "CompanyName"]]
        .head(15).to_dict("records"),
    }


def save_parquet(df: pd.DataFrame) -> Path:
    config.ensure_dirs()
    df.to_parquet(LOCAL_PARQUET, index=False)
    return LOCAL_PARQUET
