"""Content-addressed archive and text reader for NSE announcement attachments.

The announcement feed's ``details`` field is usually a title, not the filing.
H064 therefore needs the linked attachment, but experiments must not fetch URLs
or open arbitrary files themselves. This source module owns both operations and
exposes a URL-to-text map through :mod:`research_data.repository`.
"""
from __future__ import annotations

import hashlib
import io
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests
from pypdf import PdfReader

from ...core import config
from . import nse_api

ARCHIVE_DIR = config.RAW_DIR / "announcement_attachments"
MANIFEST_PATH = config.METADATA_DIR / "announcement_attachment_manifest.parquet"
MANIFEST_COLUMNS = [
    "url", "sha256", "n_bytes", "fetched_at", "status", "n_pages",
    "extract_status", "text",
]


def blob_path(sha: str, suffix: str = ".bin") -> Path:
    return ARCHIVE_DIR / sha[:2] / f"{sha}{suffix}"


def load_manifest() -> pd.DataFrame:
    if not MANIFEST_PATH.exists():
        return pd.DataFrame(columns=MANIFEST_COLUMNS)
    return pd.read_parquet(MANIFEST_PATH)


def _pdf_text(content: bytes) -> tuple[str, int, str]:
    try:
        reader = PdfReader(io.BytesIO(content), strict=False)
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:  # one malformed page must not lose the document
                pages.append("")
        text = "\n".join(pages).strip()
        return text, len(reader.pages), "ok" if text else "empty"
    except Exception as exc:  # noqa: BLE001 - status is research provenance
        return "", 0, f"error:{type(exc).__name__}"


def _extract(content: bytes, url: str) -> tuple[str, int, str]:
    if url.lower().split("?", 1)[0].endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                names = [n for n in zf.namelist() if n.lower().endswith(".pdf")]
                if not names:
                    return "", 0, "zip_without_pdf"
                texts, pages, statuses = [], 0, []
                for name in names:
                    text, n_pages, status = _pdf_text(zf.read(name))
                    texts.append(text); pages += n_pages; statuses.append(status)
                combined = "\n".join(t for t in texts if t).strip()
                return combined, pages, "ok" if combined else "+".join(statuses)
        except Exception as exc:  # noqa: BLE001
            return "", 0, f"error:{type(exc).__name__}"
    return _pdf_text(content)


def archive(urls: Iterable[str], throttle: float = 0.08,
            timeout: int = 90, verbose: bool = True) -> pd.DataFrame:
    """Fetch missing URLs, content-address the bytes and preserve extraction."""
    manifest = load_manifest()
    # A transient connection failure is a checkpoint, not a completed URL.
    # Keep successes and permanent 404s; retry transport/5xx failures on the
    # next invocation so a long archive run can resume after the host cools.
    if len(manifest):
        completed = manifest[manifest["status"].astype(str).isin(("ok", "http:404"))]
        seen = set(completed["url"].dropna().astype(str))
    else:
        seen = set()
    pending = [str(u) for u in dict.fromkeys(urls) if u and str(u) not in seen]
    rows = []
    for i, url in enumerate(pending, 1):
        rec = {
            "url": url, "sha256": None, "n_bytes": 0,
            "fetched_at": datetime.now(), "status": "ok", "n_pages": 0,
            "extract_status": "not_attempted", "text": "",
        }
        try:
            response = requests.get(url, headers=nse_api.HEADERS, timeout=timeout)
            if response.status_code != 200 or not response.content.strip():
                rec["status"] = f"http:{response.status_code}"
            else:
                content = response.content
                sha = hashlib.sha256(content).hexdigest()
                suffix = Path(url.split("?", 1)[0]).suffix.lower() or ".bin"
                path = blob_path(sha, suffix)
                if not path.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                text, pages, extract_status = _extract(content, url)
                rec.update({
                    "sha256": sha, "n_bytes": len(content), "text": text,
                    "n_pages": pages, "extract_status": extract_status,
                })
        except requests.RequestException as exc:
            rec["status"] = f"error:{type(exc).__name__}"
        rows.append(rec)
        if verbose and (i % 50 == 0 or i == len(pending)):
            usable = sum(bool(r["text"]) for r in rows)
            print(f"  attachments {i}/{len(pending)} text={usable}", flush=True)
        if i < len(pending):
            time.sleep(throttle)

    if rows:
        manifest = pd.concat([manifest, pd.DataFrame(rows)], ignore_index=True)
        manifest = manifest.drop_duplicates("url", keep="last")
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        manifest.to_parquet(MANIFEST_PATH, index=False)
    return manifest


def text_for_urls(urls: Iterable[str], max_chars: int = 6000) -> dict[str, str]:
    """Extracted cached text only; never performs network I/O."""
    wanted = {str(u) for u in urls if u}
    if not wanted:
        return {}
    manifest = load_manifest()
    if manifest.empty:
        return {}
    d = manifest[manifest["url"].astype(str).isin(wanted)]
    return {
        str(r.url): str(r.text or "")[:max_chars]
        for r in d.itertuples(index=False) if str(r.status) == "ok" and r.text
    }
