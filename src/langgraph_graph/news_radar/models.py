"""Pydantic models and normalization helpers for the news_radar graph."""

from __future__ import annotations

import contextlib
import hashlib
import re
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from langgraph_graph.meta_legal.models import (
    CellError,
    _utc_now_iso,
    make_cell_id,
    normalize_domain,
    normalize_jurisdiction,
    slugify,
)

__all__ = [
    "CellError",
    "RadarInput",
    "WatchCell",
    "SignalDraft",
    "SignalRecord",
    "RejectedSignal",
    "SignalCluster",
    "RadarManifest",
]


class RadarInput(BaseModel):
    """Invoke input for the news_radar graph."""

    jurisdictions: list[str] = Field(..., min_length=1)
    domains: list[str] = Field(..., min_length=1)
    subject: str = "Meta"
    lookback_days: int = Field(default=14, ge=1, le=365)
    levels: list[str] = Field(default_factory=lambda: ["country", "supranational"])
    dossier_run_id: str | None = None
    max_cells: int | None = Field(default=None, ge=1)
    include_rumors: bool = False
    previous_run_id: str | None = None

    @field_validator("jurisdictions", "domains")
    @classmethod
    def _reject_empty_items(cls, v: list[str]) -> list[str]:
        cleaned = [item.strip() for item in v if item and str(item).strip()]
        if not cleaned:
            raise ValueError("list must contain at least one non-empty string")
        return cleaned

    @model_validator(mode="after")
    def _require_non_empty_lists(self) -> RadarInput:
        if not self.jurisdictions:
            raise ValueError("jurisdictions must not be empty")
        if not self.domains:
            raise ValueError("domains must not be empty")
        return self


class WatchCell(BaseModel):
    """One jurisdiction × domain radar unit."""

    cell_id: str
    jurisdiction: str
    jurisdiction_id: str
    domain: str
    domain_id: str
    subject: str = "Meta"
    status: Literal["pending", "scanning", "validating", "done", "error"] = "pending"
    level: str | None = None


def _stable_signal_id(jurisdiction_id: str, domain_id: str, source_url: str, title: str) -> str:
    """Deterministic id so the same story is recognized across runs."""
    url = (source_url or "").strip().lower().split("#")[0]
    normalized_title = re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()
    text = f"{jurisdiction_id or ''}|{domain_id or ''}|{url}|{normalized_title}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class SignalDraft(BaseModel):
    """A forward-looking signal extracted from news/trade/law-firm sources."""

    signal_id: str = ""
    title: str
    jurisdiction_id: str
    domain_id: str
    event_type: Literal[
        "bill",
        "amendment",
        "consultation",
        "enforcement_probe",
        "litigation",
        "regulatory_guidance",
        "rumor",
        "other",
    ] = "other"
    summary: str = ""
    source_url: str = ""
    source_name: str = ""
    source_type: Literal[
        "news", "wire", "trade_press", "law_firm_blog", "think_tank", "official_press", "other"
    ] = "other"
    published_date: str | None = None
    likelihood: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    is_rumor: bool = False
    relevance_to_subject: str = ""
    corroboration_notes: str = ""
    known_law_status: Literal["new", "update_to_known_law", "duplicate_of_known_law"] = "new"
    known_law_match_id: str | None = None
    worker_model: str = ""
    cell_id: str = ""
    retrieved_at: str = Field(default_factory=_utc_now_iso)

    @field_validator("title")
    @classmethod
    def _title_non_empty(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("title is required")
        return v.strip()

    @model_validator(mode="after")
    def _set_stable_signal_id(self) -> SignalDraft:
        self.signal_id = _stable_signal_id(
            self.jurisdiction_id, self.domain_id, self.source_url, self.title
        )
        return self


class SignalRecord(SignalDraft):
    """A signal that has passed validation."""

    validated: bool = True


class RejectedSignal(BaseModel):
    """A signal draft rejected by validation."""

    record: SignalDraft
    reason: str
    cell_id: str = ""


class SignalCluster(BaseModel):
    """Corroborated cluster of related signals from distinct publishers."""

    cluster_id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    event_type: str = "other"
    jurisdiction_id: str = ""
    domain_id: str = ""
    signal_ids: list[str] = Field(default_factory=list)
    signals: list[SignalRecord] = Field(default_factory=list)
    distinct_publisher_count: int = 0
    publisher_names: list[str] = Field(default_factory=list)
    earliest_date: str | None = None
    latest_date: str | None = None
    is_rumor_cluster: bool = False
    status: Literal["confirmed", "corroborated", "rumor", "duplicate"] = "corroborated"
    created_at: str = Field(default_factory=_utc_now_iso)


class RadarManifest(BaseModel):
    """Top-level manifest for a radar run."""

    run_id: str
    subject: str = "Meta"
    previous_run_id: str | None = None
    jurisdictions: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    lookback_days: int = 14
    levels: list[str] = Field(default_factory=list)
    include_rumors: bool = False
    signal_count: int = 0
    cluster_count: int = 0
    known_law_count: int = 0
    rejected_count: int = 0
    error_count: int = 0
    catalog_version: str = ""
    radar_path: str = ""
    created_at: str = Field(default_factory=_utc_now_iso)


def _coerce_watch_cell(state: Any) -> WatchCell | None:
    """Build a WatchCell from a Send payload or nested ``cell``."""
    if isinstance(state, WatchCell):
        return state
    data: dict[str, Any] = {}
    if isinstance(state, dict):
        data = dict(state)
    elif hasattr(state, "model_dump"):
        with contextlib.suppress(Exception):
            data = dict(state.model_dump())

    cell = data.get("cell")
    if isinstance(cell, dict):
        nested = dict(cell)
        nested.update({k: v for k, v in data.items() if k != "cell" and v not in (None, "")})
        data = nested
    elif isinstance(cell, WatchCell):
        data = cell.model_dump()
        data.update(
            {k: v for k, v in state.items() if k != "cell" and v not in (None, "")}
        ) if hasattr(state, "items") else None

    jurisdiction = normalize_jurisdiction(str(data.get("jurisdiction") or "").strip())
    domain_raw = str(data.get("domain") or data.get("domain_id") or "").strip()
    domain_id = normalize_domain(domain_raw)
    if not jurisdiction or not domain_id:
        return None
    jurisdiction_id = slugify(jurisdiction) or "unknown"
    cell_id = str(data.get("cell_id") or "").strip() or make_cell_id(jurisdiction_id, domain_id)
    return WatchCell(
        cell_id=cell_id,
        jurisdiction=jurisdiction,
        jurisdiction_id=jurisdiction_id,
        domain=domain_id,
        domain_id=domain_id,
        subject=str(data.get("subject") or "Meta").strip() or "Meta",
        status="scanning",
    )
