# exp_001 — seed expansion

**Hypothesis:** Sparse seed URL / instrument coverage is the main recall bottleneck (~0.02). Expanding well-known official seeds for gold jurisdictions×domains should lift match rate without leaking gold titles into the graph.

**Method:**

- Eval grid builds `explicit_cells` from gold pairs only (jurisdiction name + domain_id).
- Graph plans those ~63 cells via `explicit_cells` (no full cartesian).
- Score dossier with independent gold matcher.

**Success:** recall ≥ 0.95 on gold_set (100). Intermediate wins: large jumps in `found` after each seed batch.

**Non-goals this exp:** formatters, orchestrator tests, live long runs inside agents (orchestrator runs eval_grid).
