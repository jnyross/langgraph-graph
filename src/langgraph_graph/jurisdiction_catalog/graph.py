"""Evidence-backed jurisdiction catalog graph (no HITL)."""

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
    widen_seed,
    write_catalog,
)
from .state import CatalogState


def fanout_candidates(state: CatalogState) -> list[Send] | str:
    """Route planned candidates to evidence workers or continue empty runs."""
    if state.get("error") or not state.get("candidates"):
        return "aggregate"
    return [
        Send("verify_jurisdiction", {"candidate": candidate}) for candidate in state["candidates"]
    ]


def _assemble_graph() -> StateGraph:
    """Build the declarative graph topology."""
    graph = StateGraph(CatalogState)
    graph.add_node("ingest_input", ingest_input)  # type: ignore[type-var]
    graph.add_node("plan_candidates", plan_candidates)  # type: ignore[type-var]
    graph.add_node("discover_candidates", discover_candidates)  # type: ignore[type-var]
    graph.add_node("verify_jurisdiction", verify_jurisdiction)  # type: ignore[type-var]
    graph.add_node("validate_candidate", validate_candidate)  # type: ignore[type-var]
    graph.add_node("widen_seed", widen_seed)  # type: ignore[type-var]
    graph.add_node("aggregate", aggregate)  # type: ignore[type-var]
    graph.add_node("diff_catalog", diff_catalog)  # type: ignore[type-var]
    graph.add_node("write_catalog", write_catalog)  # type: ignore[type-var]
    graph.add_edge(START, "ingest_input")
    graph.add_edge("ingest_input", "plan_candidates")
    graph.add_edge("plan_candidates", "discover_candidates")
    graph.add_conditional_edges(
        "discover_candidates", fanout_candidates, ["verify_jurisdiction", "aggregate"]
    )
    graph.add_edge("verify_jurisdiction", "aggregate")
    graph.add_edge("aggregate", "validate_candidate")
    graph.add_edge("validate_candidate", "widen_seed")
    graph.add_edge("widen_seed", "diff_catalog")
    graph.add_edge("diff_catalog", "write_catalog")
    graph.add_edge("write_catalog", END)
    return graph


def build_graph(checkpointer: Any = None):
    """Compile the graph for scripts, defaulting to an in-memory checkpointer."""
    if checkpointer is None:
        checkpointer = MemorySaver()
    elif checkpointer is False:
        checkpointer = None
    return _assemble_graph().compile(checkpointer=checkpointer)


graph = _assemble_graph().compile()
