"""Matching logic between gold-set laws and dossier/prediction laws."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse, urlunparse

_ALNUM = re.compile(r"[^a-z0-9]+", re.IGNORECASE)
_SLUG_STRIP = re.compile(r"[^\w\s-]", re.UNICODE)
_SLUG_SPACE = re.compile(r"[-\s]+")
_SLUG_US = re.compile(r"_+")

# Tracking / document chrome query keys to ignore for URL equality.
_DROP_QUERY_KEYS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
    }
)


def normalize_citation(value: str | None) -> str:
    """Compact alphanumeric citation key (case-insensitive)."""
    if not value:
        return ""
    return _ALNUM.sub("", str(value)).lower()


def normalize_title_slug(value: str | None) -> str:
    """Slugify a title the same way jurisdiction/domain ids are formed."""
    if not value:
        return ""
    text = str(value).strip().lower()
    text = _SLUG_STRIP.sub("", text)
    text = _SLUG_SPACE.sub("_", text)
    text = _SLUG_US.sub("_", text).strip("_")
    return text


def significant_url_key(url: str | None) -> str:
    """Host + path key with trailing slash stripped and tracking params dropped."""
    if not url:
        return ""
    raw = str(url).strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return raw.lower().rstrip("/")

    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (parsed.path or "").rstrip("/") or ""
    # Keep meaningful query pairs (e.g. EUR-Lex eli params) minus tracking.
    query = ""
    if parsed.query:
        kept: list[str] = []
        for part in parsed.query.split("&"):
            if not part:
                continue
            key = part.split("=", 1)[0].lower()
            if key in _DROP_QUERY_KEYS:
                continue
            kept.append(part)
        if kept:
            query = "&".join(sorted(kept))
    # Ignore scheme/fragment differences.
    return urlunparse(("", host, path, "", query, "")).lower()


def _as_mapping(item: Any) -> dict[str, Any]:
    if isinstance(item, Mapping):
        return dict(item)
    if hasattr(item, "model_dump"):
        return dict(item.model_dump())
    raise TypeError(f"Unsupported prediction type: {type(item)!r}")


def _aliases(item: Mapping[str, Any]) -> list[str]:
    raw = item.get("aliases") or []
    if isinstance(raw, str):
        return [raw]
    return [str(a) for a in raw if a]


def _pred_title_keys(pred: Mapping[str, Any]) -> set[str]:
    keys: set[str] = set()
    title = normalize_title_slug(pred.get("title"))
    if title:
        keys.add(title)
    for alias in _aliases(pred):
        slug = normalize_title_slug(alias)
        if slug:
            keys.add(slug)
    return keys


def _gold_title_keys(gold: Mapping[str, Any]) -> set[str]:
    keys: set[str] = set()
    title = normalize_title_slug(gold.get("title"))
    if title:
        keys.add(title)
    for alias in _aliases(gold):
        slug = normalize_title_slug(alias)
        if slug:
            keys.add(slug)
    return keys


def gold_found(gold: Mapping[str, Any], predictions: Sequence[Mapping[str, Any]]) -> bool:
    """Return True if any prediction matches the gold entry.

    Match order / rules:
    1. normalized citation equality (compact alnum)
    2. source_url host+path significant equality
    3. normalized title similarity: slugify title equality OR alias hit
       AND same jurisdiction_id and domain_id
    """
    gold_cite = normalize_citation(gold.get("citation"))
    gold_url = significant_url_key(gold.get("source_url"))
    gold_titles = _gold_title_keys(gold)
    gold_jid = str(gold.get("jurisdiction_id") or "").strip()
    gold_did = str(gold.get("domain_id") or "").strip()

    for pred in predictions:
        p = _as_mapping(pred)

        if gold_cite:
            pred_cite = normalize_citation(p.get("citation"))
            if pred_cite and pred_cite == gold_cite:
                return True

        if gold_url:
            pred_url = significant_url_key(p.get("source_url"))
            if pred_url and pred_url == gold_url:
                return True

        if gold_jid and gold_did:
            pred_jid = str(p.get("jurisdiction_id") or "").strip()
            pred_did = str(p.get("domain_id") or "").strip()
            if pred_jid == gold_jid and pred_did == gold_did:
                pred_titles = _pred_title_keys(p)
                if gold_titles & pred_titles:
                    return True

    return False


def match_gold_to_predictions(
    gold_set: Sequence[Mapping[str, Any]],
    predictions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Score a gold set against predictions; return found/missing detail."""
    preds = [_as_mapping(p) for p in predictions]
    found: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for gold in gold_set:
        g = _as_mapping(gold)
        entry = {
            "gold_id": g.get("gold_id"),
            "title": g.get("title"),
            "jurisdiction_id": g.get("jurisdiction_id"),
            "domain_id": g.get("domain_id"),
        }
        if gold_found(g, preds):
            found.append(entry)
        else:
            missing.append(entry)

    total = len(gold_set)
    found_n = len(found)
    recall = (found_n / total) if total else 0.0
    return {
        "total": total,
        "found": found_n,
        "missing": total - found_n,
        "recall": recall,
        "found_ids": [e["gold_id"] for e in found],
        "missing_ids": [e["gold_id"] for e in missing],
        "found_entries": found,
        "missing_entries": missing,
    }


def load_gold_set(path: str | Path) -> list[dict[str, Any]]:
    """Load gold set JSON (list or ``{\"laws\": [...]}``)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [dict(x) for x in data]
    if isinstance(data, Mapping) and "laws" in data:
        return [dict(x) for x in data["laws"]]
    raise ValueError(f"Unrecognized gold set shape in {path}")


def _iter_law_json_files(laws_dir: Path) -> Iterable[Path]:
    if not laws_dir.is_dir():
        return []
    return sorted(p for p in laws_dir.glob("*.json") if p.is_file())


def load_predictions(path: str | Path) -> list[dict[str, Any]]:
    """Load predictions from a flat JSON list or a dossier directory.

    Dossier mode (directory):
    - prefer each ``laws/*.json`` full record
    - fall back to ``index.json`` ``laws`` entries if laws/ is empty
    """
    p = Path(path)
    if p.is_file():
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [dict(x) for x in data]
        if isinstance(data, Mapping):
            if "laws" in data and isinstance(data["laws"], list):
                return [dict(x) for x in data["laws"]]
            if "predictions" in data and isinstance(data["predictions"], list):
                return [dict(x) for x in data["predictions"]]
        raise ValueError(f"Unrecognized predictions shape in {path}")

    if not p.is_dir():
        raise FileNotFoundError(f"Predictions path not found: {path}")

    laws_dir = p / "laws"
    records: list[dict[str, Any]] = []
    for law_path in _iter_law_json_files(laws_dir):
        try:
            payload = json.loads(law_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            records.append(dict(payload))

    if records:
        return records

    index_path = p / "index.json"
    if index_path.is_file():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        laws = index.get("laws") if isinstance(index, Mapping) else None
        if isinstance(laws, list):
            return [dict(x) for x in laws if isinstance(x, Mapping)]

    return []
