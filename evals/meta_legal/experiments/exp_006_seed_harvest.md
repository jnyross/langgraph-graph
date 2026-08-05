# exp_006 — deterministic seed instrument harvest

**Hypothesis:** Eval recall peaked at 0.70 then fell to ~0.62 at concurrency 100 with more `cell_errors`. LLM+search is flaky under load; cells with curated seeds still return empty drafts when search/LLM fail. A deterministic harvest path that turns instrument names + seed URLs into `LawRecordDraft`s should floor non-empty draft rates and recover gold instruments even when the model path flakes.

**Method:**

- New `nodes/seed_harvest.py`:
  - `pair_instruments_and_seeds` — best-effort match of `_JURISDICTION_DOMAIN_INSTRUMENTS` names to `_SEED_URLS` (token/CELEX/number scoring; leftover seeds still emit).
  - `harvest_seed_instruments(cell)` — fetch each paired seed (reuse cache when available), build drafts with `title`, `source_url`, `citation` (best-effort), `excerpt` (first N chars or empty), `meta_nexus=platform_obligation`, `confidence=0.8`, `source_type=primary` on official hosts. Always emits title+URL even if fetch is empty (validate_cell needs URL).
  - `merge_drafts` — append harvest results; dedupe by normalized `source_url` / title.
- `research_cell.run_research_cell` always merges harvest drafts after LLM extract (and when LLM init/invoke fails).
- Optional rate-limit softening: `META_LEGAL_FETCH_HOST_SPACING_MS` per-host fetch spacing; one 429 backoff retry in `_call_llm`.

**Success:**

- Unit: mocked fetch on EU privacy seeds yields ≥1 draft accepted by `validate_drafts`.
- Unit: empty search + empty/failing LLM still returns harvest drafts when seeds exist.
- Live grid (orchestrator): fewer empty cells / lower `cell_errors` draft-empty rate at concurrency 100; recall should not regress below the 0.70 peak solely due to LLM flake.

**Non-goals this exp:** gold_set edits, matcher auto-pass of gold ids, full live eval inside this agent.
