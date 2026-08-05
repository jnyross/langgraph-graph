"""Langgraph Graph — personal-automation runtime for AI agentic graphs with HITL.

Public API:
    build_graph()  -> CompiledGraph with a checkpointer and interrupt-based HITL.
    graph          -> Studio entry (compiled, no custom checkpointer).
    AgentState     -> typed graph state.
"""

from langgraph_graph.graph import build_graph, graph
from langgraph_graph.state import AgentState

__all__ = ["AgentState", "build_graph", "graph"]
__version__ = "0.1.0"
