"""Verify Meta availability and jurisdictional law-making authority."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from langgraph_graph.meta_legal.llm import get_llm
from langgraph_graph.meta_legal.tools.fetch import fetch_url
from langgraph_graph.meta_legal.tools.search import web_search

from ..models import Assessment, Candidate, Evidence, Verdict, Verification
from ..state import CatalogState

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts/verify.md"


class _Assessment(BaseModel):
    """LLM-facing structured verification response."""

    services_available: bool
    authority_exists: bool
    verdict: str
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


def _prompt(candidate: Candidate, evidence: list[Evidence]) -> str:
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    material = "\n\n".join(
        f"TITLE: {item.title}\nURL: {item.url}\nSNIPPET: {item.snippet}" for item in evidence
    )
    return (
        template.replace("{{subject}}", "Meta")
        + f"\n\nJURISDICTION: {candidate.name} ({candidate.id})\n"
        + f"EVIDENCE:\n{material}"
    )


def verify_jurisdiction(state: CatalogState) -> dict[str, Any]:
    """Search, fetch, and structurally assess one candidate; never raises."""
    raw = state.get("candidate") or state
    candidate = raw if isinstance(raw, Candidate) else Candidate.model_validate(raw)
    if not os.getenv("OPENROUTER_API_KEY") and not os.getenv("OPENAI_API_KEY"):
        verification = Verification(
            candidate_id=candidate.id,
            candidate=candidate,
            rationale="No LLM key configured; offline run.",
            errors=["llm_unavailable"],
        )
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
            evidence.append(
                Evidence(
                    url=url,
                    title=result.get("title", ""),
                    snippet=(text or result.get("snippet", ""))[:500],
                )
            )
    except Exception as exc:
        errors.append(f"evidence tools failed: {exc}")
    if not evidence:
        errors.append("no evidence retrieved")
        return {
            "verifications": [
                Verification(
                    candidate_id=candidate.id,
                    candidate=candidate,
                    evidence=evidence,
                    errors=errors,
                )
            ]
        }
    try:
        llm = get_llm()
        structured = llm.with_structured_output(_Assessment)
        response = structured.invoke(
            [
                {"role": "system", "content": _prompt(candidate, evidence)},
                {"role": "user", "content": "Assess this jurisdiction from the supplied evidence."},
            ]
        )
        assessment = (
            response
            if isinstance(response, Assessment)
            else Assessment.model_validate(
                response.model_dump() if hasattr(response, "model_dump") else response
            )
        )
        verdict: Verdict
        if assessment.services_available and assessment.authority_exists:
            verdict = "include" if assessment.verdict == "include" else "uncertain"
        elif not assessment.services_available or not assessment.authority_exists:
            verdict = "exclude"
        else:
            verdict = "uncertain"
    except Exception as exc:
        errors.append(f"llm verification failed: {exc}")
        assessment = None
    if assessment is None:
        verification = Verification(
            candidate_id=candidate.id,
            candidate=candidate,
            evidence=evidence,
            errors=errors,
        )
    else:
        verification = Verification(
            candidate_id=candidate.id,
            candidate=candidate,
            verdict=verdict,
            confidence=assessment.confidence,
            evidence=evidence,
            rationale=assessment.rationale,
            errors=errors,
        )
    return {"verifications": [verification]}
