"""Pydantic models and normalization helpers for the Meta legal research graph."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

STARTER_DOMAINS: frozenset[str] = frozenset(
    {
        "privacy",
        "competition",
        "youth_safety",
        "ip",
        "accessibility",
    }
)

DOMAIN_ALIASES: dict[str, str] = {
    "privacy": "privacy",
    "data protection": "privacy",
    "data_protection": "privacy",
    "competition": "competition",
    "antitrust": "competition",
    "youth safety": "youth_safety",
    "youth_safety": "youth_safety",
    "child safety": "youth_safety",
    "child_safety": "youth_safety",
    "ip": "ip",
    "intellectual property": "ip",
    "intellectual_property": "ip",
    "copyright": "ip",
    "trademark": "ip",
    "accessibility": "accessibility",
    "a11y": "accessibility",
}

JURISDICTION_ALIASES: dict[str, str] = {
    "eu": "European Union",
    "european union": "European Union",
    "us": "United States",
    "usa": "United States",
    "u.s.": "United States",
    "u.s.a.": "United States",
    "united states": "United States",
    "united states of america": "United States",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "united kingdom": "United Kingdom",
    "gb": "United Kingdom",
    "great britain": "United Kingdom",
    "ca": "California",
    "calif": "California",
    "california": "California",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: str) -> str:
    """Filesystem-safe slug: lowercase, non-alnum → underscore, collapse runs."""
    text = value.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[-\s]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unknown"


def normalize_domain(value: str) -> str:
    """Canonicalize a domain label to a slug (starter aliases preferred)."""
    key = " ".join(value.strip().lower().split())
    if key in DOMAIN_ALIASES:
        return DOMAIN_ALIASES[key]
    underscored = key.replace(" ", "_")
    if underscored in DOMAIN_ALIASES:
        return DOMAIN_ALIASES[underscored]
    return slugify(value)


def normalize_jurisdiction(value: str) -> str:
    """Canonicalize a jurisdiction label (no expansion to members/states)."""
    key = " ".join(value.strip().lower().split())
    if key in JURISDICTION_ALIASES:
        return JURISDICTION_ALIASES[key]
    return " ".join(value.strip().split())


def make_cell_id(jurisdiction_id: str, domain_id: str) -> str:
    """Stable research-cell identity: `{jurisdiction_id}::{domain_id}`."""
    return f"{jurisdiction_id}::{domain_id}"


class ResearchInput(BaseModel):
    """Invoke input for the meta_legal graph."""

    jurisdictions: list[str] = Field(..., min_length=1)
    domains: list[str] = Field(..., min_length=1)
    subject: str = "Meta"

    @field_validator("jurisdictions", "domains")
    @classmethod
    def _reject_empty_items(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("list must not be empty")
        cleaned = [item.strip() for item in v if item and str(item).strip()]
        if not cleaned:
            raise ValueError("list must contain at least one non-empty string")
        return cleaned

    @model_validator(mode="after")
    def _require_non_empty_lists(self) -> ResearchInput:
        if not self.jurisdictions:
            raise ValueError("jurisdictions must not be empty")
        if not self.domains:
            raise ValueError("domains must not be empty")
        return self


class ResearchCell(BaseModel):
    """One jurisdiction × domain research unit."""

    cell_id: str
    jurisdiction: str
    jurisdiction_id: str
    domain: str
    domain_id: str
    status: Literal["pending", "researching", "validating", "done", "error"] = "pending"
    subject: str = "Meta"


class LawRecordDraft(BaseModel):
    """Worker-emitted law finding prior to validation."""

    law_id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    jurisdiction_id: str
    domain_id: str
    meta_nexus: str = Field(
        default="platform_obligation",
        description="named_party | platform_obligation | sector_rule | other",
    )
    meta_nexus_rationale: str = ""
    citation: str = ""
    source_url: str = ""
    source_type: Literal["primary", "secondary"] = "secondary"
    excerpt: str = ""
    language: str = "en"
    effective_date: str | None = None
    status: str | None = None
    retrieved_at: str = Field(default_factory=_utc_now_iso)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    worker_model: str = ""
    cell_id: str = ""


class LawRecord(LawRecordDraft):
    """Validated law record accepted into the dossier."""

    validated: bool = True


class CellError(BaseModel):
    """Structured per-cell failure (does not abort the whole run)."""

    cell_id: str
    message: str
    stage: str = "research"


class RejectedRecord(BaseModel):
    """A draft rejected by validation, with reason."""

    record: LawRecordDraft
    reason: str
    cell_id: str = ""


class ValidationResult(BaseModel):
    """Outcome of validating one cell's drafts."""

    cell_id: str
    accepted: list[LawRecord] = Field(default_factory=list)
    rejected: list[RejectedRecord] = Field(default_factory=list)


class DossierManifest(BaseModel):
    """Top-level index written with a research run."""

    run_id: str
    subject: str = "Meta"
    jurisdictions: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    cell_ids: list[str] = Field(default_factory=list)
    accepted_count: int = 0
    rejected_count: int = 0
    error_count: int = 0
    dossier_path: str = ""
    created_at: str = Field(default_factory=_utc_now_iso)
