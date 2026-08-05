"""Web search helpers for meta_legal research workers.

Never raises: failures degrade to an empty result list.
"""

from __future__ import annotations

import os
import warnings
from typing import Any
from urllib.parse import urlsplit, urlunsplit


# Preferred multi-engine backends for the modern ``ddgs`` package.
_DDGS_BACKENDS: tuple[str, ...] = (
    "auto",
    "duckduckgo,bing,brave",
    "duckduckgo",
    "bing",
    "brave",
    "yahoo",
)
# Legacy duckduckgo_search backends (kept for older installs).
_LEGACY_BACKENDS: tuple[str, ...] = ("api", "html", "lite")


def _normalize_result(item: dict[str, Any]) -> dict[str, str] | None:
    """Coerce heterogeneous provider payloads into title/url/snippet."""
    title = str(item.get("title") or item.get("name") or "").strip()
    url = str(
        item.get("url")
        or item.get("href")
        or item.get("link")
        or item.get("content")  # some providers misuse content for URL
        or ""
    ).strip()
    snippet = str(
        item.get("snippet")
        or item.get("body")
        or item.get("description")
        or item.get("content")
        or ""
    ).strip()
    # Prefer a real URL field; if content was used as URL fallback and looks
    # non-URL, drop it from url and keep as snippet only.
    if url and not (url.startswith("http://") or url.startswith("https://")):
        if not snippet:
            snippet = url
        url = str(item.get("href") or item.get("link") or "").strip()
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return None
    return {"title": title or url, "url": url, "snippet": snippet}


def _canonical_url(url: str) -> str:
    """Normalize URL for de-duplication (strip fragment, trailing slash, case host)."""
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        netloc = parts.netloc.lower()
        path = parts.path.rstrip("/") or ""
        return urlunsplit((parts.scheme.lower(), netloc, path, parts.query, ""))
    except Exception:
        return raw.split("#", 1)[0].rstrip("/").lower()


def _dedupe_results(results: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for item in results:
        key = _canonical_url(item.get("url") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _search_tavily(query: str, max_results: int) -> list[dict[str, str]]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return []
    try:
        import httpx
    except Exception:
        return []

    try:
        response = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "include_answer": False,
                "search_depth": "basic",
            },
            timeout=20.0,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []

    results: list[dict[str, str]] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_result(
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "snippet": item.get("content") or item.get("snippet"),
            }
        )
        if normalized:
            results.append(normalized)
        if len(results) >= max_results:
            break
    return _dedupe_results(results)


def _import_ddgs_class() -> Any | None:
    """Prefer ``ddgs.DDGS``; fall back to legacy ``duckduckgo_search``."""
    try:
        from ddgs import DDGS as ddgs_cls  # type: ignore

        return ddgs_cls
    except Exception:
        pass
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            from duckduckgo_search import DDGS as ddgs_cls  # type: ignore

        return ddgs_cls
    except Exception:
        return None


def _ddg_text_once(
    ddgs_cls: Any,
    query: str,
    *,
    max_results: int,
    backend: str | None,
    region: str = "wt-wt",
) -> list[dict[str, Any]]:
    """Run one DDGS.text call; never raises."""
    kwargs: dict[str, Any] = {"max_results": max_results, "region": region}
    if backend:
        kwargs["backend"] = backend

    def _call(client: Any, call_kwargs: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            return list(client.text(query, **call_kwargs) or [])
        except TypeError:
            # Older signatures: keywords=..., no region/backend, etc.
            slim = {"max_results": max_results}
            if backend:
                slim["backend"] = backend
            try:
                return list(client.text(query, **slim) or [])
            except TypeError:
                try:
                    return list(client.text(query, max_results=max_results) or [])
                except TypeError:
                    try:
                        return list(client.text(keywords=query, max_results=max_results) or [])
                    except Exception:
                        return []
            except Exception:
                return []
        except Exception:
            return []

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            try:
                with ddgs_cls() as client:
                    return _call(client, kwargs)
            except TypeError:
                client = ddgs_cls()
                try:
                    return _call(client, kwargs)
                finally:
                    close = getattr(client, "close", None)
                    if callable(close):
                        try:
                            close()
                        except Exception:
                            pass
    except Exception:
        return []
    return []


def _collect_normalized(raw: list[dict[str, Any]], limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_result(item)
        if normalized:
            results.append(normalized)
        if len(results) >= limit:
            break
    return _dedupe_results(results)


def _search_ddg(query: str, max_results: int) -> list[dict[str, str]]:
    """Search via ``ddgs`` (preferred) or legacy ``duckduckgo_search``.

    Tries multiple backends/regions, retries once on empty, de-dupes by URL.
    Never raises.
    """
    ddgs_cls = _import_ddgs_class()
    if ddgs_cls is None:
        return []

    # Detect modern multi-engine package vs legacy DDG-only package by module path.
    mod = getattr(ddgs_cls, "__module__", "") or ""
    is_modern = mod.startswith("ddgs") or "ddgs" in mod
    backends: list[str | None]
    if is_modern:
        backends = list(_DDGS_BACKENDS)
    else:
        backends = list(_LEGACY_BACKENDS) + [None]

    limit = max(1, int(max_results or 5))
    # Over-fetch slightly so de-dupe still fills the limit.
    fetch_n = max(limit, min(limit * 2, 10))

    collected: list[dict[str, str]] = []
    for backend in backends:
        raw = _ddg_text_once(
            ddgs_cls,
            query,
            max_results=fetch_n,
            backend=backend,
            region="wt-wt",
        )
        collected = _collect_normalized(raw, limit)
        if collected:
            return collected[:limit]

    # Retry once on total empty (transient empty pages / rate limits).
    for backend in backends[:3]:
        raw = _ddg_text_once(
            ddgs_cls,
            query,
            max_results=fetch_n,
            backend=backend,
            region="wt-wt",
        )
        collected = _collect_normalized(raw, limit)
        if collected:
            return collected[:limit]

    return []


def web_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Search the web and return ``[{title, url, snippet}, ...]``.

    Provider order:
      1. Tavily when ``TAVILY_API_KEY`` is set
      2. ddgs / duckduckgo_search if importable

    Never raises; returns ``[]`` on any failure or empty input.
    """
    q = (query or "").strip()
    if not q:
        return []
    limit = max(1, int(max_results or 5))

    try:
        if os.getenv("TAVILY_API_KEY"):
            hits = _search_tavily(q, limit)
            if hits:
                return hits[:limit]
        return _search_ddg(q, limit)[:limit]
    except Exception:
        return []
