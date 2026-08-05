#!/usr/bin/env python3
"""Run gold-63 eval against a list of commits and append TSV results."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "evals/meta_legal/experiments/campaign_gold_gate.tsv"
LOG = REPO / "evals/meta_legal/experiments/log.jsonl"

# Baseline pre-campaign + progressive keeps (skip hollow 32f2d82; winner already known bad)
COMMITS = [
    "d8ef8f0",  # pre-campaign main tip (round3 speed) — may already be logged
    "313ba42",  # seed-first skip search if >=2 bodies
    "30fd4bf",  # harvest before LLM
    "6f0b019",  # rich>=3 early exit
    "659e73b",  # queries=2 budget=3s
    "5dd7b8f",  # skip search whenever seeds exist
    "eb14b91",  # rescue harvest
    "d6290f4",  # winner (already measured 0.77, re-check)
]


def sh(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=REPO, text=True, capture_output=True, **kw)


def analyze(exp_id: str) -> dict:
    rows = [
        json.loads(l)
        for l in LOG.read_text().splitlines()
        if l.strip()
    ]
    row = [r for r in rows if r.get("exp_id") == exp_id][-1]
    idx = json.loads((Path(row["dossier"]) / "index.json").read_text())
    by = Counter(l["cell_id"] for l in idx["laws"])
    cov = sum(1 for c in idx["cell_ids"] if by.get(c, 0) >= 1)
    no = sum(
        1
        for e in idx.get("errors") or []
        if "search returned no results" in (e.get("message") or "")
    )
    rich = empty = 0
    for law in idx["laws"]:
        p = Path(row["dossier"]) / law["path"]
        if not p.is_file():
            continue
        o = json.loads(p.read_text())
        if (o.get("excerpt") or "").strip():
            rich += 1
        else:
            empty += 1
    return {
        "elapsed": row["elapsed_sec"],
        "recall": row.get("recall"),
        "found": row.get("found"),
        "accepted": idx["accepted_count"],
        "cov": f"{cov}/{len(idx['cell_ids'])}",
        "rich": rich,
        "empty": empty,
        "no_res": no,
        "dossier": row["dossier"],
    }


def already_logged(exp_id: str) -> bool:
    if not LOG.is_file():
        return False
    for l in LOG.read_text().splitlines():
        if not l.strip():
            continue
        if json.loads(l).get("exp_id") == exp_id:
            return True
    return False


def main() -> int:
    os.environ.setdefault("LANGSMITH_TRACING", "false")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
    os.environ.setdefault("META_LEGAL_LLM_TIMEOUT_S", "45")

    if not OUT.exists():
        OUT.write_text(
            "commit\tsubject\telapsed\trecall\tfound\taccepted\tcov\trich\tempty\tno_res\n",
            encoding="utf-8",
        )

    start = REPO
    original = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    if original == "HEAD":
        original = "main"

    try:
        for c in COMMITS:
            short = sh(["git", "rev-parse", "--short", c]).stdout.strip()
            subj = sh(["git", "log", "-1", "--format=%s", c]).stdout.strip().replace("\t", " ")
            exp = f"exp_camp_{short}"
            print(f"\n===== GOLD63 {short} =====", flush=True)
            print(subj, flush=True)

            co = sh(["git", "checkout", "-q", c])
            if co.returncode != 0:
                print(co.stderr, file=sys.stderr)
                continue

            if not already_logged(exp):
                cmd = [
                    "uv",
                    "run",
                    "python",
                    "examples/meta_legal_eval_grid.py",
                    "--source",
                    "gold",
                    "--exp-id",
                    exp,
                    "--exp-name",
                    f"campaign_gold_{short}",
                    "--max-concurrency",
                    "100",
                    "--notes",
                    f"gold gate bisect {short}",
                ]
                proc = sh(cmd, timeout=900)
                Path(f"/tmp/gold_{short}.log").write_text(
                    (proc.stdout or "") + "\n" + (proc.stderr or ""), encoding="utf-8"
                )
                if proc.returncode != 0:
                    line = f"{short}\t{subj}\tFAIL\t\t\t\t\t\t\t\n"
                    OUT.open("a").write(line)
                    print("FAIL", proc.returncode, flush=True)
                    print((proc.stderr or proc.stdout)[-500:], flush=True)
                    continue
            else:
                print("reuse existing log row", flush=True)

            m = analyze(exp)
            line = (
                f"{short}\t{subj}\t{m['elapsed']}\t{m['recall']}\t{m['found']}\t"
                f"{m['accepted']}\t{m['cov']}\t{m['rich']}\t{m['empty']}\t{m['no_res']}\n"
            )
            OUT.open("a").write(line)
            print(line.strip(), flush=True)
            print(
                f"  PASS_RECALL={float(m['recall'] or 0) >= 0.98} dossier={m['dossier']}",
                flush=True,
            )
    finally:
        sh(["git", "checkout", "-q", original])

    print("\n===== SUMMARY =====", flush=True)
    print(OUT.read_text(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
