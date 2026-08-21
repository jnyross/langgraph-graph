"""Unit tests for rumor gating in validate_signal._rejection_reasons."""

from __future__ import annotations

import pytest

from langgraph_graph.news_radar.models import SignalDraft, WatchCell
from langgraph_graph.news_radar.nodes.validate_signal import _rejection_reasons


def _draft(**overrides: object) -> SignalDraft:
    base: dict[str, object] = {
        "title": "Draft privacy bill advances in committee",
        "jurisdiction_id": "european_union",
        "domain_id": "privacy",
        "source_url": "https://example.com/news",
        "confidence": 0.8,
    }
    base.update(overrides)
    return SignalDraft.model_validate(base)


_CELL = WatchCell(
    cell_id="c1",
    jurisdiction="European Union",
    jurisdiction_id="european_union",
    domain="privacy",
    domain_id="privacy",
    subject="Meta",
)


def test_rumor_event_type_rejected_when_rumors_excluded() -> None:
    draft = _draft(event_type="rumor", is_rumor=False)
    reasons = _rejection_reasons(draft, _CELL, include_rumors=False)
    assert any("rumor" in reason for reason in reasons)


def test_rumor_event_type_passes_when_rumors_included() -> None:
    draft = _draft(event_type="rumor", is_rumor=False)
    assert _rejection_reasons(draft, _CELL, include_rumors=True) == []


def test_is_rumor_flag_still_rejected_when_rumors_excluded() -> None:
    draft = _draft(event_type="bill", is_rumor=True)
    reasons = _rejection_reasons(draft, _CELL, include_rumors=False)
    assert any("rumor" in reason for reason in reasons)


def test_ordinary_event_unaffected_by_rumor_gating() -> None:
    draft = _draft(event_type="bill", is_rumor=False)
    assert _rejection_reasons(draft, _CELL, include_rumors=False) == []
    assert _rejection_reasons(draft, _CELL, include_rumors=True) == []


def test_cell_mismatch_still_reported() -> None:
    draft = _draft(jurisdiction_id="united_states")
    reasons = _rejection_reasons(draft, _CELL, include_rumors=False)
    assert any("mismatch" in reason for reason in reasons)


@pytest.mark.parametrize(
    ("event_type", "is_rumor", "include_rumors", "expected"),
    [
        ("rumor", False, False, True),
        ("rumor", False, True, False),
        ("bill", True, False, True),
        ("bill", False, False, False),
    ],
)
def test_gating_matrix(
    event_type: str, is_rumor: bool, include_rumors: bool, expected: bool
) -> None:
    draft = _draft(event_type=event_type, is_rumor=is_rumor)
    reasons = _rejection_reasons(draft, _CELL, include_rumors=include_rumors)
    assert any("rumor" in reason for reason in reasons) is expected
