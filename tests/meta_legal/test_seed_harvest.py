"""exp_006: deterministic seed instrument harvest unit tests."""

from __future__ import annotations

from typing import Any

from langgraph_graph.meta_legal.models import LawRecordDraft, ResearchCell
from langgraph_graph.meta_legal.nodes.research_cell import run_research_cell
from langgraph_graph.meta_legal.nodes.seed_harvest import (
    harvest_seed_instruments,
    merge_drafts,
    pair_instruments_and_seeds,
)
from langgraph_graph.meta_legal.nodes.validate_cell import validate_drafts


def _eu_privacy_cell(**overrides: Any) -> ResearchCell:
    data = {
        "cell_id": "european_union::privacy",
        "jurisdiction": "European Union",
        "jurisdiction_id": "european_union",
        "domain": "privacy",
        "domain_id": "privacy",
        "subject": "Meta",
        "status": "researching",
    }
    data.update(overrides)
    return ResearchCell(**data)


def test_harvest_seed_instruments_eu_privacy_mocked_fetch() -> None:
    cell = _eu_privacy_cell()
    fetched: list[str] = []

    def fetch_fn(url: str, max_chars: int = 12000) -> str:
        fetched.append(url)
        if "2016/679" in url or "32016R0679" in url:
            return (
                "Regulation (EU) 2016/679 of the European Parliament and of the Council "
                "on the protection of natural persons with regard to the processing of "
                "personal data (General Data Protection Regulation)."
            )[:max_chars]
        return "official instrument text body for seed harvest"[:max_chars]

    drafts = harvest_seed_instruments(cell, fetch_fn=fetch_fn)

    assert len(drafts) >= 1
    assert all(isinstance(d, LawRecordDraft) for d in drafts)
    assert any("GDPR" in d.title or "2016/679" in d.title or "Data Protection" in d.title for d in drafts)
    assert any("eur-lex" in d.source_url for d in drafts)
    assert any((d.excerpt or "").strip() for d in drafts)
    assert all(d.meta_nexus == "platform_obligation" for d in drafts)
    assert all(d.source_url.startswith("http") for d in drafts)
    assert all(d.jurisdiction_id == "european_union" for d in drafts)
    assert all(d.domain_id == "privacy" for d in drafts)
    assert all(d.confidence >= 0.8 for d in drafts)
    assert fetched, "harvest should fetch seed URLs when cache empty"

    accepted, rejected = validate_drafts(drafts, cell)
    assert accepted, f"expected validate_cell to accept harvest drafts; rejected={rejected}"


def test_harvest_emits_draft_even_when_fetch_empty() -> None:
    cell = _eu_privacy_cell()

    def fetch_fn(url: str, max_chars: int = 12000) -> str:
        return ""

    drafts = harvest_seed_instruments(cell, fetch_fn=fetch_fn)
    assert len(drafts) >= 1
    assert all(d.title and d.source_url for d in drafts)
    accepted, _rejected = validate_drafts(drafts, cell)
    assert accepted


def test_pair_instruments_and_seeds_gdpr_match() -> None:
    instruments = (
        "GDPR General Data Protection Regulation Regulation (EU) 2016/679",
        "ePrivacy Directive 2002/58/EC Cookie Directive",
    )
    seeds = (
        "https://eur-lex.europa.eu/eli/reg/2016/679/oj",
        "https://eur-lex.europa.eu/eli/dir/2002/58/oj",
    )
    pairs = pair_instruments_and_seeds(instruments, seeds)
    assert len(pairs) >= 2
    by_url = {u: n for n, u in pairs}
    assert "2016/679" in by_url["https://eur-lex.europa.eu/eli/reg/2016/679/oj"] or "GDPR" in by_url[
        "https://eur-lex.europa.eu/eli/reg/2016/679/oj"
    ]


def test_merge_drafts_dedupes_by_url_and_title() -> None:
    a = LawRecordDraft(
        title="GDPR",
        jurisdiction_id="european_union",
        domain_id="privacy",
        meta_nexus="platform_obligation",
        source_url="https://eur-lex.europa.eu/eli/reg/2016/679/oj",
    )
    b = LawRecordDraft(
        title="GDPR",
        jurisdiction_id="european_union",
        domain_id="privacy",
        meta_nexus="platform_obligation",
        source_url="https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng",
    )
    c = LawRecordDraft(
        title="Other Law",
        jurisdiction_id="european_union",
        domain_id="privacy",
        meta_nexus="platform_obligation",
        source_url="https://eur-lex.europa.eu/eli/dir/2002/58/oj",
    )
    # same title as a → drop; same url as a → drop; c kept
    dup_title = LawRecordDraft(
        title="gdpr",
        jurisdiction_id="european_union",
        domain_id="privacy",
        meta_nexus="platform_obligation",
        source_url="https://example.com/other",
    )
    dup_url = LawRecordDraft(
        title="Unique Title",
        jurisdiction_id="european_union",
        domain_id="privacy",
        meta_nexus="platform_obligation",
        source_url="https://eur-lex.europa.eu/eli/reg/2016/679/oj",
    )
    merged = merge_drafts([a], [b, c, dup_title, dup_url])
    # b shares title "GDPR" with a → dropped; dup_* dropped; c kept
    assert len(merged) == 2
    urls = {d.source_url for d in merged}
    assert a.source_url in urls
    assert c.source_url in urls
    assert b.source_url not in urls



def test_run_research_cell_empty_search_and_llm_still_harvests() -> None:
    cell = _eu_privacy_cell()

    def search_fn(query: str, max_results: int = 5) -> list[dict[str, str]]:
        return []

    def fetch_fn(url: str, max_chars: int = 12000) -> str:
        return f"Fetched body for {url}"[:max_chars]

    class _EmptyLLM:
        def invoke(self, *_a: Any, **_k: Any) -> Any:
            class _Msg:
                content = '{"drafts":[]}'

            return _Msg()

        def with_structured_output(self, *_a: Any, **_k: Any) -> Any:
            raise TypeError("no structured")

    result = run_research_cell(
        cell,
        search_fn=search_fn,
        fetch_fn=fetch_fn,
        llm=_EmptyLLM(),
    )
    assert len(result["drafts"]) >= 1
    assert any(d.worker_model == "seed_harvest" for d in result["drafts"])
    assert any(d.source_url.startswith("http") for d in result["drafts"])


def test_run_research_cell_llm_failure_still_returns_harvest() -> None:
    cell = _eu_privacy_cell()

    def search_fn(query: str, max_results: int = 5) -> list[dict[str, str]]:
        return []

    def fetch_fn(url: str, max_chars: int = 12000) -> str:
        return ""

    class _BoomLLM:
        def invoke(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("upstream model unavailable")

        def with_structured_output(self, *_a: Any, **_k: Any) -> Any:
            raise TypeError("no structured")

    result = run_research_cell(
        cell,
        search_fn=search_fn,
        fetch_fn=fetch_fn,
        llm=_BoomLLM(),
    )
    assert len(result["drafts"]) >= 1
    assert all(isinstance(d, LawRecordDraft) for d in result["drafts"])
