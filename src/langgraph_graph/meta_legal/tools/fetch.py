"""URL fetch helpers for meta_legal research workers.

Never raises: failures degrade to an empty string.
Thread-safe for concurrent fetches within a cell worker.
"""

from __future__ import annotations

import re
import threading
from html import unescape
from typing import Any, Final

_DEFAULT_TIMEOUT: Final[float] = 28.0
_MAX_ATTEMPTS: Final[int] = 2  # initial try + one retry
_SCRIPT_STYLE_RE = re.compile(
    r"(?is)<(script|style|noscript|svg|iframe)\b[^>]*>.*?</\1\s*>"
)
_TAG_RE = re.compile(r"(?s)<[^>]+>")
_WS_RE = re.compile(r"[ \t\f\v]+")
_BLANK_RE = re.compile(r"\n{3,}")

_THREAD_LOCAL = threading.local()
_CLIENT_LOCK = threading.Lock()


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


def fetch_url(url: str, max_chars: int = 12000) -> str:
    """GET ``url`` and return plain-ish page text (truncated).

    Uses a thread-local httpx client with redirect following, ~28s timeout,
    HTML-preferring Accept header, and one automatic retry on transient failure.
    Never raises; returns ``""`` on failure or empty input.
    """
    target = (url or "").strip()
    if not target:
        return ""
    if not (target.startswith("http://") or target.startswith("https://")):
        return ""

    limit = max(0, int(max_chars if max_chars is not None else 12000))
    client = _get_client()
    if client is None:
        return ""

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
