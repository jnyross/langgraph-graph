# exp_003 — match normalize + jurisdiction id alignment

**Hypothesis:** The graph often finds the right instruments, but recall stays low because the scorer misses on normalization drift: citation boilerplate (`Regulation (EU)` vs `Reg. (EU)`), title/alias containment, and jurisdiction_id mismatches (state gold like `california` vs dossier `united_states`).

**Method:**

1. **Matcher (`evals/meta_legal/match.py`)**
   - Stronger citation keys: strip instrument boilerplate, tolerate EU/US form variants, partial USC ranges, reordered tokens (`TFEU Art. 101` ↔ `Article 101 TFEU`).
   - Alias expansion: distinctive gold alias tokens (e.g. `GDPR`, `CCPA`, `DMA`) may hit when contained in the prediction title, not only via full slug equality.
   - Parent-jurisdiction tolerance **only** for US states under `united_states` when domain matches and title/alias evidence is present. No EU member inflation.

2. **Producer alignment**
   - `research_cell` re-canonicalizes `jurisdiction_id` via `normalize_jurisdiction` + `slugify` (so California cells stamp `california`, not a parent/generic id).
   - `validate_cell` force-stamps accepted records with the cell’s canonical jurisdiction/domain slugs.

**Success:** Higher gold recall on the same dossiers without editing gold content. Intermediate signal: unit tests for citation variants + parent jurisdiction green; self-score of gold remains ~1.0.

**Non-goals:** seed expansion (exp_001), prompt/JSON shape (exp_002), fetch concurrency (exp_004), gold gaming, formatters.
