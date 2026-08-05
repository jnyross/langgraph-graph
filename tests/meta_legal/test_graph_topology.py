"""U6: meta_legal graph topology — Send fan-out, nodes, mocked e2e."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from langgraph_graph.meta_legal.models import make_cell_id

REQUIRED_NODES = {
    "ingest_input",
    "plan_cells",
    "research_cell",
    "validate_cell",
    "write_dossier",
}


def _compiled_node_names(compiled: Any) -> set[str]:
    """Best-effort node name set across LangGraph compiled graph shapes."""
    names: set[str] = set()

    # LangGraph 0.2+/1.x: get_graph().nodes is a dict keyed by name
    try:
        g = compiled.get_graph()
        nodes = getattr(g, "nodes", None)
        if isinstance(nodes, dict):
            names.update(str(k) for k in nodes)
        elif nodes is not None:
            for n in nodes:
                nid = getattr(n, "id", None) or getattr(n, "name", None) or n
                names.add(str(nid))
    except Exception:
        pass

    # Fallback: builder / internal structures
    for attr in ("nodes", "builder"):
        obj = getattr(compiled, attr, None)
        if obj is None:
            continue
        candidate = getattr(obj, "nodes", obj)
        if isinstance(candidate, dict):
            names.update(str(k) for k in candidate)

    # Drop pseudo-nodes
    names.discard("__start__")
    names.discard("__end__")
    names.discard("START")
    names.discard("END")
    return names


def test_compiled_graph_includes_pipeline_nodes() -> None:
    from langgraph_graph.meta_legal.graph import build_graph, graph

    for compiled in (graph, build_graph(False)):
        names = _compiled_node_names(compiled)
        missing = REQUIRED_NODES - names
        assert not missing, f"missing nodes {missing}; have {sorted(names)}"
        assert "aggregate_findings" in names


def test_existing_agent_graph_still_imports() -> None:
    """Unchanged invariant: HITL agent graph still loads."""
    from langgraph_graph.graph import graph as agent_graph

    assert agent_graph is not None
    assert hasattr(agent_graph, "invoke")


def test_package_exports_build_graph_and_graph() -> None:
    from langgraph_graph import meta_legal
    from langgraph_graph.meta_legal import build_graph, graph

    assert callable(build_graph)
    assert graph is not None
    assert meta_legal.graph is graph


def test_fanout_cells_sends_or_skips_to_writer() -> None:
    from langgraph.types import Send

    from langgraph_graph.meta_legal.graph import fanout_cells
    from langgraph_graph.meta_legal.models import ResearchCell

    empty = fanout_cells({"cells": [], "subject": "Meta"})  # type: ignore[arg-type]
    assert empty == "write_dossier"

    errored = fanout_cells({"error": "bad", "cells": []})  # type: ignore[arg-type]
    assert errored == "write_dossier"

    cell = ResearchCell(
        cell_id="eu::privacy",
        jurisdiction="European Union",
        jurisdiction_id="eu",
        domain="privacy",
        domain_id="privacy",
        subject="Meta",
    )
    sends = fanout_cells({"cells": [cell], "subject": "Meta"})  # type: ignore[arg-type]
    assert isinstance(sends, list)
    assert len(sends) == 1
    assert isinstance(sends[0], Send)
    assert sends[0].node == "research_cell"
    assert sends[0].arg["cell_id"] == "eu::privacy"
    assert sends[0].arg["subject"] == "Meta"


def test_mocked_integration_two_cells_writes_dossier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invoke with 2 cells; mock research_cell; real validate + write."""
    import importlib

    from langgraph_graph.meta_legal.models import LawRecordDraft

    # Package exports ``graph`` (compiled), which shadows the submodule name.
    graph_module = importlib.import_module("langgraph_graph.meta_legal.graph")

    monkeypatch.setenv("DOSSIER_ROOT", str(tmp_path))

    def _fake_research(state: Any) -> dict[str, list[Any]]:
        data = state if isinstance(state, dict) else {}
        if hasattr(state, "model_dump"):
            data = state.model_dump()
        cell_id = str(data.get("cell_id") or "")
        jurisdiction_id = str(data.get("jurisdiction_id") or "")
        domain_id = str(data.get("domain_id") or "")
        # One strong draft (accept) + one weak (reject) per cell
        good = LawRecordDraft(
            title=f"Primary Law {cell_id}",
            jurisdiction_id=jurisdiction_id,
            domain_id=domain_id,
            cell_id=cell_id,
            meta_nexus="platform_obligation",
            meta_nexus_rationale="Applies to large online platforms including Meta.",
            citation="Art. 1",
            source_url=f"https://example.test/law/{cell_id.replace('::', '/')}",
            source_type="primary",
            excerpt="Platform providers shall comply.",
            confidence=0.9,
        )
        weak = LawRecordDraft(
            title="",  # missing_title → rejected
            jurisdiction_id=jurisdiction_id,
            domain_id=domain_id,
            cell_id=cell_id,
            meta_nexus="platform_obligation",
            source_url="https://example.test/weak",
        )
        return {"drafts": [good, weak], "cell_errors": []}

    # Patch the symbol used when assembling the graph, then rebuild.
    monkeypatch.setattr(graph_module, "research_cell", _fake_research)

    app = graph_module.build_graph(False)
    result = app.invoke(
        {
            "jurisdictions": ["European Union", "United States"],
            "domains": ["privacy"],
            "subject": "Meta",
        }
    )

    dossier_path = result.get("dossier_path") or ""
    assert dossier_path, f"expected dossier_path, got keys={sorted(result)}"
    assert Path(dossier_path).is_dir()
    assert (Path(dossier_path) / "manifest.json").is_file()
    assert (Path(dossier_path) / "index.json").is_file()

    accepted = list(result.get("accepted") or [])
    rejected = list(result.get("rejected") or [])
    # 2 cells × 1 good draft
    assert len(accepted) == 2, f"accepted={accepted!r}"
    # 2 cells × 1 weak draft
    assert len(rejected) == 2, f"rejected={rejected!r}"
    assert all(getattr(a, "validated", True) for a in accepted)
    assert all("missing_title" in (getattr(r, "reason", "") or "") for r in rejected)

    cells = list(result.get("cells") or [])
    assert len(cells) == 2
    cell_ids = {(c.cell_id if hasattr(c, "cell_id") else c.get("cell_id")) for c in cells}
    assert make_cell_id("european_union", "privacy") in cell_ids or any(
        "privacy" in str(cid) for cid in cell_ids
    )
    assert result.get("run_id")
    assert not result.get("error")


def test_empty_cells_still_writes_dossier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid / empty plan path skips workers and still writes dossier."""
    from langgraph_graph.meta_legal.graph import build_graph

    monkeypatch.setenv("DOSSIER_ROOT", str(tmp_path))
    app = build_graph(False)

    # Force empty cells via planner error path: empty jurisdictions rejected at ingest
    result = app.invoke(
        {
            "jurisdictions": [],
            "domains": ["privacy"],
            "subject": "Meta",
        }
    )
    dossier_path = result.get("dossier_path") or ""
    # ingest sets error and empty cells → fanout skips to write_dossier
    assert result.get("error")
    assert dossier_path, f"expected empty-run dossier, got {result!r}"
    assert Path(dossier_path).is_dir()
