"""Meta legal research graph — Studio entry and script builder.

Topology (no HITL):
  START → ingest_input → plan_cells
    → Send(research_cell) per cell (or skip to write_dossier when empty/error)
    → validate_cell → aggregate_findings → write_dossier → END
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from langgraph_graph.meta_legal.models import (
    ResearchInput,
    normalize_domain,
    normalize_jurisdiction,
)
from langgraph_graph.meta_legal.nodes.plan_cells import plan_cells
from langgraph_graph.meta_legal.nodes.research_cell import research_cell
from langgraph_graph.meta_legal.nodes.validate_cell import validate_cell
from langgraph_graph.meta_legal.nodes.write_dossier import write_dossier
from langgraph_graph.meta_legal.state import ResearchState


def ingest_input(state: ResearchState) -> dict[str, Any]:
    """Validate and normalize invoke input into canonical state fields."""
    raw_jurisdictions = list(state.get("jurisdictions") or [])
    raw_domains = list(state.get("domains") or [])
    subject = (state.get("subject") or "Meta").strip() or "Meta"
    explicit_cells = [
        dict(cell)
        for cell in (state.get("explicit_cells") or [])
        if isinstance(cell, dict)
    ]

    # When only explicit cells are provided, derive list fields for ResearchInput.
    if explicit_cells and (not raw_jurisdictions or not raw_domains):
        derived_j: list[str] = []
        derived_d: list[str] = []
        seen_j: set[str] = set()
        seen_d: set[str] = set()
        for cell in explicit_cells:
            j_raw = (
                cell.get("jurisdiction")
                or cell.get("jurisdiction_name")
                or cell.get("jurisdiction_id")
                or ""
            )
            d_raw = cell.get("domain") or cell.get("domain_id") or ""
            j_key = str(j_raw).strip()
            d_key = str(d_raw).strip()
            if j_key and j_key not in seen_j:
                seen_j.add(j_key)
                derived_j.append(j_key)
            if d_key and d_key not in seen_d:
                seen_d.add(d_key)
                derived_d.append(d_key)
        if not raw_jurisdictions:
            raw_jurisdictions = derived_j
        if not raw_domains:
            raw_domains = derived_d

    try:
        validated = ResearchInput(
            jurisdictions=raw_jurisdictions,
            domains=raw_domains,
            subject=subject,
        )
    except Exception as exc:  # pydantic ValidationError and ValueError
        return {
            "error": f"invalid input: {exc}",
            "jurisdictions": [],
            "domains": [],
            "subject": subject,
            "explicit_cells": explicit_cells,
            "cells": [],
            "run_id": state.get("run_id") or str(uuid4()),
            "dossier_path": state.get("dossier_path") or "",
        }

    jurisdictions = [normalize_jurisdiction(j) for j in validated.jurisdictions]
    domains = [normalize_domain(d) for d in validated.domains]

    # Deduplicate while preserving order
    jurisdictions = list(dict.fromkeys(jurisdictions))
    domains = list(dict.fromkeys(domains))

    return {
        "jurisdictions": jurisdictions,
        "domains": domains,
        "subject": validated.subject,
        "explicit_cells": explicit_cells,
        "cells": list(state.get("cells") or []),
        "run_id": state.get("run_id") or str(uuid4()),
        "dossier_path": state.get("dossier_path") or "",
        "error": None,
    }



def fanout_cells(state: ResearchState) -> list[Send] | str:
    """Fan out one Send per planned cell, or skip workers when empty/error.

    Returns a list of ``Send("research_cell", payload)`` when there is work,
    otherwise the string ``\"write_dossier\"`` so an empty/error run still
    produces a dossier path.
    """
    if state.get("error"):
        return "write_dossier"

    cells = state.get("cells") or []
    if not cells:
        return "write_dossier"

    subject = state.get("subject") or "Meta"
    sends: list[Send] = []
    for c in cells:
        payload = c.model_dump() if hasattr(c, "model_dump") else dict(c)
        payload.setdefault("subject", subject)
        sends.append(Send("research_cell", payload))
    return sends


def aggregate_findings(state: ResearchState) -> dict[str, Any]:
    """Passthrough reduce node after parallel validate fan-in.

    Reducers on ``accepted`` / ``rejected`` / ``drafts`` / ``cell_errors``
    already merged worker output. Returning those lists again would
    double-append via ``operator.add`` — so this is intentionally a no-op.
    """
    _ = state  # state is available for future count/summary fields
    return {}


def _assemble_graph() -> StateGraph:
    """Build the StateGraph topology (nodes/edges only; not compiled)."""
    g = StateGraph(ResearchState)
    g.add_node("ingest_input", ingest_input)
    g.add_node("plan_cells", plan_cells)
    g.add_node("research_cell", research_cell)
    g.add_node("validate_cell", validate_cell)
    g.add_node("aggregate_findings", aggregate_findings)
    g.add_node("write_dossier", write_dossier)

    g.add_edge(START, "ingest_input")
    g.add_edge("ingest_input", "plan_cells")
    g.add_conditional_edges(
        "plan_cells",
        fanout_cells,
        ["research_cell", "write_dossier"],
    )
    g.add_edge("research_cell", "validate_cell")
    g.add_edge("validate_cell", "aggregate_findings")
    g.add_edge("aggregate_findings", "write_dossier")
    g.add_edge("write_dossier", END)
    return g


def build_graph(checkpointer: Any = None):
    """Compile the graph for local CLI / scripts.

    Defaults to MemorySaver when checkpointer is None. Pass an explicit
    checkpointer to use it, or checkpointer=False to compile with none.
    """
    if checkpointer is None:
        checkpointer = MemorySaver()
    elif checkpointer is False:
        checkpointer = None
    return _assemble_graph().compile(checkpointer=checkpointer)


# LangSmith Studio / `langgraph dev` entry — Agent Server injects a checkpointer.
graph = _assemble_graph().compile()
