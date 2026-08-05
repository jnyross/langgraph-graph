"""Web search helpers for meta_legal research workers.

Never raises: failures degrade to an empty result list.
Caches identical in-process queries; parallelizes multi-backend DDG attempts.
"""

from __future__ import annotations

import os
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed
from typing import Any
from urllib.parse import urlsplit, urlunsplit


class _DaemonThreadPoolExecutor(ThreadPoolExecutor):
    """ThreadPoolExecutor whose workers are daemons (safe process exit on hang)."""

    def _adjust_thread_count(self) -> None:  # type: ignore[override]
        super()._adjust_thread_count()
        for t in list(getattr(self, "_threads", ())):
            try:
                t.daemon = True
            except Exception:
                pass


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

# Bound each backend probe so a hung provider cannot stall the worker forever.
_BACKEND_ATTEMPT_TIMEOUT_SEC = 5.0
# Overall budget for one parallel backend wave (first non-empty wins).
_BACKEND_WAVE_TIMEOUT_SEC = 6.0

# In-process cache: (normalized_query, max_results) -> results
_SEARCH_CACHE: dict[tuple[str, int], list[dict[str, str]]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 256


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


def _cache_key(query: str, max_results: int) -> tuple[str, int]:
    return (query.strip().lower(), max(1, int(max_results or 5)))


def _cache_get(query: str, max_results: int) -> list[dict[str, str]] | None:
    key = _cache_key(query, max_results)
    with _CACHE_LOCK:
        hit = _SEARCH_CACHE.get(key)
        if hit is None:
            return None
        # Return a shallow copy so callers cannot mutate the cache entry.
        return [dict(item) for item in hit]


def _cache_put(query: str, max_results: int, results: list[dict[str, str]]) -> None:
    key = _cache_key(query, max_results)
    stored = [dict(item) for item in results]
    with _CACHE_LOCK:
        if len(_SEARCH_CACHE) >= _CACHE_MAX and key not in _SEARCH_CACHE:
            # Drop an arbitrary oldest-ish entry (FIFO via insertion order).
            try:
                _SEARCH_CACHE.pop(next(iter(_SEARCH_CACHE)))
            except StopIteration:
                pass
        _SEARCH_CACHE[key] = stored


def clear_search_cache() -> None:
    """Clear the in-process search cache (tests / long-running process hygiene)."""
    with _CACHE_LOCK:
        _SEARCH_CACHE.clear()


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


def _backend_attempt(
    ddgs_cls: Any,
    query: str,
    *,
    fetch_n: int,
    backend: str | None,
    limit: int,
) -> list[dict[str, str]]:
    raw = _ddg_text_once(
        ddgs_cls,
        query,
        max_results=fetch_n,
        backend=backend,
        region="wt-wt",
    )
    return _collect_normalized(raw, limit)


def _search_ddg(query: str, max_results: int) -> list[dict[str, str]]:
    """Search via ``ddgs`` (preferred) or legacy ``duckduckgo_search``.

    Tries multiple backends in parallel (small pool), retries once on empty,
    de-dupes by URL. Never raises. Bounded by wave/attempt timeouts so a hung
    backend cannot stall a research cell forever.
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

    def _run_backends(backend_list: list[str | None]) -> list[dict[str, str]]:
        if not backend_list:
            return []
        # Parallel backend probes; first non-empty wins (cancel remaining).
        # Daemon workers + non-waiting shutdown so hung providers cannot pin exit.
        workers = min(4, len(backend_list))
        pool: ThreadPoolExecutor = _DaemonThreadPoolExecutor(max_workers=workers)
        try:
            futures = {
                pool.submit(
                    _backend_attempt,
                    ddgs_cls,
                    query,
                    fetch_n=fetch_n,
                    backend=backend,
                    limit=limit,
                ): backend
                for backend in backend_list
            }
            try:
                for fut in as_completed(futures, timeout=_BACKEND_WAVE_TIMEOUT_SEC):
                    try:
                        hits = fut.result(timeout=_BACKEND_ATTEMPT_TIMEOUT_SEC) or []
                    except FuturesTimeout:
                        hits = []
                    except Exception:
                        hits = []
                    if hits:
                        for other in futures:
                            if other is not fut:
                                other.cancel()
                        return hits[:limit]
            except FuturesTimeout:
                for fut in futures:
                    fut.cancel()
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return []

    collected = _run_backends(backends)
    if collected:
        return collected[:limit]

    # Single short retry on the first two backends only (transient empties).
    collected = _run_backends(backends[:2])
    if collected:
        return collected[:limit]

    return []


def web_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Search the web and return ``[{title, url, snippet}, ...]``.

    Provider order:
      1. Tavily when ``TAVILY_API_KEY`` is set
      2. ddgs / duckduckgo_search if importable

    Identical queries are served from an in-process cache within the process.
    Never raises; returns ``[]`` on any failure or empty input.
    """
    q = (query or "").strip()
    if not q:
        return []
    limit = max(1, int(max_results or 5))

    cached = _cache_get(q, limit)
    if cached is not None:
        return cached[:limit]

    try:
        if os.getenv("TAVILY_API_KEY"):
            hits = _search_tavily(q, limit)
            if hits:
                out = hits[:limit]
                _cache_put(q, limit, out)
                return out
        out = _search_ddg(q, limit)[:limit]
        # Cache empty results too to avoid hammering dead backends for same query.
        _cache_put(q, limit, out)
        return out
    except Exception:
        return []
