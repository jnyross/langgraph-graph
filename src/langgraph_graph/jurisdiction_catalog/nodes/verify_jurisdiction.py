"""Verify Meta availability and jurisdictional law-making authority."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from langgraph_graph.jurisdiction_catalog.models import (
    Assessment,
    Candidate,
    Evidence,
    Verdict,
    Verification,
)
from langgraph_graph.jurisdiction_catalog.state import CatalogState
from langgraph_graph.meta_legal.llm import get_llm
from langgraph_graph.meta_legal.tools.fetch import fetch_url
from langgraph_graph.meta_legal.tools.search import web_search

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts/verify.md"


def _evidence_mentions_candidate(candidate: Candidate, evidence: Evidence) -> bool:
    """Return whether a source names the candidate or a common alias."""
    haystack = " ".join((evidence.title, evidence.url, evidence.snippet)).lower()
    aliases = {
        candidate.name.lower(),
        candidate.id.replace("_", " ").lower(),
    }
    if "," in candidate.name:
        aliases.add(candidate.name.split(",", 1)[0].strip().lower())
    if candidate.id == "iran_islamic_republic_of":
        aliases.update({"iran", "islamic republic of iran"})
    if candidate.id == "united_states":
        aliases.update({"united states", "usa", "u.s.", "us"})
    return any(alias in haystack for alias in aliases if alias)


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
        queries = [
            (
                f'"{candidate.name}" Facebook Instagram WhatsApp availability '
                "blocked access residents"
            ),
            (
                f'"{candidate.name}" data protection regulator platform privacy law '
                "competition youth safety intellectual property accessibility"
            ),
            f'"{candidate.name}" Meta jurisdiction',
        ]
        seen_urls: set[str] = set()
        for query in queries[:2]:
            results = web_search(query, max_results=8)
            for result in results[:8]:
                url = result.get("url", "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                text = fetch_url(url, max_chars=2500) if url else ""
                candidate_evidence = Evidence(
                    url=url,
                    title=result.get("title", ""),
                    snippet=(text or result.get("snippet", ""))[:500],
                )
                if _evidence_mentions_candidate(candidate, candidate_evidence):
                    evidence.append(candidate_evidence)
        if not evidence:
            results = web_search(queries[2], max_results=8)
            for result in results[:8]:
                url = result.get("url", "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                text = fetch_url(url, max_chars=2500) if url else ""
                candidate_evidence = Evidence(
                    url=url,
                    title=result.get("title", ""),
                    snippet=(text or result.get("snippet", ""))[:500],
                )
                if _evidence_mentions_candidate(candidate, candidate_evidence):
                    evidence.append(candidate_evidence)
    except Exception as exc:
        errors.append(f"evidence tools failed: {exc}")
    if not evidence:
        errors.append("no relevant evidence retrieved for jurisdiction")
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
        structured = llm.with_structured_output(Assessment)
        response = structured.invoke(
            [
                {"role": "system", "content": _prompt(candidate, evidence)},
                {"role": "user", "content": "Assess this jurisdiction from the supplied evidence."},
            ]
        )
        assessment = response
        verdict: Verdict
        if assessment.services_available and assessment.authority_exists:
            verdict = "include" if assessment.verdict == "include" else "uncertain"
        elif (
            assessment.verdict == "exclude" and assessment.confidence >= 0.75 and len(evidence) >= 2
        ):
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
