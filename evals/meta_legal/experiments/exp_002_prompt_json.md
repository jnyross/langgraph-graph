# exp_002 — structured JSON extraction + retry

**Hypothesis:** Recall fails partly because the research-cell LLM returns non-JSON, markdown-fenced, or empty drafts even when seed URLs / fetches succeed. Hardening extraction should convert more successful fetches into scorable `LawRecordDraft`s.

**Method:**

- Prefer `ChatOpenAI.with_structured_output` over a Pydantic list schema (`_ExtractedLawList`) when OpenRouter supports it (`json_schema` → `function_calling` → default).
- Fallback to `response_format` JSON mode (`json_object` / `json_schema`) via `bind`.
- Keep text JSON parse (fence strip + first `{…}`/`[…]` blob) as last resort.
- Tighten `prompts/research.md`: JSON **array only**, no markdown, `source_url` must come from provided materials, citations match statutes.
- On empty parse, one automatic retry with a short “return JSON array only” user prompt.
- Always stamp `worker_model`; never raise into the graph.
- Eval grid gains `--limit-cells N` for mini live runs.

**Success:** Higher draft yield / gold recall vs exp_001 baseline on the same cells, especially cells that already fetch primary pages. Target remains recall ≥ 0.95 on full gold_set (100); this exp isolates extraction reliability.

**Non-goals this exp:** seed expansion, concurrency/fetch tuning, gold-set edits, full 63-cell agent runs.
