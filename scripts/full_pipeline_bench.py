#!/usr/bin/env python3
"""Full catalog×domain pipeline bench for autoresearch.

Runs the 1110-cell eval grid, scores gold recall, and emits:

  METRIC wall_s=<seconds>
  METRIC recall=<0-1>
  METRIC coverage=<0-1>
  METRIC accepted=<n>
  METRIC rich_pct=<0-1>
  METRIC no_results_rate=<0-1>
  METRIC cells=<n>

Quality gates (exit 2 if failed) — 0 quality loss vs exp_013 baseline:
  - recall >= 0.98
  - coverage >= 0.95  (cells with >=1 accepted)
  - no_results_rate <= 0.05
  - rich_pct >= 0.20  (accepted laws with non-empty excerpt)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Quality floors (exp_013: recall 1.0, cov 1.0, rich ~0.25, no_res 0)
MIN_RECALL = 0.98
MIN_COVERAGE = 0.95
MAX_NO_RESULTS_RATE = 0.05
MIN_RICH_PCT = 0.20


def main() -> int:
    os.chdir(REPO)
    os.environ.setdefault("LANGSMITH_TRACING", "false")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
    os.environ.setdefault("META_LEGAL_LLM_TIMEOUT_S", "30")
    os.environ.setdefault("META_LEGAL_MAX_CONCURRENCY", "100")

    exp_id = f"exp_ar_{uuid.uuid4().hex[:10]}"
    exp_name = "autoresearch_full_pipeline"
    log_path = REPO / "evals/meta_legal/experiments/log.jsonl"

    cmd = [
        "uv",
        "run",
        "python",
        "examples/meta_legal_eval_grid.py",
        "--source",
        "catalog",
        "--exp-id",
        exp_id,
        "--exp-name",
        exp_name,
        "--max-concurrency",
        os.environ.get("META_LEGAL_MAX_CONCURRENCY", "100"),
        "--notes",
        "autoresearch full-pipeline speed experiment",
    ]

    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=REPO, text=True, capture_output=True)
    wall = time.perf_counter() - t0

    # Always surface child output for debugging
    sys.stdout.write(proc.stdout or "")
    sys.stderr.write(proc.stderr or "")

    if proc.returncode != 0:
        print(f"METRIC wall_s={wall:.4f}")
        print("METRIC recall=0")
        print("METRIC coverage=0")
        print("METRIC accepted=0")
        print("METRIC rich_pct=0")
        print("METRIC no_results_rate=1")
        print("METRIC cells=0")
        print(f"PIPELINE_FAIL exit={proc.returncode}", file=sys.stderr)
        return 2

    # Parse log row
    rows = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    matches = [r for r in rows if r.get("exp_id") == exp_id]
    if not matches:
        print(f"METRIC wall_s={wall:.4f}")
        print("METRIC recall=0")
        print("METRIC coverage=0")
        print("METRIC accepted=0")
        print("METRIC rich_pct=0")
        print("METRIC no_results_rate=1")
        print("METRIC cells=0")
        print("PIPELINE_FAIL missing log row", file=sys.stderr)
        return 2

    row = matches[-1]
    dossier = Path(row["dossier"])
    idx = json.loads((dossier / "index.json").read_text(encoding="utf-8"))
    cells = idx.get("cell_ids") or []
    laws = idx.get("laws") or []
    by = Counter(law.get("cell_id") for law in laws)
    with1 = sum(1 for c in cells if by.get(c, 0) >= 1)
    coverage = (with1 / len(cells)) if cells else 0.0

    no_res_cells = {
        e.get("cell_id")
        for e in (idx.get("errors") or [])
        if "search returned no results" in (e.get("message") or "")
    }
    no_results_rate = (len(no_res_cells) / len(cells)) if cells else 1.0

    rich = empty = 0
    for law in laws:
        path = dossier / law["path"]
        if not path.is_file():
            continue
        obj = json.loads(path.read_text(encoding="utf-8"))
        if (obj.get("excerpt") or "").strip():
            rich += 1
        else:
            empty += 1
    rich_pct = rich / max(1, rich + empty)

    recall = float(row.get("recall") or 0.0)
    accepted = int(idx.get("accepted_count") or 0)
    # Prefer harness wall; fall back to logged elapsed
    wall_s = float(row.get("elapsed_sec") or wall)

    print(f"METRIC wall_s={wall_s:.4f}")
    print(f"METRIC recall={recall:.4f}")
    print(f"METRIC coverage={coverage:.4f}")
    print(f"METRIC accepted={accepted}")
    print(f"METRIC rich_pct={rich_pct:.4f}")
    print(f"METRIC no_results_rate={no_results_rate:.4f}")
    print(f"METRIC cells={len(cells)}")

    failures: list[str] = []
    if recall < MIN_RECALL:
        failures.append(f"recall {recall:.3f} < {MIN_RECALL}")
    if coverage < MIN_COVERAGE:
        failures.append(f"coverage {coverage:.3f} < {MIN_COVERAGE}")
    if no_results_rate > MAX_NO_RESULTS_RATE:
        failures.append(f"no_results_rate {no_results_rate:.3f} > {MAX_NO_RESULTS_RATE}")
    if rich_pct < MIN_RICH_PCT:
        failures.append(f"rich_pct {rich_pct:.3f} < {MIN_RICH_PCT}")

    if failures:
        print("QUALITY_FAIL " + "; ".join(failures), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
