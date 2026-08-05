"""Langgraph Graph — personal-automation runtime for AI agentic graphs with HITL.

Public API:
    build_graph()  -> CompiledGraph with a checkpointer and interrupt-based HITL.
    AgentState     -> typed graph state.
"""

from langgraph_graph.state import AgentState
from langgraph_graph.graph import build_graph

__all__ = ["AgentState", "build_graph"]
__version__ = "0.1.0"
