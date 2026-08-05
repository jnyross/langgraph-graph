"""U4: rule-based validate_cell / validate_drafts."""

from __future__ import annotations

from langgraph_graph.meta_legal.models import (
    LawRecord,
    LawRecordDraft,
    RejectedRecord,
    ResearchCell,
    make_cell_id,
)
from langgraph_graph.meta_legal.nodes.validate_cell import validate_cell, validate_drafts


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


def test_malformed_and_empty_drafts_no_crash() -> None:
    accepted, rejected = validate_drafts([], cell=_cell())
    assert accepted == []
    assert rejected == []

    accepted, rejected = validate_drafts(None, cell=None)  # type: ignore[arg-type]
    assert accepted == []
    assert rejected == []

    # Garbage items → rejected malformed, not raised
    accepted, rejected = validate_drafts(
        [None, 42, {"not": "a draft"}, "oops"],  # type: ignore[list-item]
        cell=_cell(),
    )
    assert accepted == []
    assert len(rejected) == 4
    assert all(r.reason == "malformed_draft" for r in rejected)


def test_validate_cell_node_from_send_state() -> None:
    cell = _cell()
    draft = _draft()
    out = validate_cell(
        {
            "cell_id": cell.cell_id,
            "jurisdiction_id": cell.jurisdiction_id,
            "domain_id": cell.domain_id,
            "jurisdiction": cell.jurisdiction,
            "domain": cell.domain,
            "drafts": [draft],
        }
    )
    assert "accepted" in out and "rejected" in out
    assert len(out["accepted"]) == 1
    assert out["rejected"] == []
    assert out["accepted"][0].validated is True


def test_validate_cell_filters_other_cell_drafts() -> None:
    cell = _cell()
    mine = _draft(cell_id=cell.cell_id)
    other = _draft(
        cell_id=make_cell_id("united_states", "privacy"),
        jurisdiction_id="united_states",
        title="Other Cell Law",
    )
    out = validate_cell(
        {
            "cell_id": cell.cell_id,
            "jurisdiction_id": cell.jurisdiction_id,
            "domain_id": cell.domain_id,
            "drafts": [mine, other],
        }
    )
    assert len(out["accepted"]) == 1
    assert out["accepted"][0].title == "Digital Services Act"


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
