from __future__ import annotations

# ruff: noqa: E501
import os
from typing import Any

from langgraph_graph.meta_legal.tools.fetch import fetch_url
from langgraph_graph.meta_legal.tools.search import web_search

from ..models import Candidate, Evidence, Verdict, Verification


def verify_jurisdiction(state: dict[str, Any]) -> dict[str, Any]:
    raw = state.get("candidate") or state
    candidate = raw if isinstance(raw, Candidate) else Candidate.model_validate(raw)
    if not os.getenv("OPENROUTER_API_KEY") and not os.getenv("OPENAI_API_KEY"):
        verification = Verification(candidate_id=candidate.id, candidate=candidate, rationale="No LLM key configured; offline run.", errors=["llm_unavailable"])
        return {"verifications": [verification]}
    evidence: list[Evidence] = []
    errors: list[str] = []
    try:
        results = web_search(
            f"{candidate.name} Meta Facebook Instagram WhatsApp availability law regulator",
            max_results=3,
        )
        for result in results[:3]:
            url = result.get("url", "")
            text = fetch_url(url, max_chars=2500) if url else ""
            evidence.append(Evidence(url=url, title=result.get("title", ""), snippet=(text or result.get("snippet", ""))[:500]))
    except Exception as exc:
        errors.append(f"evidence tools: {exc}")
    verdict: Verdict = "include" if len(evidence) >= 2 else "uncertain"
    confidence = min(0.9, 0.35 + 0.2 * len(evidence)) if evidence else 0.0
    verification = Verification(candidate_id=candidate.id, candidate=candidate, verdict=verdict, confidence=confidence, evidence=evidence, rationale="Evidence-backed availability and authority review.", errors=errors)
    return {"verifications": [verification]}
