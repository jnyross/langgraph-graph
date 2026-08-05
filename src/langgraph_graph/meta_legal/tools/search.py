"""Web search helpers for meta_legal research workers.

Never raises: failures degrade to an empty result list.
Caches identical in-process queries; parallelizes multi-backend DDG attempts.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
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
_BACKEND_ATTEMPT_TIMEOUT_SEC = 3.0
# Overall budget for one parallel backend wave (first non-empty wins).
_BACKEND_WAVE_TIMEOUT_SEC = 4.0

# In-process cache: (normalized_query, max_results) -> results
_SEARCH_CACHE: dict[tuple[str, int], list[dict[str, str]]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 256

# --- global failure circuit breaker (exp_007) ---
# After N consecutive all-backend-empty searches process-wide, short-circuit
# further searches to [] for a cooldown window (backends throttled/dead).
# Env knobs: META_LEGAL_SEARCH_BREAKER_N, META_LEGAL_SEARCH_BREAKER_COOLDOWN_S.
_BREAKER_DEFAULT_N = 3
_BREAKER_DEFAULT_COOLDOWN_S = 120.0
_BREAKER_LOCK = threading.Lock()
_BREAKER_EMPTY_STREAK = 0
_BREAKER_OPENED_AT: float | None = None


# Firecrawl cloud CLI availability (resolved once).
_FIRECRAWL_CLI: bool | None = None
_FIRECRAWL_CLI_LOCK = threading.Lock()
_FIRECRAWL_SEARCH_MAX_PAR_ENV = "META_LEGAL_FIRECRAWL_SEARCH_MAX_PAR"
_FIRECRAWL_SEARCH_SEM: threading.Semaphore | None = None
_FIRECRAWL_SEARCH_SEM_LOCK = threading.Lock()
_FIRECRAWL_SEARCH_SEM_SIZE: int | None = None


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


def _breaker_n() -> int:
    try:
        return max(1, int(os.getenv("META_LEGAL_SEARCH_BREAKER_N", "") or _BREAKER_DEFAULT_N))
    except ValueError:
        return _BREAKER_DEFAULT_N


def _breaker_cooldown_s() -> float:
    try:
        return max(
            0.0,
            float(os.getenv("META_LEGAL_SEARCH_BREAKER_COOLDOWN_S", "") or _BREAKER_DEFAULT_COOLDOWN_S),
        )
    except ValueError:
        return _BREAKER_DEFAULT_COOLDOWN_S


def _breaker_state() -> str:
    """Return ``closed`` | ``open`` | ``half_open``. Never raises."""
    with _BREAKER_LOCK:
        if _BREAKER_OPENED_AT is None:
            return "closed"
        if time.monotonic() - _BREAKER_OPENED_AT < _breaker_cooldown_s():
            return "open"
        return "half_open"


def _breaker_record(success: bool) -> None:
    """Track consecutive all-backend-empty searches; trip after N failures."""
    global _BREAKER_EMPTY_STREAK, _BREAKER_OPENED_AT
    with _BREAKER_LOCK:
        if success:
            _BREAKER_EMPTY_STREAK = 0
            _BREAKER_OPENED_AT = None
            return
        _BREAKER_EMPTY_STREAK += 1
        if _BREAKER_EMPTY_STREAK >= _breaker_n():
            _BREAKER_OPENED_AT = time.monotonic()


def reset_search_breaker() -> None:
    """Reset the global search circuit breaker (tests / process hygiene)."""
    global _BREAKER_EMPTY_STREAK, _BREAKER_OPENED_AT
    with _BREAKER_LOCK:
        _BREAKER_EMPTY_STREAK = 0
        _BREAKER_OPENED_AT = None


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


def _firecrawl_cli_available() -> bool:
    """Cache whether the ``firecrawl`` binary is on PATH."""
    global _FIRECRAWL_CLI
    with _FIRECRAWL_CLI_LOCK:
        if _FIRECRAWL_CLI is None:
            _FIRECRAWL_CLI = shutil.which("firecrawl") is not None
        return _FIRECRAWL_CLI


def _firecrawl_search_semaphore() -> threading.Semaphore:
    """Limit concurrent ``firecrawl search`` subprocesses (default 12)."""
    global _FIRECRAWL_SEARCH_SEM, _FIRECRAWL_SEARCH_SEM_SIZE
    try:
        size = max(1, int(os.getenv(_FIRECRAWL_SEARCH_MAX_PAR_ENV) or "12"))
    except ValueError:
        size = 12
    with _FIRECRAWL_SEARCH_SEM_LOCK:
        if _FIRECRAWL_SEARCH_SEM is None or _FIRECRAWL_SEARCH_SEM_SIZE != size:
            _FIRECRAWL_SEARCH_SEM = threading.Semaphore(size)
            _FIRECRAWL_SEARCH_SEM_SIZE = size
        return _FIRECRAWL_SEARCH_SEM


def _search_firecrawl_cli(query: str, max_results: int) -> list[dict[str, str]]:
    """Search via authenticated Firecrawl cloud CLI. Never raises."""
    q = (query or "").strip()
    if not q:
        return []
    if not _firecrawl_cli_available():
        return []
    limit = max(1, int(max_results or 5))
    sem = _firecrawl_search_semaphore()
    acquired = False
    completed: subprocess.CompletedProcess[str] | None = None
    try:
        # Don't queue forever under cell stampede; budget owns wall-clock.
        acquired = sem.acquire(timeout=8.0)
        if not acquired:
            return []
        completed = subprocess.run(
            ["firecrawl", "search", q, "--limit", str(limit), "--json"],
            capture_output=True,
            text=True,
            timeout=12,
        )
    except FileNotFoundError:
        with _FIRECRAWL_CLI_LOCK:
            _FIRECRAWL_CLI = False
        return []
    except Exception:
        return []
    finally:
        if acquired:
            try:
                sem.release()
            except Exception:
                pass

    if completed is None or completed.returncode != 0:
        return []

    try:
        payload = json.loads(completed.stdout or "")
    except Exception:
        return []

    data = payload.get("data") if isinstance(payload, dict) else None
    web = data.get("web") if isinstance(data, dict) else None
    if not isinstance(web, list):
        return []

    results: list[dict[str, str]] = []
    for item in web:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_result(
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "snippet": item.get("description") or item.get("snippet") or "",
            }
        )
        if normalized:
            results.append(normalized)
        if len(results) >= limit:
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


def _search_ddg(query: str, max_results: int, *, single_wave: bool = False) -> list[dict[str, str]]:
    """Search via ``ddgs`` (preferred) or legacy ``duckduckgo_search``.

    Tries multiple backends in parallel (small pool), retries once on empty,
    de-dupes by URL. Never raises. Bounded by wave/attempt timeouts so a hung
    backend cannot stall a research cell forever. ``single_wave`` limits the
    probe to one backend wave (used when the failure breaker is half-open).
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

    if single_wave:
        return []

    # Single short retry on the first two backends only (transient empties).
    collected = _run_backends(backends[:2])
    if collected:
        return collected[:limit]

    return []


def web_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Search the web and return ``[{title, url, snippet}, ...]``.

    Provider order:
      1. Tavily when ``TAVILY_API_KEY`` is set
      2. Firecrawl cloud CLI when ``firecrawl`` binary is on PATH
      3. ddgs / duckduckgo_search if importable

    Identical queries are served from an in-process cache within the process.
    A process-wide circuit breaker short-circuits to ``[]`` for a cooldown
    window after N consecutive all-backend-empty searches (throttled/dead
    backends); the first probe after cooldown runs a single backend wave.
    Never raises; returns ``[]`` on any failure or empty input.
    """
    q = (query or "").strip()
    if not q:
        return []
    limit = max(1, int(max_results or 5))

    cached = _cache_get(q, limit)
    if cached is not None:
        return cached[:limit]

    breaker = _breaker_state()
    if breaker == "open":
        return []

    try:
        if os.getenv("TAVILY_API_KEY"):
            hits = _search_tavily(q, limit)
            if hits:
                out = hits[:limit]
                _cache_put(q, limit, out)
                _breaker_record(True)
                return out
        if _firecrawl_cli_available():
            hits = _search_firecrawl_cli(q, limit)
            if hits:
                out = hits[:limit]
                _cache_put(q, limit, out)
                _breaker_record(True)
                return out
        out = _search_ddg(q, limit, single_wave=breaker == "half_open")[:limit]
        # Cache empty results too to avoid hammering dead backends for same query.
        _cache_put(q, limit, out)
        _breaker_record(bool(out))
        return out
    except Exception:
        return []
