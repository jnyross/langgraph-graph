"""Offline table-driven tests for the LLM JSON extraction helpers.

Covers ``_extract_json_payload`` (fenced / bare / garbage inputs) and
``_drafts_from_payload`` (wrapper-key handling and value clamps) with fake
objects only — no network, no real LLM.
"""

from __future__ import annotations

from typing import Any

import pytest

from langgraph_graph.meta_legal.models import ResearchCell, make_cell_id
from langgraph_graph.meta_legal.nodes.research_cell import (
    _drafts_from_payload,
    _extract_json_payload,
    _payload_from_structured,
)


def _cell() -> ResearchCell:
    return ResearchCell(
        cell_id=make_cell_id("european_union", "privacy"),
        jurisdiction="European Union",
        jurisdiction_id="european_union",
        domain="privacy",
        domain_id="privacy",
        subject="Meta",
        status="researching",
    )


class _Msg:
    """Fake chat response carrying plain-text content."""

    def __init__(self, content: str) -> None:
        self.content = content


# ---------------------------------------------------------------------------
# _extract_json_payload: (label, raw text, expected payload or None-sentinel)
# ---------------------------------------------------------------------------

_MISSING = object()

_EXTRACT_CASES: list[tuple[str, str, Any]] = [
    ("empty", "", None),
    ("whitespace", "   \n\t ", None),
    ("bare_object", '{"drafts": []}', {"drafts": []}),
    ("bare_array", '[{"title": "GDPR"}]', [{"title": "GDPR"}]),
    (
        "fenced_json",
        '```json\n{"drafts": [{"title": "DSA"}]}\n```',
        {"drafts": [{"title": "DSA"}]},
    ),
    (
        "fenced_bare",
        "```\n[1, 2, 3]\n```",
        [1, 2, 3],
    ),
    (
        "prose_then_object",
        'Here is the result:\n{"ok": true}\nHope that helps!',
        {"ok": True},
    ),
    (
        "prose_then_array",
        'Sure!\n[{"title": "A"}, {"title": "B"}]',
        [{"title": "A"}, {"title": "B"}],
    ),
    (
        "two_invalid_blobs_returns_none",
        'Note {a: b} is not JSON but {"n": 1} is.',
        None,
    ),
    (
        "unclosed_outer_recovers_inner_array",
        '{"drafts": [{"title": "x"}',
        [{"title": "x"}],
    ),
    (
        "unclosed_no_closer_at_all",
        '{"drafts": ["x", "y',
        None,
    ),
    ("garbage_no_braces", "no structured payload here", None),
    ("garbage_single_quotes", "{'title': 'x'}", None),
]


@pytest.mark.parametrize(
    ("label", "raw", "expected"), _EXTRACT_CASES, ids=[c[0] for c in _EXTRACT_CASES]
)
def test_extract_json_payload_table(label: str, raw: str, expected: Any) -> None:
    got = _extract_json_payload(raw)
    if expected is None:
        assert got is None, f"{label}: expected None, got {got!r}"
    else:
        assert got == expected, f"{label}: expected {expected!r}, got {got!r}"


# ---------------------------------------------------------------------------
# Wrapper-key handling: drafts / records / items / bare object / bare list
# ---------------------------------------------------------------------------


def _draft_dict(title: str) -> dict[str, Any]:
    return {
        "title": title,
        "source_url": f"https://eur-lex.europa.eu/{title}",
        "meta_nexus": "platform_obligation",
        "source_type": "primary",
        "confidence": 0.8,
    }


@pytest.mark.parametrize(
    ("label", "payload"),
    [
        ("drafts_key", {"drafts": [_draft_dict("A")]}),
        ("records_key", {"records": [_draft_dict("A")]}),
        ("items_key", {"items": [_draft_dict("A")]}),
        ("bare_list", [_draft_dict("A")]),
        ("single_object", _draft_dict("A")),
    ],
)
def test_drafts_from_payload_wrapper_keys(label: str, payload: Any) -> None:
    drafts = _drafts_from_payload(payload, cell=_cell(), worker_model="test_model")
    assert len(drafts) == 1, f"{label}: expected 1 draft, got {drafts!r}"
    assert drafts[0].title == "A"
    assert drafts[0].cell_id == make_cell_id("european_union", "privacy")
    assert drafts[0].worker_model == "test_model"


@pytest.mark.parametrize(
    ("label", "payload"),
    [
        ("none", None),
        ("scalar", 42),
        ("empty_list", []),
        ("list_of_blanks", [{}, "", None]),
    ],
)
def test_drafts_from_payload_no_usable_items(label: str, payload: Any) -> None:
    assert _drafts_from_payload(payload, cell=_cell(), worker_model="m") == [], label


# ---------------------------------------------------------------------------
# Clamps and fallbacks applied by _drafts_from_payload
# ---------------------------------------------------------------------------


def test_confidence_clamped_to_unit_range() -> None:
    too_high = _draft_dict("Hi")
    too_high["confidence"] = 4.2
    too_low = _draft_dict("Lo")
    too_low["confidence"] = -3
    non_numeric = _draft_dict("NaN")
    non_numeric["confidence"] = "not-a-number"

    drafts = _drafts_from_payload(
        [too_high, too_low, non_numeric], cell=_cell(), worker_model="m"
    )
    assert [d.confidence for d in drafts] == [1.0, 0.0, 0.5]


def test_unknown_nexus_and_source_type_fall_back() -> None:
    weird = _draft_dict("Weird")
    weird["meta_nexus"] = "totally unknown nexus"
    weird["source_type"] = "blog post"

    drafts = _drafts_from_payload([weird], cell=_cell(), worker_model="m")
    assert len(drafts) == 1
    assert drafts[0].meta_nexus == "platform_obligation"
    assert drafts[0].source_type == "secondary"


def test_missing_source_url_falls_back_to_url_key() -> None:
    aliased = _draft_dict("Aliased")
    del aliased["source_url"]
    aliased["url"] = "https://eur-lex.europa.eu/aliased"

    drafts = _drafts_from_payload([aliased], cell=_cell(), worker_model="m")
    assert len(drafts) == 1
    assert drafts[0].source_url == "https://eur-lex.europa.eu/aliased"


# ---------------------------------------------------------------------------
# _payload_from_structured: fake structured-output shapes
# ---------------------------------------------------------------------------


def test_payload_from_structured_message_text() -> None:
    payload = _payload_from_structured(_Msg('{"drafts": [{"title": "X"}]}'))
    assert payload == {"drafts": [{"title": "X"}]}


def test_payload_from_structured_mapping_passthrough() -> None:
    payload = _payload_from_structured({"drafts": []})
    assert payload == {"drafts": []}


def test_payload_from_structured_none_and_garbage() -> None:
    assert _payload_from_structured(None) is None
    assert _payload_from_structured(_Msg("not json at all")) is None
