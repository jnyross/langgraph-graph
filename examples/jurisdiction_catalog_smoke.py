"""Offline-safe jurisdiction catalog graph smoke run."""
# ruff: noqa: E501

from __future__ import annotations

from langgraph_graph.jurisdiction_catalog import build_graph

if __name__ == "__main__":
    result = build_graph(False).invoke(
        {"levels": ["supranational", "country", "state_province", "us_state", "us_city", "city"]}
    )
    print(result.get("output_path", "catalog run did not produce output"))
