"""U1: jurisdiction resolver graph compiles and canonicalizes inputs."""

from __future__ import annotations

from langgraph_graph.jurisdiction import JurisdictionState
from langgraph_graph.jurisdiction.graph import build_graph, graph


def test_studio_graph_compiles() -> None:
    assert graph is not None
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


def test_canonicalizes_aliases_and_names() -> None:
    app = build_graph(False)
    result = app.invoke(
        {
            "jurisdictions": ["EU", "United States", "California", "us"],
            "subject": "Meta",
        }
    )

    names = list(result.get("jurisdictions") or [])
    assert "European Union" in names
    assert "United States" in names
    assert "California" in names
    # Alias deduplication should collapse "us" and "United States".
    assert len([n for n in names if n == "United States"]) == 1
    assert not result.get("error")
    assert result.get("run_id")


def test_returns_ids_and_filters_unknowns_strictly() -> None:
    app = build_graph(False)
    result = app.invoke(
        {
            "requested": ["EU", "Fakeland"],
            "strict": True,
        }
    )

    assert result.get("error")
    assert "Fakeland" in (result.get("unresolved") or [])
    assert "European Union" in (result.get("jurisdictions") or [])
    assert "european_union" in (result.get("jurisdiction_ids") or [])


def test_non_strict_keeps_known_and_records_unknown() -> None:
    app = build_graph(False)
    result = app.invoke(
        {
            "jurisdictions": ["EU", "Fakeland"],
            "strict": False,
        }
    )

    assert not result.get("error")
    assert "European Union" in result["jurisdictions"]
    assert "Fakeland" in (result.get("unresolved") or [])


def test_level_filter_defaults_to_all_catalog_jurisdictions() -> None:
    app = build_graph(False)
    result = app.invoke({"levels": ["us_state"], "strict": False})

    names = list(result.get("jurisdictions") or [])
    assert "California" in names
    assert "European Union" not in names
    assert not result.get("error")


def test_state_class_is_typed_dict() -> None:
    # Ensures the public API type exists and can be imported.
    assert JurisdictionState is not None
