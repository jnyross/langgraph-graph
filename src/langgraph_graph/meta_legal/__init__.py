"""Meta legal research graph — parallel dossier builder (no HITL).

Public API:
    build_graph()     -> CompiledGraph with optional checkpointer.
    graph             -> Studio entry (compiled, no custom checkpointer).
    ResearchInput     -> invoke input model.
    ResearchState     -> typed graph state.
    STARTER_DOMAINS   -> canonical domain slug set.
"""

from langgraph_graph.meta_legal.graph import build_graph, graph
from langgraph_graph.meta_legal.models import (
    DOMAIN_ALIASES,
    STARTER_DOMAINS,
    ResearchCell,
    ResearchInput,
    make_cell_id,
    normalize_domain,
    normalize_jurisdiction,
)
from langgraph_graph.meta_legal.state import ResearchState

__all__ = [
    "DOMAIN_ALIASES",
    "STARTER_DOMAINS",
    "ResearchCell",
    "ResearchInput",
    "ResearchState",
    "build_graph",
    "graph",
    "make_cell_id",
    "normalize_domain",
    "normalize_jurisdiction",
]
