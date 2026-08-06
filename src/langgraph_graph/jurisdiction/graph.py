"""Jurisdiction resolver graph — validates and canonicalizes jurisdiction lists.

Topology:
  START -> ingest_input -> resolve_jurisdictions -> validate -> END

This graph is intended to run ahead of a law-finder (or meta_legal research)
process so the downstream graph receives a clean, catalog-backed list of
jurisdictions.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from langgraph_graph.meta_legal.jurisdictions import (
    VALID_LEVELS,
    list_jurisdiction_names,
    load_catalog,
    resolve_jurisdiction_names,
)

from .state import JurisdictionState


def ingest_input(state: JurisdictionState) -> dict[str, Any]:
    """Normalize the invoke payload and seed working state."""
    # Accept either the canonical output key or the explicit input key.
    raw_requested = list(
        state.get("requested")
        or state.get("jurisdictions")
        or []
    )
    subject = (state.get("subject") or "Meta").strip() or "Meta"
    run_id = state.get("run_id") or str(uuid4())

    levels = list(state.get("levels") or [])
    if not levels:
        levels = sorted(VALID_LEVELS)

    # Preserve order while deduplicating and dropping empty strings.
    requested: list[str] = []
    seen: set[str] = set()
    for raw in raw_requested:
        label = str(raw).strip()
        if not label:
            continue
        key = label.casefold()
        if key not in seen:
            seen.add(key)
            requested.append(label)

    strict = state.get("strict", True)
    if not isinstance(strict, bool):
        strict = bool(strict)

    return {
        "subject": subject,
        "requested": requested,
        "levels": levels,
        "strict": strict,
        "run_id": run_id,
        "resolved": [],
        "unresolved": [],
        "jurisdiction_ids": [],
        "jurisdictions": [],
        "error": None,
    }


def resolve_jurisdictions(state: JurisdictionState) -> dict[str, Any]:
    """Match requested labels to the catalog, or return the full filtered catalog."""
    requested = state.get("requested") or []
    levels = state.get("levels") or []

    if requested:
        resolved_entries, unresolved = resolve_jurisdiction_names(
            requested,
            levels=levels,
        )
    else:
        # No explicit request: surface every catalog jurisdiction for the levels.
        catalog = load_catalog()
        all_names = list_jurisdiction_names(catalog, levels=levels)
        by_name = {
            str(item.get("name")): item
            for item in catalog.get("jurisdictions", [])
            if str(item.get("name", "")) and str(item.get("id", ""))
        }
        resolved_entries = [
            by_name[name]
            for name in dict.fromkeys(all_names)
            if name in by_name
        ]
        unresolved = []

    resolved_names = [str(entry.get("name")) for entry in resolved_entries]
    resolved_ids = [str(entry.get("id")) for entry in resolved_entries]

    return {
        "resolved": resolved_names,
        "jurisdiction_ids": resolved_ids,
        "unresolved": unresolved,
        "jurisdictions": resolved_names,
    }


def validate(state: JurisdictionState) -> dict[str, Any]:
    """Fail hard in strict mode when any label cannot be resolved."""
    resolved = state.get("resolved") or []
    unresolved = state.get("unresolved") or []
    strict = state.get("strict", True)

    error = None
    if not resolved:
        error = "no valid jurisdictions resolved"
    elif strict and unresolved:
        error = f"unresolved jurisdictions: {', '.join(unresolved)}"

    return {
        "jurisdictions": resolved,
        "error": error,
    }


def _assemble_graph() -> StateGraph:
    """Build the StateGraph topology (nodes/edges only; not compiled)."""
    g = StateGraph(JurisdictionState)
    g.add_node("ingest_input", ingest_input)  # type: ignore[type-var]
    g.add_node("resolve_jurisdictions", resolve_jurisdictions)  # type: ignore[type-var]
    g.add_node("validate", validate)  # type: ignore[type-var]

    g.add_edge(START, "ingest_input")
    g.add_edge("ingest_input", "resolve_jurisdictions")
    g.add_edge("resolve_jurisdictions", "validate")
    g.add_edge("validate", END)
    return g


def build_graph(checkpointer: Any = None):
    """Compile the graph for local CLI / scripts.

    Defaults to MemorySaver when checkpointer is None. Pass False to compile
    with no checkpointer, or an explicit checkpointer to use it.
    """
    if checkpointer is None:
        checkpointer = MemorySaver()
    elif checkpointer is False:
        checkpointer = None
    return _assemble_graph().compile(checkpointer=checkpointer)


# LangSmith Studio / `langgraph dev` entry — Agent Server injects a checkpointer.
graph = _assemble_graph().compile()
