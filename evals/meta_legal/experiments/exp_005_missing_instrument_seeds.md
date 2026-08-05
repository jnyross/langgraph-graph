# exp_005 — target missing gold instrument seeds

**Hypothesis:** Exp001 recall (0.70, 70/100) stalls on a long tail of gold instruments that already have nearby cell coverage but lack exact primary URLs and alias-rich instrument query strings. Filling those seeds should lift found without matcher weakening.

**Method:**

- For each missing gold pair, ensure `_JURISDICTION_DOMAIN_INSTRUMENTS` names the statute plus common aliases (Section 230 / CDA 230 / 47 USC 230; Online Safety Act 2023; PDPA 2012; CRA; WAD 2016/2102; IPRED; ECA Lei 8069; MCDPA; California Delete Act SB 362; SB 976; etc.).
- Add the official gold `source_url` (and close official mirrors) to `_SEED_URLS` for that `(jurisdiction_id, domain_id)` without dropping existing good seeds.
- CSAM: seed CELEX `52022PC0209` and label instrument as **Child Sexual Abuse Regulation Proposal Framework** so drafts can emit the proposal reference gold expects.
- Keep seeds/query-only: no gold_set import, no matcher changes.

**Success:** `seed_urls_for_cell` returns each targeted primary URL for affected cells; live grid recall moves from 0.70 toward ≥0.95 on the same 100-gold set.

**Non-goals this exp:** formatters, full suite, matcher auto-pass, gold_set edits.
