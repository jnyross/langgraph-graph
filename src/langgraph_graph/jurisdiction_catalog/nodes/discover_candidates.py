"""Optionally discover additional candidates with search and an LLM."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from langgraph_graph.meta_legal.llm import get_llm
from langgraph_graph.meta_legal.tools.fetch import fetch_url
from langgraph_graph.meta_legal.tools.search import web_search

from ..models import Candidate, candidate_id
from ..state import CatalogState

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts/discover.md"


class _Proposal(BaseModel):
    """LLM-facing candidate proposal."""

    name: str
    level: str
    parent_id: str | None = None
    rationale: str = ""
    domains_priority: list[str] = Field(default_factory=lambda: ["all"])


class _DiscoveryResponse(BaseModel):
    """Structured discovery response."""

    candidates: list[_Proposal] = Field(default_factory=list)


def discover_candidates(state: CatalogState) -> dict[str, Any]:
    """Discover additions only when enabled and a model key is configured."""
    if not state.get("discover_extra"):
        return {}
    if not os.getenv("OPENROUTER_API_KEY") and not os.getenv("OPENAI_API_KEY"):
        return {}
    errors: list[str] = []
    try:
        results = web_search(
            "new supranational online platform privacy regulator jurisdiction "
            "subnational social media law",
            max_results=5,
        )
        material = []
        for result in results:
            url = result.get("url", "")
            text = fetch_url(url, max_chars=1800) if url else ""
            material.append(f"TITLE: {result.get('title', '')}\nURL: {url}\n{text[:600]}")
        prompt = _PROMPT_PATH.read_text(encoding="utf-8")
        response = (
            get_llm()
            .with_structured_output(_DiscoveryResponse)
            .invoke(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "\n\n".join(material)},
                ]
            )
        )
        parsed = (
            response
            if isinstance(response, _DiscoveryResponse)
            else _DiscoveryResponse.model_validate(response)
        )
    except Exception as exc:
        errors.append(f"candidate discovery failed: {exc}")
        return {"errors": errors}
    existing = {item.id for item in state.get("candidates") or []}
    additions: list[Candidate] = []
    for proposal in parsed.candidates:
        identifier = candidate_id(proposal.name, proposal.level, proposal.parent_id)
        if identifier in existing:
            continue
        existing.add(identifier)
        additions.append(
            Candidate(
                id=identifier,
                name=proposal.name,
                level=proposal.level,
                parent_id=proposal.parent_id,
                domains_priority=proposal.domains_priority,
                rationale=proposal.rationale,
                source="discovered",
            )
        )
    return {"candidates": [*(state.get("candidates") or []), *additions], "errors": errors}
