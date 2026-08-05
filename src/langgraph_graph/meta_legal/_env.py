"""Centralized env-var helpers for meta_legal.

All ``META_LEGAL_*`` (and related) knobs are parsed through these helpers so
defaults, clamping, and ``ValueError`` fallbacks live in one place. Callers
should prefer these over scattered ``os.getenv`` + inline ``try/except``.

The module intentionally stays dependency-free (stdlib only) and never raises:
invalid values fall back to the supplied default.
"""

from __future__ import annotations

import os


def env_str(name: str, default: str = "") -> str:
    """Return stripped string env var or *default* if unset/empty."""
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    return raw if raw else default


def env_int(  # noqa: E501
    name: str, default: int, *, minimum: int | None = None, maximum: int | None = None
) -> int:
    """Parse int env var with fallback to *default* on missing/invalid."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = int(raw.strip())
        except ValueError:
            return default
    if minimum is not None and value < minimum:
        value = minimum
    if maximum is not None and value > maximum:
        value = maximum
    return value


def env_float(  # noqa: E501
    name: str, default: float, *, minimum: float | None = None, maximum: float | None = None
) -> float:
    """Parse float env var with fallback to *default* on missing/invalid."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = float(raw.strip())
        except ValueError:
            return default
    if minimum is not None and value < minimum:
        value = minimum
    if maximum is not None and value > maximum:
        value = maximum
    return value


def env_choice(name: str, default: str, valid: set[str]) -> str:
    """Return lower-cased env var if in *valid*, else *default*."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    cand = raw.strip().lower()
    return cand if cand in valid else default
