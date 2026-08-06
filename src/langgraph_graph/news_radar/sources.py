"""Publisher classification and URL selection for news/radar sources.

The news_radar graph deliberately inverts the official-source bias used by
meta_legal: primary sources are demoted so that news, trade press, law-firm
blogs, think-tank reports and wire services dominate the signal mix. Official
hosts are not excluded, however, because regulator press releases contain
legitimate forward-looking signals.
"""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlparse

SourceLabel = Literal[
    "news",
    "wire",
    "trade_press",
    "law_firm_blog",
    "think_tank",
    "official_press",
    "official",
    "other",
]
HostScore = tuple[int, SourceLabel]

# Bonus patterns for known international/global outlets. Format: (host_substring, score, label).
_NEWS_HOST_HINTS: list[tuple[str, int, SourceLabel]] = [
    # major wires / agencies
    ("reuters.com", 95, "wire"),
    ("apnews.com", 95, "wire"),
    ("afp.com", 95, "wire"),
    ("bloomberg.com", 90, "news"),
    # mainstream business/news
    ("ft.com", 90, "news"),
    ("wsj.com", 90, "news"),
    ("nytimes.com", 85, "news"),
    ("theguardian.com", 85, "news"),
    ("washingtonpost.com", 85, "news"),
    ("politico", 85, "news"),
    ("bbc.com", 85, "news"),
    # tech / trade press
    ("theverge.com", 80, "trade_press"),
    ("techcrunch.com", 80, "trade_press"),
    ("wired.com", 80, "trade_press"),
    ("arstechnica.com", 80, "trade_press"),
    ("theregister.com", 80, "trade_press"),
    ("zdnet.com", 80, "trade_press"),
    ("cnet.com", 75, "trade_press"),
    ("gartner.com", 75, "trade_press"),
    ("forrester.com", 75, "trade_press"),
    ("cmswire.com", 70, "trade_press"),
    # legal / IP / privacy trade press
    ("iam-media.com", 85, "trade_press"),
    ("worldipreview.com", 85, "trade_press"),
    ("jdsupra.com", 80, "law_firm_blog"),
    ("lexology.com", 80, "law_firm_blog"),
    ("law360.com", 85, "trade_press"),
    # law firms (selection of global firms; many more fall through to generic bonus)
    ("skadden.com", 75, "law_firm_blog"),
    ("cooley.com", 75, "law_firm_blog"),
    ("hoganlovells.com", 75, "law_firm_blog"),
    ("dlapiper.com", 75, "law_firm_blog"),
    ("whitecase.com", 75, "law_firm_blog"),
    ("linklaters.com", 75, "law_firm_blog"),
    ("bakerlaw.com", 75, "law_firm_blog"),
    ("cliffordchance.com", 75, "law_firm_blog"),
    ("freshfields.com", 75, "law_firm_blog"),
    ("gibsondunn.com", 75, "law_firm_blog"),
    # think tanks / advocacy
    ("brookings.edu", 80, "think_tank"),
    ("cato.org", 80, "think_tank"),
    ("eff.org", 80, "think_tank"),
    ("epic.org", 80, "think_tank"),
    ("lawfaremedia.org", 80, "think_tank"),
    ("privacyinternational.org", 80, "think_tank"),
    ("accessnow.org", 80, "think_tank"),
]

_OFFICIAL_HOST_PATTERNS: tuple[str, ...] = (
    ".gov",
    ".gov.",
    ".parliament",
    "congress.gov",
    "ec.europa.eu",
    "europa.eu",
    "gov.uk",
    "gov.au",
    "gc.ca",
    "bundesregierung.de",
    "legifrance.gouv",
    "parl.ca",
    "ico.org.uk",
    "cnil.fr",
    "edpb.eu",
)


def news_host_score(url: str, title: str = "") -> HostScore:
    """Return (score, source_label) for a source URL.

    Higher scores go to distinct press/blog publishers; official-domain press
    releases get a small bonus so they remain in the mix but behind news.
    """
    host = urlparse(url or "").netloc.lower().removeprefix("www.")
    if not host:
        return (0, "other")

    normalized_title = (title or "").lower()

    for pattern, score, label in _NEWS_HOST_HINTS:
        if pattern in host or pattern in normalized_title:
            return (score, label)

    # Generic news-ish domain heuristics (weak, do not override explicit list).
    news_tokens = ("news", "post", "times", "herald", "tribune", "daily", "live")
    law_tokens = ("law", "legal", "jdsupra", "lexology")
    if any(t in host for t in law_tokens):
        return (60, "law_firm_blog")
    if any(t in host for t in news_tokens):
        return (50, "news")

    # Official hosts: demoted but retained.
    if any(p in host for p in _OFFICIAL_HOST_PATTERNS):
        is_press_release = any(
            token in normalized_title
            for token in ("press release", "announces", "announced", "to launch")
        )
        return (20 if is_press_release else 10, "official")
    return (40, "other")


def _dedupe_news_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """De-duplicate search results by URL, keeping the first occurrence."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in records:
        url = str(item.get("url") or item.get("href") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(item)
    return out


def select_news_urls(
    hits: list[dict[str, Any]],
    *,
    limit: int = 6,
    max_per_host: int = 2,
    include_official: bool = True,
) -> list[dict[str, Any]]:
    """Pick a diverse, news-first subset of search results.

    Sorts primarily by publisher score, then caps each host to ``max_per_host``
    so that one wire service does not dominate a cell. Official hosts are kept
    with lower priority.
    """
    hits = _dedupe_news_records(hits)
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for item in hits:
        url = str(item.get("url") or item.get("href") or "").strip()
        title = str(item.get("title") or "").strip()
        if not url:
            continue
        score, label = news_host_score(url, title)
        if not include_official and label in {"official", "official_press"}:
            continue
        scored.append((score, url, {**item, "source_label": label}))

    # Sort by score descending, URL ascending for determinism.
    scored.sort(key=lambda x: (-x[0], x[1]))

    host_counts: dict[str, int] = {}
    selected: list[dict[str, Any]] = []
    for score, url, item in scored:
        host = urlparse(url).netloc.lower().removeprefix("www.").split(":")[0]
        if not host:
            continue
        if host_counts.get(host, 0) >= max_per_host:
            continue
        item["_score"] = score
        selected.append(item)
        host_counts[host] = host_counts.get(host, 0) + 1
        if len(selected) >= limit:
            break
    return selected


def publisher_name_from_url(url: str, fallback: str = "") -> str:
    """Extract a human-ish publisher name from a URL."""
    host = urlparse(url or "").netloc.lower().removeprefix("www.")
    if not host:
        return (fallback or "unknown").strip()
    parts = host.split(".")
    if parts[0] in ("m", "mobile", "news", "www"):
        parts = parts[1:]
    name = parts[0] if parts else host
    return name.replace("-", " ").replace("_", " ").title()
