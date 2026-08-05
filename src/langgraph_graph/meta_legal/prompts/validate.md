# Validate cell — optional LLM adjudicator

v1 validation is **rule-based** (`nodes/validate_cell.py`): required title,
source URL, meta_nexus, and jurisdiction/domain match against the research cell.

This prompt is reserved for a future second-pass adjudicator (same OpenRouter
ChatOpenAI stack via `get_llm`) on borderline cases only, for example:

- Meta nexus is present but rationale is thin or contradictory
- Source URL is non-official / secondary and needs a primary-source upgrade
- Excerpt does not support the cited instrument title

Do **not** replace deterministic rejects (`missing_citation`, `missing_title`,
`jurisdiction_mismatch`, `domain_mismatch`, `missing_meta_nexus`). LLM output
should only re-rank or annotate already-structured drafts.

Expected structured fields if enabled later:

- `decision`: `accept` | `reject` | `needs_review`
- `reason`: short machine code or free-text rationale
- `law_id`: draft id under review
