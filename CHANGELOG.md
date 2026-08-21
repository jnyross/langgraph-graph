# Changelog

All notable changes to this project will be documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [0.1.0] - Unreleased

### Added
- Project scaffold: `src/langgraph_graph/` package, `examples/`, `scripts/`, `docs/`.
- Starter graph with `plan → act (HITL interrupt) → reply` nodes and in-memory checkpointer.
- Typed `AgentState` and tool registry (`send_message`, `write_record` stubs).
- HITL policy doc and roadmap.
- CLI runner (`scripts/run.py`) and demo (`examples/hitl_basic.py`).

### Changed
- HITL resume parsing fails closed: unrecognized or empty resume payloads reject instead of approve.
- meta_legal: per-cell draft validation folded into `research_cell` (the standalone `validate_cell` node never executed post-fan-out); drafts citing sources not retrieved for their cell are rejected as `unverified_source`.
- meta_legal: seed harvest emits only fetch-backed drafts; LLM extraction gate configurable via `META_LEGAL_FORCE_LLM` / `smoke --force-llm`; default LLM extraction budget raised to 150s (`META_LEGAL_LLM_TIMEOUT_S`).
- Search auto chain probes the Firecrawl REST API (news + web result shapes) before CLI/DDG; fetch/search breakers and bounded fetch loops.
- news_radar: deterministic cluster ids and ordering; shape-tolerant context loading.
- Web: run selector functional, `source_url` scheme allowlist, cache headers, generic API error bodies; generated matrices no longer embed absolute build paths.

### Added
- CI workflow (`.github/workflows/ci.yml`): pytest hard gate, offline matrix/example smokes, informational ruff.
- Dossier `index.json` now records rejection reasons and cell errors (capped).
- Catalog promotion refuses on uncertain verifications, run errors, or out-of-scope removals; seed widening skips errored/unverified runs.
- Untrusted-content framing (`<untrusted_source>` delimiters) across research/scan/verify prompts.

### Fixed
- Eval citation matcher false positives (single-digit fingerprints, prefix-substring collisions); gold gate runs on fresh clones via worktree isolation.
- Firecrawl news-topic search results (v2 `data.news`) now parsed — fixes silently empty radar scans on keyed runs.
- Dossier law-file slug collisions and stale-run merges; host-spacing lock no longer serializes unrelated hosts; worker model label drift.
