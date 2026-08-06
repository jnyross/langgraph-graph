"""LangGraph definition for the news_radar forward-looking intelligence pipeline."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from langgraph_graph.news_radar.nodes.cluster_signals import cluster_signals
from langgraph_graph.news_radar.nodes.ingest_input import ingest_input
from langgraph_graph.news_radar.nodes.link_known_laws import link_known_laws
from langgraph_graph.news_radar.nodes.load_context import load_context
from langgraph_graph.news_radar.nodes.plan_cells import plan_cells
from langgraph_graph.news_radar.nodes.scan_cell import scan_cell
from langgraph_graph.news_radar.nodes.validate_signal import validate_signal
from langgraph_graph.news_radar.nodes.write_radar import write_radar
from langgraph_graph.news_radar.state import RadarState


def _aggregate_signals(state: RadarState) -> dict:
    """No-op fan-in: all branch outputs are already merged via reducers."""
    return {}


def fanout_cells(state: RadarState) -> list[Send] | str:
    """Map each watch cell onto a parallel scan_cell invocation."""
    if state.get("error"):
        return "write_radar"
    cells = state.get("cells", [])
    if not cells:
        return "write_radar"
    return [Send("scan_cell", {**dict(state), **c.model_dump()}) for c in cells]


def _assemble_graph() -> StateGraph:
    """Build the news_radar StateGraph topology (not compiled)."""
    g = StateGraph(RadarState)

    g.add_node("ingest_input", ingest_input)
    g.add_node("load_context", load_context)
    g.add_node("plan_cells", plan_cells)
    g.add_node("scan_cell", scan_cell)
    g.add_node("validate_signal", validate_signal)
    g.add_node("aggregate_signals", _aggregate_signals)
    g.add_node("cluster_signals", cluster_signals)
    g.add_node("link_known_laws", link_known_laws)
    g.add_node("write_radar", write_radar)

    g.add_edge(START, "ingest_input")
    g.add_edge("ingest_input", "load_context")
    g.add_edge("load_context", "plan_cells")
    g.add_conditional_edges("plan_cells", fanout_cells, ["scan_cell", "write_radar"])
    g.add_edge("scan_cell", "validate_signal")
    g.add_edge("validate_signal", "aggregate_signals")
    g.add_edge("aggregate_signals", "cluster_signals")
    g.add_edge("cluster_signals", "link_known_laws")
    g.add_edge("link_known_laws", "write_radar")
    g.add_edge("write_radar", END)
    return g


def build_graph(checkpointer: Any = None):
    """Compile the graph for local CLI / scripts.

    Defaults to MemorySaver when ``checkpointer`` is None. Pass an explicit
    checkpointer to use it, or ``checkpointer=False`` to compile with none.
    """
    if checkpointer is None:
        checkpointer = MemorySaver()
    elif checkpointer is False:
        checkpointer = None
    return _assemble_graph().compile(checkpointer=checkpointer)


# Studio export: no custom checkpointer.
graph = _assemble_graph().compile()
