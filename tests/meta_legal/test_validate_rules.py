"""U4: rule-based validate_drafts (folded into the research_cell worker)."""

from __future__ import annotations

import pytest

from langgraph_graph.meta_legal.models import (
    LawRecord,
    LawRecordDraft,
    RejectedRecord,
    ResearchCell,
    make_cell_id,
)
from langgraph_graph.meta_legal.nodes.research_cell import validate_drafts


def _cell(
    jurisdiction_id: str = "european_union",
    domain_id: str = "privacy",
) -> ResearchCell:
    return ResearchCell(
        cell_id=make_cell_id(jurisdiction_id, domain_id),
        jurisdiction=jurisdiction_id.replace("_", " ").title(),
        jurisdiction_id=jurisdiction_id,
        domain=domain_id,
        domain_id=domain_id,
        status="validating",
        subject="Meta",
    )


def _draft(**overrides: object) -> LawRecordDraft:
    base: dict = {
        "title": "Digital Services Act",
        "jurisdiction_id": "european_union",
        "domain_id": "privacy",
        "meta_nexus": "platform_obligation",
        "meta_nexus_rationale": "Applies to very large online platforms",
        "citation": "Regulation (EU) 2022/2065",
        "source_url": "https://eur-lex.europa.eu/eli/reg/2022/2065/oj",
        "source_type": "primary",
        "excerpt": "Providers of very large online platforms shall ...",
        "cell_id": make_cell_id("european_union", "privacy"),
    }
    base.update(overrides)
    return LawRecordDraft(**base)  # type: ignore[arg-type]


def test_cited_primary_accepted() -> None:
    accepted, rejected = validate_drafts([_draft()], cell=_cell())
    assert len(accepted) == 1
    assert len(rejected) == 0
    rec = accepted[0]
    assert isinstance(rec, LawRecord)
    assert rec.validated is True
    assert rec.title == "Digital Services Act"
    assert rec.source_url.startswith("https://")


def test_missing_url_rejected_missing_citation() -> None:
    accepted, rejected = validate_drafts(
        [_draft(source_url="")],
        cell=_cell(),
    )
    assert accepted == []
    assert len(rejected) == 1
    assert isinstance(rejected[0], RejectedRecord)
    assert "missing_citation" in rejected[0].reason


def test_jurisdiction_mismatch_rejected() -> None:
    accepted, rejected = validate_drafts(
        [_draft(jurisdiction_id="united_states")],
        cell=_cell(jurisdiction_id="european_union", domain_id="privacy"),
    )
    assert accepted == []
    assert len(rejected) == 1
    assert "jurisdiction_mismatch" in rejected[0].reason


def test_domain_mismatch_rejected() -> None:
    accepted, rejected = validate_drafts(
        [_draft(domain_id="competition")],
        cell=_cell(domain_id="privacy"),
    )
    assert accepted == []
    assert len(rejected) == 1
    assert "domain_mismatch" in rejected[0].reason


def test_missing_meta_nexus_rejected() -> None:
    accepted, rejected = validate_drafts(
        [_draft(meta_nexus="")],
        cell=_cell(),
    )
    assert accepted == []
    assert len(rejected) == 1
    assert "missing_meta_nexus" in rejected[0].reason


def test_missing_title_rejected() -> None:
    accepted, rejected = validate_drafts(
        [_draft(title="   ")],
        cell=_cell(),
    )
    assert accepted == []
    assert len(rejected) == 1
    assert "missing_title" in rejected[0].reason


def test_dict_draft_coercion() -> None:
    cell = _cell()
    payload = {
        "title": "GDPR",
        "jurisdiction_id": "european_union",
        "domain_id": "privacy",
        "meta_nexus": "platform_obligation",
        "source_url": "https://eur-lex.europa.eu/eli/reg/2016/679/oj",
        "source_type": "primary",
        "cell_id": cell.cell_id,
    }
    accepted, rejected = validate_drafts([payload], cell=cell)  # type: ignore[list-item]
    assert len(accepted) == 1
    assert rejected == []


def test_unverified_source_rejected_when_allowlist_set() -> None:
    """Host not among allowed_sources → rejected with unverified_source."""
    accepted, rejected = validate_drafts(
        [_draft()],
        cell=_cell(),
        allowed_sources={"https://gdpr-info.eu/art-1/"},
    )
    assert accepted == []
    assert len(rejected) == 1
    assert "unverified_source" in rejected[0].reason


def test_verified_source_accepted_with_allowlist() -> None:
    """Draft citing a host that WAS searched/fetched for the cell is accepted."""
    accepted, rejected = validate_drafts(
        [_draft()],
        cell=_cell(),
        allowed_sources={
            "https://eur-lex.europa.eu/eli/reg/2022/2065/oj",
            "https://example.org/other",
        },
    )
    assert len(accepted) == 1
    assert rejected == []


def test_allowlist_none_keeps_check_off() -> None:
    """Legacy callers (allowed_sources=None) skip the source-allowlist check."""
    accepted, rejected = validate_drafts([_draft()], cell=_cell())
    assert len(accepted) == 1
    assert rejected == []


def test_run_research_cell_validates_per_cell_with_unverified_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end per-cell proof: run_research_cell itself rejects a draft whose
    cited host was never searched/fetched for THIS cell (folded validation)."""
    from langgraph_graph.meta_legal.nodes.research_cell import run_research_cell

    cell = _cell()

    def search_fn(query: str, max_results: int = 5) -> list[dict[str, str]]:
        return [
            {
                "title": "DSA official",
                "url": "https://eur-lex.europa.eu/eli/reg/2022/2065/oj",
                "snippet": "Digital Services Act full text",
            }
        ]

    def fetch_fn(url: str, max_chars: int = 12000) -> str:
        # Only the searched URL yields a body; curated seeds are disabled below.
        if url.startswith("https://eur-lex.europa.eu/"):
            return "Digital Services Act text. Providers shall comply."[:max_chars]
        return ""

    # Disable curated seeds AND the instrument harvest floor: even with no
    # seed URLs the harvester emits canonical instrument drafts (>= 3, which
    # would skip the LLM path entirely) citing hosts never fetched this cell.
    import langgraph_graph.meta_legal.nodes.research_cell as rc_mod

    monkeypatch.setattr(rc_mod, "seed_urls_for_cell", lambda cell: [])
    monkeypatch.setattr(rc_mod, "harvest_seed_instruments", lambda *a, **k: [])

    llm_payload = (
        '{"drafts":['
        '{"title":"Verified Law","citation":"DSA-1",'
        '"source_url":"https://eur-lex.europa.eu/eli/reg/2022/2065/oj",'
        '"source_type":"primary","excerpt":"Providers shall comply.",'
        '"language":"en","confidence":0.9,"meta_nexus":"platform_obligation"},'
        '{"title":"Fabricated Law","citation":"XX-1",'
        '"source_url":"https://never-fetched.example/law",'
        '"source_type":"primary","excerpt":"Made up.",'
        '"language":"en","confidence":0.9,"meta_nexus":"platform_obligation"}]}'
    )

    class _Msg:
        def __init__(self, content: str) -> None:
            self.content = content

    class _LLM:
        def invoke(self, messages: object, **_kwargs: object) -> _Msg:
            return _Msg(llm_payload)

    result = run_research_cell(cell, search_fn=search_fn, fetch_fn=fetch_fn, llm=_LLM())

    accepted_titles = {r.title for r in result.get("accepted") or []}
    reasons = {(r.record.title, r.reason) for r in result.get("rejected") or []}
    assert "Verified Law" in accepted_titles
    assert any(
        title == "Fabricated Law" and "unverified_source" in reason for title, reason in reasons
    ), f"expected cell-scoped unverified_source rejection; got {reasons}"
