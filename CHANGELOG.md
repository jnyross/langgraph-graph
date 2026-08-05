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
