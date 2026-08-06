"""Evidence-backed jurisdiction catalog graph (no HITL)."""
# ruff: noqa: E501

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from .nodes import (
    aggregate,
    diff_catalog,
    discover_candidates,
    ingest_input,
    plan_candidates,
    validate_candidate,
    verify_jurisdiction,
    write_catalog,
)
from .state import CatalogState


def fanout_candidates(state: CatalogState) -> list[Send] | str:
    if state.get("error") or not state.get("candidates"):
        return "aggregate"
    return [Send("verify_jurisdiction", {"candidate": candidate, **({"subject": state.get("subject")} if state.get("subject") else {})}) for candidate in state["candidates"]]


def _assemble_graph() -> StateGraph:
    graph = StateGraph(CatalogState)
    for name, fn in {"ingest_input": ingest_input, "plan_candidates": plan_candidates, "discover_candidates": discover_candidates, "verify_jurisdiction": verify_jurisdiction, "validate_candidate": validate_candidate, "aggregate": aggregate, "diff_catalog": diff_catalog, "write_catalog": write_catalog}.items():
        graph.add_node(name, fn)  # type: ignore[type-var]
    graph.add_edge(START, "ingest_input")
    graph.add_edge("ingest_input", "plan_candidates")
    graph.add_edge("plan_candidates", "discover_candidates")
    graph.add_conditional_edges("discover_candidates", fanout_candidates, ["verify_jurisdiction", "aggregate"])
    graph.add_edge("verify_jurisdiction", "validate_candidate")
    graph.add_edge("validate_candidate", "aggregate")
    graph.add_edge("aggregate", "diff_catalog")
    graph.add_edge("diff_catalog", "write_catalog")
    graph.add_edge("write_catalog", END)
    return graph


def build_graph(checkpointer: Any = None):
    if checkpointer is None:
        checkpointer = MemorySaver()
    elif checkpointer is False:
        checkpointer = None
    return _assemble_graph().compile(checkpointer=checkpointer)


graph = _assemble_graph().compile()
