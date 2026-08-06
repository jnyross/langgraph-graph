"""Models and deterministic helpers for jurisdiction catalog research."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from langgraph_graph.meta_legal.models import slugify

SUPPORTED_LEVELS = frozenset(
    {"supranational", "country", "us_state", "us_city", "state_province", "city"}
)
Verdict = Literal["include", "exclude", "uncertain"]


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Candidate(BaseModel):
    id: str
    name: str
    level: str
    parent_id: str | None = None
    domains_priority: list[str] = Field(default_factory=lambda: ["all"])
    rationale: str = ""
    source: Literal["seed", "current_catalog", "discovered"] = "seed"


class Evidence(BaseModel):
    url: str
    title: str = ""
    snippet: str = ""
    retrieved_at: str = Field(default_factory=now_iso)


class Verification(BaseModel):
    candidate_id: str
    candidate: Candidate | None = None
    verdict: Verdict = "uncertain"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list)
    rationale: str = ""
    errors: list[str] = Field(default_factory=list)


class Assessment(BaseModel):
    """Structured LLM assessment of availability and legal authority."""

    services_available: bool
    authority_exists: bool
    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


class CatalogDiff(BaseModel):
    added: list[dict] = Field(default_factory=list)
    removed: list[dict] = Field(default_factory=list)
    changed: list[dict] = Field(default_factory=list)
    unchanged: list[dict] = Field(default_factory=list)
    excluded: list[dict] = Field(default_factory=list)


def candidate_id(name: str, level: str, parent_id: str | None = None) -> str:
    """Slug with parent-aware disambiguation for country/subdivision collisions."""
    base = slugify(name)
    if parent_id and level not in {"country", "supranational"}:
        return f"{base}_{slugify(parent_id)}"
    return base
