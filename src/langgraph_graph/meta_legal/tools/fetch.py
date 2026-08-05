"""URL fetch helpers for meta_legal research workers.

Never raises: failures degrade to an empty string.
Thread-safe for concurrent fetches within a cell worker.
"""

from __future__ import annotations

import os
import re
import threading
import time
from html import unescape
from typing import Any, Final
from urllib.parse import urlparse

_DEFAULT_TIMEOUT: Final[float] = 28.0
_MAX_ATTEMPTS: Final[int] = 2  # initial try + one retry
FIRECRAWL_API_URL_ENV: Final[str] = "FIRECRAWL_API_URL"
FETCH_BACKEND_ENV: Final[str] = "META_LEGAL_FETCH_BACKEND"
FIRECRAWL_MAX_PAR_ENV: Final[str] = "META_LEGAL_FIRECRAWL_MAX_PAR"
_SCRIPT_STYLE_RE = re.compile(
    r"(?is)<(script|style|noscript|svg|iframe)\b[^>]*>.*?</\1\s*>"
)
_TAG_RE = re.compile(r"(?s)<[^>]+>")
_WS_RE = re.compile(r"[ \t\f\v]+")
_BLANK_RE = re.compile(r"\n{3,}")

_THREAD_LOCAL = threading.local()
_CLIENT_LOCK = threading.Lock()
_HOST_LOCK = threading.Lock()
_HOST_NEXT_OK: dict[str, float] = {}
_FIRECRAWL_SEM: threading.Semaphore | None = None
_FIRECRAWL_SEM_LOCK = threading.Lock()
_FIRECRAWL_SEM_SIZE: int | None = None


def _html_to_text(html: str) -> str:
    """Rough HTML → plain text: drop scripts/styles, strip tags, collapse space."""
    text = _SCRIPT_STYLE_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", text)
    text = unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS_RE.sub(" ", text)
    text = _BLANK_RE.sub("\n\n", text)
    return text.strip()


def _default_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (compatible; meta-legal-research/0.1; +https://localhost) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        # Prefer HTML for statute / regulator pages; still accept XML/text fallbacks.
        "Accept": (
            "text/html,application/xhtml+xml;q=0.95,"
            "application/xml;q=0.8,text/plain;q=0.7,*/*;q=0.5"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }


def _get_client() -> Any | None:
    """Return a thread-local httpx.Client (follow_redirects, shared headers)."""
    client = getattr(_THREAD_LOCAL, "client", None)
    if client is not None:
        return client
    try:
        import httpx
    except Exception:
        return None
    with _CLIENT_LOCK:
        client = getattr(_THREAD_LOCAL, "client", None)
        if client is not None:
            return client
        try:
            client = httpx.Client(
                timeout=_DEFAULT_TIMEOUT,
                follow_redirects=True,
                headers=_default_headers(),
                max_redirects=10,
            )
        except Exception:
            return None
        _THREAD_LOCAL.client = client
        return client


def _close_thread_client() -> None:
    """Best-effort close of the current thread's httpx client (tests / cleanup)."""
    client = getattr(_THREAD_LOCAL, "client", None)
    if client is None:
        return
    try:
        client.close()
    except Exception:
        pass
    try:
        delattr(_THREAD_LOCAL, "client")
    except Exception:
        _THREAD_LOCAL.client = None


def _response_to_text(response: Any, limit: int) -> str:
    content_type = (response.headers.get("content-type") or "").lower()
    raw = response.text or ""
    if not raw:
        return ""

    # Prefer HTML extraction when content-type or body looks like markup.
    looks_html = (
        "html" in content_type
        or "xhtml" in content_type
        or "<html" in raw[:500].lower()
        or "<!doctype" in raw[:200].lower()
    )
    if looks_html:
        text = _html_to_text(raw)
    elif "xml" in content_type or raw.lstrip().startswith("<?xml") or raw.lstrip().startswith("<"):
        # Many legal portals serve XML/HTML-ish payloads; strip tags when useful.
        text = _html_to_text(raw) if "<" in raw[:1000] else raw.strip()
    else:
        text = raw.strip()

    if limit and len(text) > limit:
        return text[:limit]
    return text


def _fetch_once(client: Any, target: str, limit: int) -> str:
    response = client.get(target, follow_redirects=True)
    response.raise_for_status()
    return _response_to_text(response, limit)


def _host_spacing_seconds() -> float:
    """Optional min gap between fetches to the same host (env ms → seconds)."""
    raw = (os.getenv("META_LEGAL_FETCH_HOST_SPACING_MS") or "").strip()
    if not raw:
        return 0.0
    try:
        ms = float(raw)
    except ValueError:
        return 0.0
    return max(0.0, ms / 1000.0)


def _wait_host_spacing(url: str) -> None:
    """Serialize lightly per host when spacing is configured."""
    gap = _host_spacing_seconds()
    if gap <= 0:
        return
    try:
        host = (urlparse(url).netloc or "").lower()
    except Exception:
        host = ""
    if not host:
        return
    with _HOST_LOCK:
        now = time.monotonic()
        ready_at = _HOST_NEXT_OK.get(host, 0.0)
        delay = ready_at - now
        if delay > 0:
            time.sleep(delay)
            now = time.monotonic()
        _HOST_NEXT_OK[host] = now + gap


def _firecrawl_api_url() -> str:
    return (os.getenv(FIRECRAWL_API_URL_ENV) or "http://localhost:3002").rstrip("/")


def _fetch_backend() -> str:
    raw = (os.getenv(FETCH_BACKEND_ENV) or "auto").strip().lower()
    if raw in {"auto", "firecrawl", "httpx"}:
        return raw
    return "auto"


def _firecrawl_semaphore() -> threading.Semaphore:
    """Module-level semaphore sized by META_LEGAL_FIRECRAWL_MAX_PAR (default 20)."""
    global _FIRECRAWL_SEM, _FIRECRAWL_SEM_SIZE
    try:
        size = max(1, int(os.getenv(FIRECRAWL_MAX_PAR_ENV) or "20"))
    except ValueError:
        size = 20
    with _FIRECRAWL_SEM_LOCK:
        if _FIRECRAWL_SEM is None or _FIRECRAWL_SEM_SIZE != size:
            _FIRECRAWL_SEM = threading.Semaphore(size)
            _FIRECRAWL_SEM_SIZE = size
        return _FIRECRAWL_SEM


def _firecrawl_skip_host(url: str) -> bool:
    """Hosts known to fail local Firecrawl (bot walls); skip straight to httpx."""
    try:
        host = (urlparse(url).netloc or "").lower()
    except Exception:
        return False
    # Verified SCRAPE_ALL_ENGINES_FAILED on self-hosted playwright stack.
    return host == "eur-lex.europa.eu" or host.endswith(".eur-lex.europa.eu")


def _fetch_via_firecrawl(url: str, max_chars: int) -> str:
    """POST local/self-hosted Firecrawl ``/v2/scrape``; never raises.

    Returns truncated markdown on success, else ``""``.
    Fail-fast timeouts (12s scrape / 15s HTTP) so auto mode can fall through
    to httpx without stacking a 30s+ hang on every blocked URL.
    """
    target = (url or "").strip()
    if not target:
        return ""
    if _firecrawl_skip_host(target):
        return ""
    limit = max(0, int(max_chars if max_chars is not None else 12000))
    try:
        import httpx
    except Exception:
        return ""

    sem = _firecrawl_semaphore()
    acquired = False
    try:
        # Bound queue wait under load (sem size + this ≈ worst-case gate).
        acquired = sem.acquire(timeout=5.0)
        if not acquired:
            return ""
        response = httpx.post(
            f"{_firecrawl_api_url()}/v2/scrape",
            json={
                "url": target,
                "formats": ["markdown"],
                "onlyMainContent": True,
                "timeout": 12000,
            },
            timeout=15.0,
        )
        if response.status_code != 200:
            return ""
        body = response.json()
        if not isinstance(body, dict) or body.get("success") is not True:
            return ""
        data = body.get("data") or {}
        if not isinstance(data, dict):
            return ""
        md = data.get("markdown") or ""
        if not isinstance(md, str) or not md:
            return ""
        if limit and len(md) > limit:
            return md[:limit]
        return md
    except Exception:
        return ""
    finally:
        if acquired:
            try:
                sem.release()
            except Exception:
                pass


def _fetch_via_httpx(url: str, max_chars: int) -> str:
    """Existing httpx path (thread-local client, retry, host spacing). Never raises."""
    target = (url or "").strip()
    if not target:
        return ""
    if not (target.startswith("http://") or target.startswith("https://")):
        return ""

    limit = max(0, int(max_chars if max_chars is not None else 12000))
    client = _get_client()
    if client is None:
        return ""

    _wait_host_spacing(target)

    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return _fetch_once(client, target, limit)
        except Exception as exc:
            last_exc = exc
            # Recreate client after connection-level failures before retry.
            if attempt + 1 < _MAX_ATTEMPTS:
                _close_thread_client()
                client = _get_client()
                if client is None:
                    return ""
            continue

    _ = last_exc  # retained for potential future debug hooks
    return ""


def fetch_url(url: str, max_chars: int = 12000) -> str:
    """GET ``url`` and return plain-ish page text (truncated).

    Backend via ``META_LEGAL_FETCH_BACKEND``:
      - ``auto`` (default): try local Firecrawl scrape first, fall through to httpx
      - ``firecrawl``: Firecrawl only
      - ``httpx``: thread-local httpx client only (exp004 path)

    Firecrawl concurrency gated by ``META_LEGAL_FIRECRAWL_MAX_PAR`` (default 20).
    Never raises; returns ``""`` on failure or empty input.
    """
    target = (url or "").strip()
    if not target:
        return ""
    if not (target.startswith("http://") or target.startswith("https://")):
        return ""

    limit = max(0, int(max_chars if max_chars is not None else 12000))
    backend = _fetch_backend()

    if backend == "httpx":
        return _fetch_via_httpx(target, limit)
    if backend == "firecrawl":
        return _fetch_via_firecrawl(target, limit)

    # auto: firecrawl first, httpx fallback
    text = _fetch_via_firecrawl(target, limit)
    if text:
        return text
    return _fetch_via_httpx(target, limit)
