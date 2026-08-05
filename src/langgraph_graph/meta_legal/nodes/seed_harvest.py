"""Deterministic seed-instrument harvest → LawRecordDrafts (exp_006).

Builds drafts from curated instrument names + seed URLs without relying on
search or the LLM. Used as a floor so cells with seeds never return empty
when the model/search path flakes under load.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import unquote, urlparse

from langgraph_graph.meta_legal.models import LawRecordDraft, ResearchCell, normalize_domain, slugify

FetchFn = Callable[[str, int], str]

_EXCERPT_CHARS = 1200
_DEFAULT_FETCH_CHARS = 8000
_HARVEST_CONFIDENCE = 0.8
_HARVEST_WORKER = "seed_harvest"

# Loose citation fragments commonly embedded in instrument alias strings.
_CITATION_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"Regulation\s*\(EU\)\s*\d{4}/\d+", re.I),
    re.compile(r"Directive\s*\(EU\)\s*\d{4}/\d+", re.I),
    re.compile(r"Directive\s+\d{4}/\d+/EC", re.I),
    re.compile(r"Council\s+Regulation\s*\(EC\)\s*No\s*\d+/\d+", re.I),
    re.compile(r"\b\d+\s*U\.?S\.?C\.?\s*§?\s*\d+[A-Za-z]?\b", re.I),
    re.compile(r"Pub\.\s*L\.\s*[\d\-]+", re.I),
    re.compile(r"\b\d{2,3}\s*CFR\s*(Part\s*)?\d+\b", re.I),
    re.compile(r"Lei\s*[\d.]+/\d{4}", re.I),
    re.compile(r"CELEX[:\s%]*\d{4,5}[A-Z]?\d+", re.I),
    re.compile(r"\b(?:ukpga|uksi|ukia)/\d{4}/\d+\b", re.I),
    re.compile(r"\bSB\s*\d{2,4}\b", re.I),
    re.compile(r"\bAB\s*\d{2,4}\b", re.I),
    re.compile(r"\bCOM/\d{4}/\d+\b", re.I),
)

_OFFICIAL_HOST_HINTS: tuple[str, ...] = (
    ".gov",
    ".gob.",
    ".gouv.",
    ".govt.",
    ".go.",
    ".mil",
    "europa.eu",
    "eur-lex.europa.eu",
    "ec.europa.eu",
    "edpb.europa.eu",
    "legislation.gov.uk",
    "parliament.uk",
    "congress.gov",
    "federalregister.gov",
    "regulations.gov",
    "ftc.gov",
    "justice.gov",
    "govinfo.gov",
    "uscode.house.gov",
    "law.cornell.edu",
    "leginfo.legislature.ca.gov",
    "legislation.",
    "regul",
    "gazette",
)


def _norm_url(url: str) -> str:
    return (url or "").strip().split("#", 1)[0].rstrip("/")


def _norm_title(title: str) -> str:
    return " ".join((title or "").lower().split())


def _is_official_host(url: str) -> bool:
    u = (url or "").lower()
    if not u:
        return False
    return any(hint in u for hint in _OFFICIAL_HOST_HINTS)


def _citation_from_name(name: str) -> str:
    text = (name or "").strip()
    if not text:
        return ""
    for pat in _CITATION_RES:
        m = pat.search(text)
        if m:
            return " ".join(m.group(0).split())
    # First ~12 tokens as a soft citation stand-in.
    tokens = text.split()
    return " ".join(tokens[:12])


def _display_title(name: str) -> str:
    """Prefer a compact title; keep enough signal for the recall matcher."""
    text = " ".join((name or "").split())
    if not text:
        return "Untitled instrument"
    # If a short leading acronym block exists, keep a readable prefix.
    if len(text) <= 96:
        return text
    cut = text[:96]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut or text[:96]


def _instrument_tokens(name: str) -> set[str]:
    text = name or ""
    lower = text.lower()
    tokens: set[str] = set()
    for m in re.finditer(r"\b(\d{4}/\d{2,4})\b", lower):
        num = m.group(1)
        tokens.add(num)
        tokens.add(num.replace("/", ""))
        # EUR-Lex CELEX style year+type fragments often appear without slash.
        tokens.add(num.replace("/", "r"))
        tokens.add(num.replace("/", "l"))
    for m in re.finditer(r"\b(\d{5}[a-z]?\d{4,5})\b", lower):
        tokens.add(m.group(1))
    for m in re.finditer(r"\bcelex[:\s]*([0-9a-z]+)\b", lower):
        tokens.add(m.group(1))
    for m in re.finditer(r"\b([A-Z][A-Z0-9]{1,11})\b", text):
        tok = m.group(1).lower()
        if tok not in {"eu", "uk", "us", "ec", "en", "no", "of", "and", "act", "law"}:
            tokens.add(tok)
    # Significant words ≥5 chars (skip stop-ish).
    for w in re.findall(r"[a-z]{5,}", lower):
        if w not in {"regulation", "directive", "official", "framework", "personal", "protection"}:
            tokens.add(w)
    return tokens


def _url_match_blob(url: str) -> str:
    raw = unquote((url or "").lower())
    return re.sub(r"[^a-z0-9]+", "", raw)


def _score_pair(instrument: str, url: str) -> int:
    tokens = _instrument_tokens(instrument)
    if not tokens:
        return 0
    blob = _url_match_blob(url)
    if not blob:
        return 0
    score = 0
    for tok in tokens:
        compact = re.sub(r"[^a-z0-9]+", "", tok.lower())
        if len(compact) < 3:
            continue
        if compact in blob:
            # Numeric / CELEX-like hits weigh more.
            score += 5 if any(ch.isdigit() for ch in compact) else 2
    return score


def pair_instruments_and_seeds(
    instruments: Sequence[str],
    seed_urls: Sequence[str],
) -> list[tuple[str, str]]:
    """Pair instrument display names with seed URLs (best-effort, stable).

    Every seed URL is emitted at least once. Instruments without any seeds are
    dropped (validation requires a source_url).
    """
    names = [n.strip() for n in instruments if (n or "").strip()]
    urls = []
    seen_u: set[str] = set()
    for u in seed_urls:
        key = _norm_url(u)
        if not key or not key.startswith("http") or key in seen_u:
            continue
        seen_u.add(key)
        urls.append(u.strip())

    if not urls:
        return []

    pairs: list[tuple[str, str]] = []
    used_urls: set[str] = set()

    for name in names:
        best_url: str | None = None
        best_score = -1
        for url in urls:
            uk = _norm_url(url)
            if uk in used_urls:
                continue
            sc = _score_pair(name, url)
            if sc > best_score:
                best_score = sc
                best_url = url
        if best_url is None:
            # Fall back to first unused URL (positional).
            for url in urls:
                uk = _norm_url(url)
                if uk not in used_urls:
                    best_url = url
                    best_score = 0
                    break
        if best_url is None:
            # All URLs already used — reuse best overall match for this name.
            ranked = sorted(urls, key=lambda u: _score_pair(name, u), reverse=True)
            best_url = ranked[0]
            best_score = _score_pair(name, best_url)
        # Weak match + already-used URL: still emit once per instrument with its best URL.
        pairs.append((name, best_url))
        used_urls.add(_norm_url(best_url))

    # Leftover seeds (no instrument claimed them) still become drafts.
    claimed = {_norm_url(u) for _, u in pairs}
    for url in urls:
        uk = _norm_url(url)
        if uk in claimed:
            continue
        # Prefer an instrument that scores on this URL for the title.
        title = ""
        if names:
            ranked = sorted(names, key=lambda n: _score_pair(n, url), reverse=True)
            if _score_pair(ranked[0], url) > 0:
                title = ranked[0]
        if not title:
            path = urlparse(url).path.strip("/") or urlparse(url).netloc
            title = f"Primary source {unquote(path)}"
        pairs.append((title, url))
        claimed.add(uk)

    return pairs


def _safe_fetch(fetch_fn: FetchFn | None, url: str, max_chars: int) -> str:
    if fetch_fn is None:
        return ""
    try:
        text = fetch_fn(url, max_chars) or ""
    except TypeError:
        try:
            text = fetch_fn(url) or ""  # type: ignore[misc, call-arg]
        except Exception:
            return ""
    except Exception:
        return ""
    return str(text).strip()


def harvest_seed_instruments(
    cell: ResearchCell | Mapping[str, Any] | Any,
    *,
    instruments: Sequence[str] | None = None,
    seed_urls: Sequence[str] | None = None,
    fetch_fn: FetchFn | None = None,
    fetched_cache: Mapping[str, str] | None = None,
    max_chars_excerpt: int = _EXCERPT_CHARS,
    max_chars_fetch: int = _DEFAULT_FETCH_CHARS,
    worker_model: str = _HARVEST_WORKER,
) -> list[LawRecordDraft]:
    """Build LawRecordDrafts from instrument names + paired seed URLs.

    Fetches each seed when possible (reusing ``fetched_cache``), but always
    emits a draft with title + source_url even when fetch returns empty.
    Never raises.
    """
    try:
        if isinstance(cell, ResearchCell):
            resolved = cell
        else:
            # Lazy import avoids circular import at module load.
            from langgraph_graph.meta_legal.nodes.research_cell import _coerce_cell

            resolved = _coerce_cell(cell)
    except Exception:
        return []

    try:
        if instruments is None or seed_urls is None:
            from langgraph_graph.meta_legal.nodes.research_cell import (
                _instruments_for_cell,
                seed_urls_for_cell,
            )

            inst = list(instruments) if instruments is not None else list(_instruments_for_cell(resolved))
            seeds = list(seed_urls) if seed_urls is not None else list(seed_urls_for_cell(resolved))
        else:
            inst = list(instruments)
            seeds = list(seed_urls)
    except Exception:
        return []

    if not seeds:
        return []

    pairs = pair_instruments_and_seeds(inst, seeds)
    if not pairs:
        return []

    jid = (resolved.jurisdiction_id or slugify(resolved.jurisdiction or "")).strip()
    did = (resolved.domain_id or normalize_domain(resolved.domain or "")).strip()
    cell_id = (resolved.cell_id or "").strip()
    cache = { _norm_url(k): v for k, v in (fetched_cache or {}).items() if v }

    drafts: list[LawRecordDraft] = []
    seen_pair: set[tuple[str, str]] = set()

    for name, url in pairs:
        title = _display_title(name)
        uk = _norm_url(url)
        key = (_norm_title(title), uk)
        if key in seen_pair:
            continue
        seen_pair.add(key)

        text = ""
        if uk in cache:
            text = (cache[uk] or "").strip()
        elif url in (fetched_cache or {}):
            text = str(fetched_cache.get(url) or "").strip()
        else:
            text = _safe_fetch(fetch_fn, url, max_chars_fetch)
            if text:
                cache[uk] = text

        excerpt = text[: max(0, int(max_chars_excerpt))].strip()
        source_type = "primary" if _is_official_host(url) else "secondary"

        try:
            drafts.append(
                LawRecordDraft(
                    title=title,
                    jurisdiction_id=jid,
                    domain_id=did,
                    meta_nexus="platform_obligation",
                    meta_nexus_rationale=(
                        "Curated seed instrument for this jurisdiction/domain cell; "
                        "platform-relevant compliance obligations typically apply."
                    ),
                    citation=_citation_from_name(name),
                    source_url=url,
                    source_type=source_type,  # type: ignore[arg-type]
                    excerpt=excerpt,
                    language="en",
                    confidence=_HARVEST_CONFIDENCE,
                    worker_model=worker_model or _HARVEST_WORKER,
                    cell_id=cell_id,
                )
            )
        except Exception:
            continue

    return drafts


def merge_drafts(
    primary: Iterable[LawRecordDraft] | None,
    extra: Iterable[LawRecordDraft] | None,
) -> list[LawRecordDraft]:
    """Append ``extra`` drafts not already present by source_url or title."""
    out: list[LawRecordDraft] = list(primary or [])
    seen_urls = {_norm_url(d.source_url) for d in out if (d.source_url or "").strip()}
    seen_titles = {_norm_title(d.title) for d in out if (d.title or "").strip()}

    for draft in extra or []:
        if draft is None:
            continue
        uk = _norm_url(getattr(draft, "source_url", "") or "")
        tk = _norm_title(getattr(draft, "title", "") or "")
        if uk and uk in seen_urls:
            continue
        if tk and tk in seen_titles:
            continue
        out.append(draft)
        if uk:
            seen_urls.add(uk)
        if tk:
            seen_titles.add(tk)
    return out


__all__ = [
    "harvest_seed_instruments",
    "merge_drafts",
    "pair_instruments_and_seeds",
]
