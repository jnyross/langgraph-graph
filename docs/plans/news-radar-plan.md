# Plan — `news_radar`: forward-looking news/rumor intelligence graph

Standalone fourth LangGraph graph (`agent`, `meta_legal`, `jurisdiction_catalog`, **`news_radar`**).
It consumes the outputs of the two existing graphs and searches **news / trade press / think-tank /
law-firm-blog sources — deliberately not official primary sources** — to surface what is *coming*:
bills introduced, amendments, consultations, enforcement probes, court challenges, leaks and rumors.

Where `meta_legal` answers *"what law is in force?"*, `news_radar` answers
*"what is about to change, and how likely is it?"*.

---

## 1. Data flow (control order)

```
jurisdiction_catalog  →  data/jurisdictions/meta_operating_catalog.json ──┐
                                                                          ├─→ news_radar
meta_legal            →  data/dossiers/<run_id>/index.json ───────────────┘        │
                                                                                   ▼
                        data/radar/<run_id>/{manifest,index,signals/,timeline}.json
```

```
START
 → ingest_radar_input        # normalize inputs, resolve window, run_id
 → load_context              # catalog jurisdictions + latest dossier law index (known-law context)
 → plan_watch_cells          # jurisdiction × domain cells, tiered/limited
 → [Send("scan_cell", …) per cell]        (or → write_radar when empty/error)
 → scan_cell                 # news-first search (recency-bounded) → fetch → LLM extract SignalDrafts
 → validate_signal           # deterministic news-appropriate rules (recency, nexus, publisher class)
 → cluster_signals           # dedupe/corroborate across cells & publishers; confidence uplift
 → link_known_laws           # attach related_law_ids from dossier; mark new vs. known
 → write_radar               # artifacts + delta vs. previous run
 → END
```

Fan-out uses the same `Send` + `Annotated[..., operator.add]` reducer pattern as `meta_legal`.
`cluster_signals` / `link_known_laws` run **after** fan-in (they need the global view), unlike
`meta_legal` where validation is per-worker.

---

## 2. New module layout

```
src/langgraph_graph/news_radar/
├── __init__.py
├── graph.py            # ingest_radar_input, fanout_cells, build_graph, module-level `graph`
├── models.py           # RadarInput, WatchCell, SignalDraft, SignalRecord, SignalCluster, RadarManifest
├── state.py            # RadarState TypedDict
├── sources.py          # news publisher registry + publisher-class scoring (the inverse of _OFFICIAL_HOST_HINTS)
├── prompts/
│   ├── scan.md         # news-first extraction prompt
│   └── classify.md     # (phase 2) signal-type/likelihood rubric
└── nodes/
    ├── load_context.py
    ├── plan_watch_cells.py
    ├── scan_cell.py
    ├── validate_signal.py
    ├── cluster_signals.py
    ├── link_known_laws.py
    └── write_radar.py
```

Registered in `langgraph.json` as `"news_radar": "./src/langgraph_graph/news_radar/graph.py:graph"`.

Reused as-is (no forks): `tools/search.py`, `tools/fetch.py`, `tools/_pool.py`, `llm.get_llm`,
`_env.env_*`, `run_config.max_concurrency/write_run_metrics`, `models.slugify/normalize_domain/
normalize_jurisdiction/make_cell_id`, `jurisdictions.load_catalog/list_jurisdiction_names`.

---

## 3. Shared-tool change (the only edit to existing code)

`src/langgraph_graph/meta_legal/tools/search.py` — backwards-compatible keyword-only options so the
existing cache / circuit-breaker / Firecrawl semaphore are reused instead of duplicated:

```python
@dataclass(frozen=True)
class SearchOptions:
    """Provider-agnostic search modifiers. Defaults reproduce today's behavior exactly."""
    topic: Literal["general", "news"] = "general"
    recency_days: int | None = None          # Tavily start_date / Firecrawl tbs=qdr:*
    include_domains: tuple[str, ...] = ()
    exclude_domains: tuple[str, ...] = ()

def web_search(
    query: str,
    max_results: int = 5,
    *,
    options: SearchOptions | None = None,   # NEW; None == today's behavior
) -> list[dict[str, str]]: ...
    # cache key becomes (query, max_results, options); breaker/semaphores unchanged
```

Provider mapping (verified against current provider docs):

| option | Tavily `POST /search` | Firecrawl `POST /v2/search` | DDG |
|---|---|---|---|
| `topic="news"` | `topic: "news"` | `sources: [{"type": "news"}]` | `news` backend |
| `recency_days=N` | `start_date` (YYYY-MM-DD) | `tbs: "sbd:1,qdr:d\|w\|m"` | `timelimit` |
| `include/exclude_domains` | `include_domains` / `exclude_domains` | `includeDomains` / `excludeDomains` | query `site:` hints |

Result normalization gains an optional `published_at` (Tavily news `published_date`, Firecrawl news
`date`) — added as an extra key, so `{title,url,snippet}` consumers are unaffected.
Caveat found in the docs: Tavily's `country` boost is **only valid with `topic="general"`**, so
per-jurisdiction targeting comes from query text + the publisher registry, not `country`.

---

## 4. Symbols, in control/data-flow order

### 4.1 `news_radar/models.py`

```python
SignalType = Literal[
    "bill_introduced", "bill_advanced", "bill_passed_pending_effect", "amendment_proposed",
    "consultation_open", "regulator_guidance_signalled", "enforcement_action", "investigation_opened",
    "litigation", "court_ruling_pending", "political_commitment", "rumor", "other",
]
PipelineStage = Literal["rumored", "drafted", "introduced", "in_committee", "passed", "awaiting_signature",
                        "enacted_not_in_force", "in_force", "stalled", "withdrawn", "unknown"]
PublisherClass = Literal["wire", "national_news", "trade_press", "law_firm", "think_tank", "blog",
                         "official", "social", "unknown"]

class RadarInput(BaseModel):
    """Invoke input. Empty jurisdictions/domains ⇒ 'all from the catalog'."""
    jurisdictions: list[str] = []          # [] → every catalog jurisdiction
    domains: list[str] = []                # [] → the five starter domains
    subject: str = "Meta"
    lookback_days: int = 30                # recency window for the news search
    levels: list[str] = []                 # catalog level filter (country, supranational, us_state…)
    dossier_run_id: str | None = None      # None → latest run under data/dossiers
    max_cells: int | None = None           # cost guard for full-grid runs
    include_rumors: bool = True

class WatchCell(BaseModel):
    """jurisdiction × domain scan unit; same ``{jurisdiction_id}::{domain_id}`` id convention."""
    cell_id: str; jurisdiction: str; jurisdiction_id: str; domain: str; domain_id: str
    subject: str = "Meta"
    known_law_titles: list[str] = []       # from the dossier — sharpens queries and 'is this new?'
    lookback_days: int = 30

class SignalDraft(BaseModel):
    """One forward-looking development extracted from a news article."""
    signal_id: str = Field(default_factory=lambda: str(uuid4()))
    headline: str
    summary: str = ""
    signal_type: SignalType = "other"
    pipeline_stage: PipelineStage = "unknown"
    jurisdiction_id: str; domain_id: str; cell_id: str = ""
    instrument_name: str = ""              # e.g. "Kids Online Safety Act"
    subject_nexus: Literal["named_party", "platform_obligation", "sector_rule", "speculative", "other"]
    subject_nexus_rationale: str = ""
    source_url: str = ""; publisher: str = ""; publisher_class: PublisherClass = "unknown"
    published_at: str | None = None        # ISO date from provider or article body
    expected_effective_date: str | None = None
    likelihood: float = Field(0.5, ge=0.0, le=1.0)   # probability it becomes binding, per the reporting
    confidence: float = Field(0.5, ge=0.0, le=1.0)   # confidence the extraction is faithful
    is_rumor: bool = False
    excerpt: str = ""; language: str = "en"
    retrieved_at: str = Field(default_factory=_utc_now_iso)
    worker_model: str = ""

class SignalRecord(SignalDraft):
    """Validated + clustered signal written to the radar."""
    validated: bool = True
    cluster_id: str = ""
    corroboration_count: int = 1           # distinct publishers reporting the same development
    corroborating_urls: list[str] = []
    related_law_ids: list[str] = []        # dossier laws this development would amend/affect
    novelty: Literal["new", "update_to_known_law", "duplicate_of_known_law"] = "new"

class SignalCluster(BaseModel):
    cluster_id: str; instrument_key: str; jurisdiction_id: str; domain_id: str
    signal_ids: list[str]; publishers: list[str]; earliest_published_at: str | None
    latest_published_at: str | None; best_signal_id: str

class RejectedSignal(BaseModel):
    signal: SignalDraft; reason: str; cell_id: str = ""

class RadarManifest(BaseModel):
    run_id: str; subject: str; generated_at: str; lookback_days: int
    jurisdictions: list[str]; domains: list[str]; cell_ids: list[str]
    dossier_run_id: str | None; catalog_version: str
    signal_count: int; rejected_count: int; error_count: int
    new_since_previous_run: int; previous_run_id: str | None
```

### 4.2 `news_radar/state.py`

```python
class RadarState(TypedDict):
    # inputs
    jurisdictions: list[str]; domains: list[str]; subject: str
    lookback_days: int; levels: list[str]; dossier_run_id: NotRequired[str | None]
    max_cells: NotRequired[int | None]; include_rumors: bool
    # context
    known_laws: list[dict]                 # slim {law_id,title,jurisdiction_id,domain_id} projection
    catalog_version: str
    # plan + fan-in reducers (same pattern as ResearchState)
    cells: list[WatchCell]
    drafts: Annotated[list[SignalDraft], operator.add]
    accepted: Annotated[list[SignalRecord], operator.add]
    rejected: Annotated[list[RejectedSignal], operator.add]
    cell_errors: Annotated[list[CellError], operator.add]
    # post-fan-in
    clusters: list[SignalCluster]
    signals: list[SignalRecord]            # clustered + law-linked, replaces `accepted` downstream
    radar_path: str; run_id: str; previous_run_id: NotRequired[str | None]
    error: NotRequired[str | None]
```

### 4.3 `news_radar/graph.py`

```python
def ingest_radar_input(state: RadarState) -> dict[str, Any]:
    """Validate via RadarInput; normalize jurisdictions/domains; clamp lookback_days; assign run_id.
    Empty lists are legal here (unlike ResearchInput) and mean 'expand from the catalog'."""

def fanout_cells(state: RadarState) -> list[Send] | str:
    """Send('scan_cell', cell payload) per WatchCell, else 'write_radar' on empty/error."""

def build_graph(checkpointer: Any = None): ...
graph = _assemble_graph().compile()        # Studio export, no custom checkpointer (AGENTS.md contract)
```

### 4.4 `nodes/load_context.py`

```python
def load_context(state: RadarState) -> dict[str, Any]:
    """Read both upstream outputs. Never raises — missing artifacts degrade, not fail."""

def latest_dossier_run(root: Path | None = None) -> Path | None:
    """Newest data/dossiers/<run_id>/ that has index.json (run ids sort lexicographically by timestamp)."""

def load_known_laws(run_dir: Path) -> list[dict[str, str]]:
    """Project index.json 'laws' to {law_id,title,jurisdiction_id,domain_id}; [] when absent."""
```

### 4.5 `nodes/plan_watch_cells.py`

```python
def plan_watch_cells(state: RadarState) -> dict[str, Any]:
    """Expand catalog × domains into WatchCells, attach each cell's known_law_titles (cap ~8),
    apply level filter and max_cells, dedupe on cell_id, deterministic sort."""
```
Full grid today = 222 catalog jurisdictions × 5 domains = 1110 cells, matching `meta_legal`'s
existing full-grid scale, so `META_LEGAL_MAX_CONCURRENCY` (default 100) governs unchanged.

### 4.6 `news_radar/sources.py` — the deliberate inversion of the official-source bias

```python
_NEWS_HOST_HINTS: tuple[str, ...]          # reuters, apnews, bloomberg, ft.com, politico(.eu),
                                           # mlex, globalcompetitionreview, iapp.org, techcrunch,
                                           # theverge, lawfare, natlawreview, jdsupra, lexology…
_PUBLISHER_CLASS: dict[str, PublisherClass]
_JURISDICTION_PUBLISHERS: dict[str, tuple[str, ...]]   # e.g. "india": (economictimes, medianama…)

def classify_publisher(url: str) -> PublisherClass: ...

def news_host_score(url: str) -> int:
    """Inverse of research_cell._host_score: rewards wires/trade press, mildly penalizes
    official hosts (they are meta_legal's job) and hard-penalizes Meta-owned/social hosts.
    Official hosts are demoted, never hard-excluded — a regulator press release announcing a
    future rule is a legitimate forward signal."""

def select_news_urls(results, *, limit: int = 6) -> list[str]:
    """Publisher-diverse selection: rank by news_host_score × recency, cap 2 URLs per host
    so one outlet cannot fill the slate (corroboration needs distinct publishers)."""
```

### 4.7 `nodes/scan_cell.py`

```python
def build_news_queries(cell: WatchCell) -> list[str]:
    """Event-first, recency-first queries (contrast with build_search_queries' instrument-first
    official-text queries). Priority: (1) '<jurisdiction> <domain> bill proposed law <year>',
    (2) '<jurisdiction> <domain> regulator investigation Meta|Facebook|Instagram',
    (3) '<jurisdiction> <domain> amendment consultation draft rules', (4) known-law-anchored
    '<known law title> amendment | challenge | delay'. Capped by NEWS_RADAR_MAX_QUERIES (default 3)."""

def run_scan_cell(cell, *, search_fn=web_search, fetch_fn=fetch_url, llm=None) -> dict[str, list[Any]]:
    """search(options=SearchOptions(topic='news', recency_days=cell.lookback_days))
    → select_news_urls → concurrent fetch → LLM extract. No seed-harvest floor: there is no
    deterministic ground truth for future events, so an empty result is a valid answer."""

def scan_cell(state) -> dict[str, list[Any]]:
    """Soft-fail worker: failures become CellError, never raise into the graph."""

class _ExtractedSignalItem(BaseModel): ...   # LLM-facing subset of SignalDraft
class _ExtractedSignalList(BaseModel): drafts: list[_ExtractedSignalItem]
```
Reuses `research_cell`'s structured-output fallback ladder — I'll extract
`_try_structured_output` / `_try_json_mode` / `_call_llm` into
`meta_legal/llm.py` (or a small `tools/structured.py`) and import from both, rather than copy them.

### 4.8 `nodes/validate_signal.py`

```python
def validate_signal(state) -> dict[str, Any]:
    """Deterministic, news-appropriate rules — NOT meta_legal's citation rules:
      reject: no source_url / unparseable host; published_at older than lookback_days (when known);
              jurisdiction or domain mismatch with the cell; no subject nexus;
              is_rumor and not include_rumors; pipeline_stage=='in_force' with no forward element
              (that is meta_legal's territory);
      keep with damped confidence: single-publisher rumors, blog/social publisher_class."""
```

### 4.9 `nodes/cluster_signals.py`

```python
def instrument_key(signal: SignalDraft) -> str:
    """Stable cluster key: slug(instrument_name) or normalized headline shingle, scoped to
    jurisdiction_id::domain_id."""

def cluster_signals(state: RadarState) -> dict[str, Any]:
    """Group by instrument_key across cells/publishers; set corroboration_count and
    corroborating_urls; pick the best signal (highest publisher class × recency) per cluster;
    apply a corroboration confidence uplift (2 distinct publishers ⇒ no longer 'rumor-only')."""
```

### 4.10 `nodes/link_known_laws.py`

```python
def link_known_laws(state: RadarState) -> dict[str, Any]:
    """Token-overlap match of instrument_name/headline against the dossier's known law titles in
    the same jurisdiction+domain; set related_law_ids and novelty
    (new | update_to_known_law | duplicate_of_known_law). This is what makes the radar strictly
    forward-looking: anything that is just a restatement of an in-force dossier law is marked
    duplicate and demoted."""
```

### 4.11 `nodes/write_radar.py`

```python
RADAR_ROOT = "data/radar"                  # override with RADAR_ROOT

def write_radar(state: RadarState) -> dict[str, Any]:
    """data/radar/<run_id>/
         manifest.json                # RadarManifest
         index.json                   # summary + per-signal paths + matrix-friendly rollup
         signals/<safe_signal_id>.json|.md
         clusters.json
         timeline.json                # signals ordered by expected_effective_date / published_at
         cells/<safe_cell_id>/findings.json
         rejected/<bucket>.json
         delta.json                   # new / escalated / resolved vs. previous run
         run_metrics.json             # via run_config.write_run_metrics
       Mirrors write_dossier conventions (safe_fs_id, _dump_json) so the web layer can read both."""

def previous_run_dir(root: Path) -> Path | None: ...
def compute_delta(current: list[SignalRecord], previous_index: dict | None) -> dict[str, Any]:
    """new_signals / stage_escalations (rumored→introduced→passed) / dropped, keyed by cluster."""
```

---

## 5. Entry points, config, tests

- `examples/news_radar_smoke.py` — `--jurisdictions "European Union" --domains privacy --lookback-days 14`.
- `examples/news_radar_full_grid.py` — catalog-wide sweep with `--max-cells`, mirroring `meta_legal_full_grid.py`.
- New env vars, all via `_env`: `NEWS_RADAR_MAX_QUERIES` (3), `NEWS_RADAR_LOOKBACK_DAYS` (30),
  `NEWS_RADAR_MAX_URLS` (6), `RADAR_ROOT`. Search/fetch/LLM/concurrency vars are unchanged and shared.
- `tests/news_radar/`: `test_models.py`, `test_plan_watch_cells.py` (catalog expansion + known-law
  attachment), `test_news_queries.py`, `test_source_scoring.py` (news beats official; host diversity),
  `test_scan_cell_unit.py` (monkeypatched search/fetch/LLM), `test_validate_rules.py`,
  `test_cluster_and_link.py`, `test_write_radar.py` (+ delta), `test_graph_topology.py`.
  Plus `tests/meta_legal/test_search_options.py` asserting `SearchOptions` provider mapping and that
  the default path is byte-identical to today's request bodies.
- Docs: `docs/news-radar.md`; AGENTS.md gets a `news_radar` section (no HITL, same Studio contract).

## 6. Deliberate non-goals for this PR

- No web UI for the radar (the aggregator/matrix stays law-only); artifacts are UI-ready for a follow-up.
- No scheduled/cron watch loop — the delta machinery makes that a thin follow-up.
- No change to `meta_legal` behavior: the only shared edit is the additive `SearchOptions` parameter
  and extracting the structured-output helpers, both default-preserving.
