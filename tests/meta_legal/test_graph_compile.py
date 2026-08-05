"""U1: package skeleton compiles and models normalize correctly."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from langgraph_graph.meta_legal import STARTER_DOMAINS, ResearchInput, normalize_domain
from langgraph_graph.meta_legal.graph import build_graph, graph


def test_studio_graph_compiles() -> None:
    assert graph is not None
    # CompiledStateGraph exposes invoke / get_graph
    assert hasattr(graph, "invoke")
    assert hasattr(graph, "get_graph")


def test_build_graph_default_has_checkpointer() -> None:
    g = build_graph()
    assert g is not None
    assert getattr(g, "checkpointer", None) is not None


def test_build_graph_false_has_no_checkpointer() -> None:
    g = build_graph(False)
    assert g is not None
    assert getattr(g, "checkpointer", None) is None


def test_starter_domains() -> None:
    assert STARTER_DOMAINS == frozenset(
        {
            "privacy",
            "competition",
            "youth_safety",
            "ip",
            "accessibility",
        }
    )


def test_research_input_rejects_empty_jurisdictions() -> None:
    with pytest.raises((ValidationError, ValueError)):
        ResearchInput(jurisdictions=[], domains=["privacy"])


def test_research_input_rejects_empty_domains() -> None:
    with pytest.raises((ValidationError, ValueError)):
        ResearchInput(jurisdictions=["EU"], domains=[])


def test_normalize_domain_aliases() -> None:
    assert normalize_domain("IP") == "ip"
    assert normalize_domain("intellectual property") == "ip"
    assert normalize_domain("Youth Safety") == "youth_safety"
    assert normalize_domain("privacy") == "privacy"
