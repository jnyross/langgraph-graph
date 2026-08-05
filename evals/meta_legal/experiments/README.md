# meta_legal quality experiments

Track recall against `evals/meta_legal/gold_set.json` (100 instruments).

## Goal

Baseline smoke recall was ~0.02 (2/100). Target ≥0.95 on the full gold set.

## Runner

```bash
uv run python examples/meta_legal_eval_grid.py --dry-run
uv run python examples/meta_legal_eval_grid.py
```

The eval grid:

1. Loads gold **only** for unique `(jurisdiction, domain)` pairs (~63 cells).
2. Invokes the graph once with `explicit_cells` (not full cartesian).
3. Scores the dossier with `evals.meta_legal.score_recall`.
4. Appends one JSON line to `log.jsonl`.

Do **not** pass gold titles into the graph matcher as cheats.

## Log format (`log.jsonl`)

Each line:

```json
{
  "exp_id": "exp_001",
  "name": "seed_expansion",
  "recall": 0.02,
  "found": 2,
  "total": 100,
  "dossier": "data/dossiers/<run_id>",
  "elapsed_sec": 12.3,
  "notes": "…"
}
```

## Experiments

| id | name | note |
|----|------|------|
| exp_001 | seed_expansion | Expand official seed URLs / instruments for gold jurisdictions×domains |
