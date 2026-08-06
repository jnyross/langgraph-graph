"""Scan a single jurisdiction × domain cell for forward-looking signals."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal, cast

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from langgraph_graph.meta_legal.llm import get_llm
from langgraph_graph.meta_legal.models import _utc_now_iso
from langgraph_graph.meta_legal.tools.fetch import fetch_url
from langgraph_graph.meta_legal.tools.search import SearchOptions, web_search
from langgraph_graph.news_radar.models import SignalDraft, WatchCell, _coerce_watch_cell
from langgraph_graph.news_radar.sources import (
    publisher_name_from_url,
    select_news_urls,
)
from langgraph_graph.news_radar.state import RadarState

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "scan.md"
_DEFAULT_WORKER_MODEL = "~deepseek/deepseek-v4-flash-latest"


def _resolve_worker_model(state_model: str | None) -> str:
    """Respect env model overrides; state is highest precedence."""
    return (
        state_model
        or os.getenv("OPENROUTER_MODEL")
        or os.getenv("DEEPSEEK_MODEL")
        or os.getenv("META_LEGAL_WORKER_MODEL")
        or _DEFAULT_WORKER_MODEL
    )

# Domain-specific natural-language search tokens for event-first queries.
_DOMAIN_TOKENS: dict[str, str] = {
    "privacy": "data protection privacy",
    "competition": "antitrust competition",
    "youth_safety": "child safety youth online safety",
    "ip": "intellectual property copyright patent trademark",
    "accessibility": "digital accessibility",
}

_EventType = Literal[
    "bill",
    "amendment",
    "consultation",
    "enforcement_probe",
    "litigation",
    "regulatory_guidance",
    "rumor",
    "other",
]
_SourceType = Literal[
    "news",
    "wire",
    "trade_press",
    "law_firm_blog",
    "think_tank",
    "official_press",
    "other",
]
_LawStatus = Literal["new", "update_to_known_law", "duplicate_of_known_law"]

_VALID_EVENT_TYPES = set(_EventType.__args__)  # type: ignore[attr-defined]
_VALID_SOURCE_TYPES = set(_SourceType.__args__)  # type: ignore[attr-defined]
_VALID_LAW_STATUS = set(_LawStatus.__args__)  # type: ignore[attr-defined]


def _coerce_event_type(value: Any) -> _EventType:
    v = str(value or "other").strip().lower()
    return cast(_EventType, v if v in _VALID_EVENT_TYPES else "other")


def _coerce_source_type(value: Any) -> _SourceType:
    v = str(value or "other").strip().lower()
    return cast(_SourceType, v if v in _VALID_SOURCE_TYPES else "other")


def _coerce_law_status(value: Any) -> _LawStatus:
    v = str(value or "new").strip().lower()
    return cast(_LawStatus, v if v in _VALID_LAW_STATUS else "new")


_EVENT_FRAMES: list[tuple[str, str]] = [
    ("bill proposed law", "upcoming bill proposed law"),
    ("amendment", "draft amendment"),
    ("consultation", "public consultation"),
    ("enforcement probe", "investigation enforcement probe"),
    ("litigation court challenge", "court case litigation"),
]


class _ExtractedSignal(BaseModel):
    title: str = Field(..., min_length=3)
    event_type: str = "other"
    summary: str = ""
    source_url: str = ""
    source_name: str = ""
    source_type: str = "other"
    published_date: str | None = None
    likelihood: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    is_rumor: bool = False
    relevance_to_subject: str = ""
    corroboration_notes: str = ""
    known_law_status: str = "new"


class _SignalList(BaseModel):
    signals: list[_ExtractedSignal] = Field(default_factory=list)


def _load_system_prompt() -> str:
    try:
        return (_PROMPT_PATH.resolve()).read_text(encoding="utf-8")
    except Exception:
        return (
            "Extract forward-looking regulatory signals from the provided materials. "
            "Return a JSON array only. Do not include markdown or prose."
        )


def _build_search_queries(cell: WatchCell, lookback_days: int) -> list[str]:
    """Generate a small set of event-first news queries for the cell."""
    domain_token = _DOMAIN_TOKENS.get(cell.domain_id, cell.domain)
    base = f"{cell.jurisdiction} {domain_token} {cell.subject}"
    queries = []
    for _, frame in _EVENT_FRAMES:
        queries.append(f"{base} {frame}")
    # Add a recency-biased broad query.
    queries.append(f"{base} latest news {lookback_days} days")
    return queries


def _normalize_published_date(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    # Prefer YYYY-MM-DD, year-month, or year.
    m = re.search(r"(\d{4})[-/](\d{1,2})(?:[-/](\d{1,2}))?", text)
    if m:
        year, month, day = m.group(1), m.group(2).zfill(2), m.group(3)
        if day:
            return f"{year}-{month}-{day.zfill(2)}"
        return f"{year}-{month}"
    m_year = re.search(r"\b(19|20)\d{2}\b", text)
    if m_year:
        return m_year.group(0)
    return text if len(text) >= 4 else None


def _run_news_search(query: str, lookback_days: int, max_results: int = 4) -> list[dict[str, Any]]:
    """Run a news-biased web search for the query."""
    options = SearchOptions(topic="news", recency_days=lookback_days)
    try:
        return web_search(query, max_results=max_results, options=options)
    except Exception:
        return []


def _gather_context(
    cell: WatchCell, lookback_days: int, max_urls: int = 6
) -> tuple[list[dict[str, Any]], str]:
    """Search, select diverse URLs, and fetch page contents."""
    queries = _build_search_queries(cell, lookback_days)
    all_hits: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for q in queries:
        hits = _run_news_search(q, lookback_days, max_results=4)
        for h in hits:
            url = str(h.get("url") or h.get("href") or "").strip()
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_hits.append(h)

    selected = select_news_urls(all_hits, limit=max_urls, max_per_host=2)

    context_parts: list[str] = []
    for i, item in enumerate(selected, 1):
        url = str(item.get("url") or item.get("href") or "").strip()
        title = str(item.get("title") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        if not url:
            continue
        fetched = ""
        try:
            fetched = fetch_url(url, max_chars=6000) or ""
        except Exception:
            fetched = ""
        # If fetch is empty/minimal, fall back to snippet.
        body = fetched.strip() if len(fetched.strip()) > 80 else snippet
        context_parts.append(f"--- Source {i} ---\nURL: {url}\nTitle: {title}\n{body}\n---")

    return selected, "\n\n".join(context_parts)


def _extract_json_block(text: str) -> Any:
    """Best-effort extraction of a JSON array from LLM text."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"```[a-zA-Z]*", "", text).replace("```", "").strip()
    # Direct parse.
    try:
        return json.loads(text)
    except Exception:
        pass
    # Find first JSON array.
    for match in re.finditer(r"\[", text):
        start = match.start()
        depth = 0
        for i, ch in enumerate(text[start:], start=start):
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except Exception:
                        break
    return None


def _extract_signals(
    cell: WatchCell,
    context: str,
    *,
    worker_model: str,
) -> list[SignalDraft]:
    """Extract signal drafts via structured output, then JSON fallback."""
    system_template = _load_system_prompt()
    system_prompt = (
        system_template.replace("{{subject}}", cell.subject)
        .replace("{{jurisdiction}}", cell.jurisdiction)
        .replace("{{jurisdiction_id}}", cell.jurisdiction_id)
        .replace("{{domain}}", cell.domain)
        .replace("{{domain_id}}", cell.domain_id)
    )
    user_prompt = f"Analyze the following sources and return a JSON array of signals.\n\n{context}"
    messages: list[Any] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]

    extracted: list[dict[str, Any]] = []
    llm = get_llm(model=worker_model)

    # Path 1: with_structured_output
    for method in ("json_schema", "function_calling"):
        try:
            binder = getattr(llm, "with_structured_output", None)
            if not callable(binder):
                break
            bound = binder(_SignalList, method=method)
            resp = bound.invoke(messages)
            if isinstance(resp, _SignalList):
                for s in resp.signals:
                    extracted.append(s.model_dump())
                break
        except Exception:
            continue

    # Path 2: JSON mode / plain text parse
    if not extracted:
        try:
            raw = llm.invoke(messages)
            content = raw.content if hasattr(raw, "content") else str(raw)
            payload = _extract_json_block(content)
            if isinstance(payload, list):
                extracted = payload
        except Exception:
            pass

    drafts: list[SignalDraft] = []
    for item in extracted:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title or len(title) < 3:
            continue
        source_url = str(item.get("source_url") or "").strip()
        published_date = _normalize_published_date(item.get("published_date"))
        source_name = str(item.get("source_name") or "").strip() or (
            publisher_name_from_url(source_url) if source_url else "unknown"
        )
        source_type = _coerce_source_type(item.get("source_type"))
        event_type = _coerce_event_type(item.get("event_type"))
        try:
            likelihood = float(item.get("likelihood", 0.5))
        except Exception:
            likelihood = 0.5
        try:
            confidence = float(item.get("confidence", 0.5))
        except Exception:
            confidence = 0.5

        drafts.append(
            SignalDraft(
                title=title,
                jurisdiction_id=cell.jurisdiction_id,
                domain_id=cell.domain_id,
                event_type=event_type,
                summary=str(item.get("summary") or "").strip()[:2000],
                source_url=source_url,
                source_name=source_name,
                source_type=source_type,
                published_date=published_date,
                likelihood=max(0.0, min(1.0, likelihood)),
                confidence=max(0.0, min(1.0, confidence)),
                is_rumor=bool(item.get("is_rumor", False)),
                relevance_to_subject=str(item.get("relevance_to_subject") or "").strip()[:500],
                corroboration_notes=str(item.get("corroboration_notes") or "").strip()[:1000],
                known_law_status=_coerce_law_status(item.get("known_law_status")),
                worker_model=worker_model or _DEFAULT_WORKER_MODEL,
                cell_id=cell.cell_id,
                retrieved_at=_utc_now_iso(),
            )
        )
    return drafts


def scan_cell(state: RadarState) -> dict:
    """Search news sources and extract signal drafts for one watch cell."""
    cell = _coerce_watch_cell(state)
    if cell is None:
        return {
            "cell_errors": [
                {
                    "cell_id": "unknown",
                    "stage": "scan",
                    "message": "Could not coerce watch cell from state",
                }
            ]
        }

    lookback_days = state.get("lookback_days", 14)
    worker_model = _resolve_worker_model(cast(str | None, state.get("worker_model")))

    try:
        _, context = _gather_context(cell, lookback_days, max_urls=6)
        if not context.strip():
            return {
                "cell_errors": [
                    {
                        "cell_id": cell.cell_id,
                        "stage": "scan",
                        "message": "No source content gathered for cell",
                    }
                ]
            }

        drafts = _extract_signals(cell, context, worker_model=worker_model)
        return {"drafts": drafts}
    except Exception as exc:
        return {
            "cell_errors": [
                {
                    "cell_id": cell.cell_id,
                    "stage": "scan",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            ]
        }
