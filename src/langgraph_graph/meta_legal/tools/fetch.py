"""URL fetch helpers for meta_legal research workers.

Never raises: failures degrade to an empty string.
"""

from __future__ import annotations

import re
from html import unescape
from typing import Final

_DEFAULT_TIMEOUT: Final[float] = 20.0
_SCRIPT_STYLE_RE = re.compile(
    r"(?is)<(script|style|noscript|svg|iframe)\b[^>]*>.*?</\1\s*>"
)
_TAG_RE = re.compile(r"(?s)<[^>]+>")
_WS_RE = re.compile(r"[ \t\f\v]+")
_BLANK_RE = re.compile(r"\n{3,}")


def _html_to_text(html: str) -> str:
    """Rough HTML → plain text: drop scripts/styles, strip tags, collapse space."""
    text = _SCRIPT_STYLE_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", text)
    text = unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS_RE.sub(" ", text)
    text = _BLANK_RE.sub("\n\n", text)
    return text.strip()


def fetch_url(url: str, max_chars: int = 12000) -> str:
    """GET ``url`` and return plain-ish page text (truncated).

    Uses httpx with a ~20s timeout. Strips script/style blocks roughly.
    Never raises; returns ``""`` on failure or empty input.
    """
    target = (url or "").strip()
    if not target:
        return ""
    if not (target.startswith("http://") or target.startswith("https://")):
        return ""

    limit = max(0, int(max_chars if max_chars is not None else 12000))

    try:
        import httpx
    except Exception:
        return ""

    try:
        with httpx.Client(
            timeout=_DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; meta-legal-research/0.1; +https://localhost) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        ) as client:
            response = client.get(target)
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").lower()
            raw = response.text or ""
    except Exception:
        return ""

    if not raw:
        return ""

    if "html" in content_type or "<html" in raw[:500].lower() or "<!doctype" in raw[:200].lower():
        text = _html_to_text(raw)
    else:
        text = raw.strip()

    if limit and len(text) > limit:
        return text[:limit]
    return text
