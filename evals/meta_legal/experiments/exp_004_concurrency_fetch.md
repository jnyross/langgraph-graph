# exp_004 — concurrency + fetch/search throughput

**Hypothesis:** Empty drafts often come from fetch failures / slow sequential search. Raising cell concurrency and parallelizing in-cell fetch/search should recover more page text and cut wall time on seed-heavy cells.

**Method:**

- `tools/fetch.py`: thread-local httpx client, `follow_redirects=True`, ~28s timeout, HTML-preferring Accept, one retry after client reset.
- `tools/search.py`: in-process query cache; parallel multi-backend DDG probes (small thread pool); cache empty hits to avoid repeat thrash.
- `research_cell.py`: concurrent URL fetch via `ThreadPoolExecutor(max_workers=5)`; default `max_urls` 5→7 (seed-heavy cells may keep up to +3).
- `run_config.py` / eval grid: `DEFAULT_MAX_CONCURRENCY` 8→12 (`META_LEGAL_MAX_CONCURRENCY`); eval grid `--max-concurrency` + `--limit-cells` for mini runs.

**Success:** fewer “all URL fetches failed” cell errors; higher non-empty draft rate on gold cells; wall time down on multi-URL cells without tanking rate limits.

**Non-goals:** gold set edits, prompt/JSON schema changes, full 63-cell live eval inside this agent (use `--limit-cells` for smokes).
