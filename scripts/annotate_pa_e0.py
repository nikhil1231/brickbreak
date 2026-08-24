#!/usr/bin/env python3
"""Run or resume one sealed model pass over the frozen PA7 E0 cases."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core import config  # noqa: E402
from src.discretionary.pa_annotations import run_model_pass  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, default=(
        config.METADATA_DIR / "research_store" / "price_action" / "pa7_e0_bundle"))
    parser.add_argument("--annotator", required=True)
    parser.add_argument("--provider", choices=("codex",), default="codex")
    parser.add_argument("--model", required=True)
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--timeout", type=int, default=300)
    options = parser.parse_args()
    result = run_model_pass(
        options.bundle, annotator=options.annotator, provider=options.provider,
        model=options.model, max_cases=options.max_cases,
        timeout_s=options.timeout,
        progress_fn=lambda index, total, case_id, ok, duration: print(
            f"[{index}/{total}] {case_id}: {'ok' if ok else 'failed'} "
            f"({duration:.1f}s)", flush=True))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "complete" else 4


if __name__ == "__main__":
    raise SystemExit(main())
