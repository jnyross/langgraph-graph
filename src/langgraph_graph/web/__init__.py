"""Web aggregation package for the law-matrix frontend."""

from langgraph_graph.web.aggregator import (
    build_matrix,
    collect_all_laws,
    discover_runs,
    generate_matrix_json,
    load_manifest,
)

__all__ = [
    "build_matrix",
    "collect_all_laws",
    "discover_runs",
    "generate_matrix_json",
    "load_manifest",
]
