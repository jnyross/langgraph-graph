# Jurisdiction catalog

`meta_operating_catalog.json` lists jurisdictions for Meta full-grid legal research runs (Facebook, Instagram, WhatsApp operating footprint).

## Provenance

- **Purpose:** scaffolding input lists for `meta_legal` cartesian cells — not a compliance determination.
- **Method:** desk-curated from public knowledge of Meta consumer availability, EU membership, and U.S. state privacy / youth-safety (AADC, social-minor) statutes as of 2026 research.
- **Exclusions:** known total/near-total consumer blocks (e.g. PRC, DPRK, Iran). Restricted markets may still appear with cautious rationales.
- **IDs:** stable slugs compatible with `langgraph_graph.meta_legal.models.slugify`. `georgia_us` is the U.S. state (country remains `georgia`).
- **Not derived from** `data/dossiers/**`.

`jurisdiction_catalog_seed.json` is the committed deterministic candidate
universe. It includes ISO-style country coverage and curated supranational,
US, Canadian, German, Australian, and selected city/subnational entries.
Research runs discover and verify additions, then write `runs/<run_id>/`;
they never overwrite the live catalog by default.

## Loader

```python
from langgraph_graph.meta_legal.jurisdictions import (
    default_catalog_path,
    load_catalog,
    list_jurisdiction_names,
)

catalog = load_catalog()
names = list_jurisdiction_names(levels=["country", "supranational"])
```
