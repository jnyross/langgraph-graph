# exp_007 — cell-interior search speedup

**Hypothesis:** The per-cell wall is search, not the graph. Live profile: `web_search` spends ~12s per query returning 0 results (DDG backends throttled/blocked under load; each multi-backend wave waits out its timeout), and `build_search_queries` emits ~24 queries run serially → ~5 min/cell before the LLM ever runs. Killing dead-backend thrash and running far fewer queries concurrently should cut cell time by an order of magnitude without losing recall (seeds + harvest already carry the deterministic floor).

**Method:**

- `tools/search.py`:
  - Global failure circuit breaker: after N consecutive all-backend-empty searches process-wide (default 3, `META_LEGAL_SEARCH_BREAKER_N`), short-circuit further searches to `[]` for a cooldown window (default 120s, `META_LEGAL_SEARCH_BREAKER_COOLDOWN_S`). First probe after cooldown is half-open: max one backend wave; success closes, empty re-trips.
  - Per-attempt timeout 5s → 3s; backend wave timeout 6s → 4s.
  - In-process query cache unchanged (empty results still cached). Never-raise contract kept.
- `nodes/research_cell.py`:
  - Query cap per cell: default 6 (`META_LEGAL_MAX_QUERIES`), prioritized instrument site-restricted → instrument generic → domain sweep; the single Meta-nexus query is dropped when over cap.
  - Capped queries run **concurrently** via daemon pool (max 4 workers); hits aggregated in query-priority order so URL ranking tiebreaks stay stable.
  - Seed-first fast path: when curated seeds exist for the cell, total search wall-clock is capped (~10s default, `META_LEGAL_SEARCH_BUDGET_S`); on expiry the cell proceeds with seeds plus whatever hits arrived (soft `cell_errors` note, no raise).
  - Seed merge + deterministic seed harvest (exp_006) unchanged.

**Per-cell estimate (search phase, before LLM):**

| scenario | before | after |
| --- | --- | --- |
| backends dead/throttled (observed) | ~24 queries × ~12s serial ≈ **290s** | breaker trips after 3 empties (≤ ~24s once, process-wide), then **~0s** per cell for 120s windows; seeded cells capped at 10s regardless |
| backends healthy | ~24 queries × ~1–3s serial ≈ 30–70s | ≤6 queries on 4 workers, each wave ≤4s (+ one retry wave) ≈ **4–16s**; seeded cells hard-capped at 10s |

Net: worst case per cell drops from ~5 min to ≤10s (seeded) / ≤~16s (unseeded, healthy), and a dead search backend now costs the whole run one breaker trip instead of 5 min × 100 cells.

**Success:** unit tests for changed modules pass (all mocked, no network); synthetic slow `search_fn` (5s sleep) with a 2s budget finishes the cell in <5s wall and still emits seed-harvest drafts (`test_search_budget_slow_search_still_emits_harvest_drafts`); breaker open/half-open/recovery covered by `test_search_breaker_*`.

**Non-goals:** gold set / matcher changes, model changes, live eval run (orchestrator verifies), eur-lex fetch unblocking.
