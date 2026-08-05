# Roadmap

Scaffold stage. Ordered by dependency.

- [ ] Wire a real tool (e.g. Telegram send) behind the HITL `act` node.
- [ ] Swap `MemorySaver` for `SqliteSaver` for durable runs across restarts.
- [ ] Add a CLI entry point (`scripts/run.py`) with `--thread-id` resume.
- [ ] Add tests: graph compiles, interrupt fires, approval grants execution.
- [ ] Add an n8n webhook bridge for family/ops automations (separate lane).
- [ ] Eval harness for local model quality on a fixed task set.
