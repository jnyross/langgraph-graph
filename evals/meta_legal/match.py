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

# Strip these instrument-type / regional boilerplate phrases before compacting.
_CITE_BOILERPLATE = re.compile(
    r"""
    \b(
        council\s+regulation
        | commission\s+regulation
        | regulation
        | directive
        | decision
        | proposal
        | public\s+law
        | pub\.?\s*l\.?
        | act
        | statute
        | code
        | reg\.?
        | dir\.?
        | no\.?
        | number
        | article
        | art\.?
        | section
        | sec\.?
        | §§?
        | et\s+seq\.?
        | and\s+following
        | of\s+the\s+european\s+parliament\s+and\s+of\s+the\s+council
        | of\s+the\s+european\s+parliament
        | of\s+the\s+council
        | european\s+union
        | european\s+community
        | \(?eu\)?
        | \(?ec\)?
        | \(?eec\)?
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# US state (and DC) slugs whose parent is united_states for matcher tolerance.
_US_STATE_JIDS: frozenset[str] = frozenset(
    {
        "alabama",
        "alaska",
        "arizona",
        "arkansas",
        "california",
        "colorado",
        "connecticut",
        "delaware",
        "district_of_columbia",
        "florida",
        "georgia_us",
        "hawaii",
        "idaho",
        "illinois",
        "indiana",
        "iowa",
        "kansas",
        "kentucky",
        "louisiana",
        "maine",
        "maryland",
        "massachusetts",
        "michigan",
        "minnesota",
        "mississippi",
        "missouri",
        "montana",
        "nebraska",
        "nevada",
        "new_hampshire",
        "new_jersey",
        "new_mexico",
        "new_york",
        "north_carolina",
        "north_dakota",
        "ohio",
        "oklahoma",
        "oregon",
        "pennsylvania",
        "rhode_island",
        "south_carolina",
        "south_dakota",
        "tennessee",
        "texas",
        "utah",
        "vermont",
        "virginia",
        "washington",
        "west_virginia",
        "wisconsin",
        "wyoming",
    }
)

_PARENT_JURISDICTION: dict[str, str] = {sid: "united_states" for sid in _US_STATE_JIDS}

# Generic tokens ignored when scoring alias/title containment.
_STOP_TITLE_TOKENS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "and",
        "or",
        "for",
        "to",
        "in",
        "on",
        "act",
        "law",
        "code",
        "bill",
        "rule",
        "regulation",
        "directive",
        "statute",
        "section",
        "article",
        "title",
        "chapter",
        "part",
        "amendment",
        "amended",
        "california",  # state name alone is weak when jid already checked loosely
        "united",
        "states",
        "federal",
        "european",
        "union",
        "eu",
        "us",
        "uk",
    }
)


def normalize_citation(value: str | None) -> str:
    """Compact alphanumeric citation key (case-insensitive).

    Also strips common instrument boilerplate (``Regulation (EU)``, ``Directive``,
    ``Pub. L.``, section markers) so ``Reg. (EU) 2016/679`` aligns with
    ``Regulation (EU) 2016/679``.
    """
    keys = {k for k in citation_keys(value) if k and ":" not in k}
    if not keys:
        return ""
    # Prefer the most-stripped non-empty key (shortest) for the primary form.
    return min(keys, key=len)


def citation_keys(value: str | None) -> set[str]:
    """Set of comparable citation keys for a raw citation string."""
    if not value:
        return set()
    text = str(value).strip()
    if not text:
        return set()

    keys: set[str] = set()

    raw = _ALNUM.sub("", text).lower()
    if raw:
        keys.add(raw)

    stripped = _CITE_BOILERPLATE.sub(" ", text)
    stripped = _ALNUM.sub("", stripped).lower()
    if stripped:
        keys.add(stripped)

    # Drop leading year-less instrument noise already handled; also add a form
    # that keeps only digit runs + short alpha codes (usc/cfr/tfeu…).
    compact = re.sub(r"[^a-z0-9]+", "", text.lower())
    # Remove repeated boilerplate tokens left as glued words.
    for token in (
        "regulation",
        "directive",
        "decision",
        "council",
        "commission",
        "proposal",
        "publiclaw",
        "publ",
        "number",
        "no",
        "article",
        "art",
        "section",
        "sec",
        "etseq",
        "europeanunion",
        "europeancommunity",
        "europeaneconomiccommunity",
    ):
        compact = compact.replace(token, "")
    # Soft-strip leading eu/ec only when followed by digits (EU 2016/679).
    compact = re.sub(r"^(?:eu|ec|eec)+(?=\d)", "", compact)
    if compact:
        keys.add(compact)

    # Digit-run fingerprint: only when multi-digit or multi-number (avoid A-1 vs B-1).
    digits = re.findall(r"\d+", text)
    if digits:
        strong = [d for d in digits if len(d) >= 2]
        if len(strong) >= 1:
            keys.add("d:" + "-".join(digits))
        elif len(digits) >= 2:
            keys.add("d:" + "-".join(digits))
        for d in strong:
            if len(d) >= 3:
                keys.add("n:" + d)

    # Alpha+digit code tokens sorted (tfeu101 == 101tfeu).
    alpha_num = re.findall(r"[a-z]{2,}\d+|\d+[a-z]{2,}", raw)
    if alpha_num:
        # Normalize each token to letters-then-digits form.
        normed: list[str] = []
        for tok in alpha_num:
            m = re.fullmatch(r"([a-z]+)(\d+)", tok) or re.fullmatch(r"(\d+)([a-z]+)", tok)
            if m:
                g1, g2 = m.group(1), m.group(2)
                if g1.isalpha():
                    letters, nums = g1, g2
                else:
                    letters, nums = g2, g1
                normed.append(f"{letters}{nums}")
            else:
                normed.append(tok)
        if normed:
            keys.add("t:" + "|".join(sorted(normed)))
            for t in normed:
                keys.add("t1:" + t)

    return {k for k in keys if k}


def citations_match(a: str | None, b: str | None) -> bool:
    """True when any normalized citation key overlaps.

    Prefers exact key overlap. Also allows a multi-digit number from one side
    to appear inside the other's compact alnum form when both share a code
    family hint (usc/cfr/tfeu/eli year-number), carefully avoiding single-digit
    collisions.
    """
    ka = citation_keys(a)
    kb = citation_keys(b)
    if not ka or not kb:
        return False

    # Bare n:<digits> keys are too loose for set intersection alone.
    def _safe(keys: set[str]) -> set[str]:
        return {k for k in keys if not k.startswith("n:")}

    if _safe(ka) & _safe(kb):
        return True

    # Partial range: gold "15usc65016506" vs pred "15usc6501".
    a_raw = _ALNUM.sub("", str(a or "")).lower()
    b_raw = _ALNUM.sub("", str(b or "")).lower()
    if not a_raw or not b_raw:
        return False

    def _family(s: str) -> str:
        for fam in ("usc", "cfr", "tfeu", "teec", "ecfr", "publ", "calciv", "cal"):
            if fam in s:
                return fam
        # EU year/number citations often lack a family token after strip.
        if re.search(r"20\d{2}\d{3,4}", s):
            return "euyear"
        return ""

    fa, fb = _family(a_raw), _family(b_raw)
    if fa and fa == fb:
        shorter, longer = (a_raw, b_raw) if len(a_raw) <= len(b_raw) else (b_raw, a_raw)
        # Require the shorter compact form to be a contiguous substring and
        # at least 6 chars (e.g. 15usc1 is too short / risky).
        if len(shorter) >= 6 and shorter in longer:
            return True

    # Reordered article forms: tfeu101 vs 101tfeu via shared t1 keys already;
    # also compare digit sets when both have a single strong code token.
    a_nums = {m for m in re.findall(r"\d+", str(a or "")) if len(m) >= 2}
    b_nums = {m for m in re.findall(r"\d+", str(b or "")) if len(m) >= 2}
    a_letters = set(re.findall(r"[a-z]{3,}", a_raw))
    b_letters = set(re.findall(r"[a-z]{3,}", b_raw))
    if a_nums and a_nums == b_nums and (a_letters & b_letters):
        return True

    return False


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


def _title_tokens(value: str | None) -> set[str]:
    slug = normalize_title_slug(value)
    if not slug:
        return set()
    return {t for t in slug.split("_") if t and t not in _STOP_TITLE_TOKENS and len(t) > 1}


def _distinctive_alias_tokens(gold: Mapping[str, Any]) -> list[set[str]]:
    """Per-alias token sets that are distinctive enough for containment matching."""
    out: list[set[str]] = []
    # Prefer short aliases (GDPR, CCPA, DMA) and multi-token distinctive phrases.
    known_short = {
        "gdpr",
        "ccpa",
        "cpra",
        "dma",
        "dsa",
        "dga",
        "dmca",
        "coppa",
        "ada",
        "cvaa",
        "avmsd",
        "cdsm",
        "ucpa",
        "tdpsa",
        "fdbr",
        "hsr",
        "ftc",
        "lanham",
        "sherman",
        "clayton",
        "ccpa",
        "aadc",
    }
    candidates = list(_aliases(gold))
    title = gold.get("title")
    if title:
        candidates.append(str(title))
    for raw in candidates:
        raw_s = str(raw).strip()
        if not raw_s:
            continue
        # Preserve original casing signal before slugify lowercases.
        raw_is_acronym = raw_s.isalpha() and raw_s.isupper() and 2 < len(raw_s) <= 6
        tokens = _title_tokens(raw_s)
        if not tokens:
            # Single stop-filtered token may vanish; fall back to raw slug.
            slug = normalize_title_slug(raw_s)
            if slug and "_" not in slug:
                tokens = {slug}
            else:
                continue
        if len(tokens) == 1:
            only = next(iter(tokens))
            if len(only) < 3:
                continue
            if raw_is_acronym or only in known_short:
                out.append({only})
                continue
            # All-caps original multi-letter acronym already handled; reject
            # generic single dictionary words for containment.
            continue
        out.append(tokens)
    return out


def _pred_blob_tokens(pred: Mapping[str, Any]) -> set[str]:
    """Token set from prediction title (+ aliases if any) for containment checks."""
    tokens: set[str] = set()
    tokens |= _title_tokens(pred.get("title"))
    for alias in _aliases(pred):
        tokens |= _title_tokens(alias)
    return tokens


def _norm_jid(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def jurisdictions_compatible(gold_jid: str, pred_jid: str) -> bool:
    """Exact match, or US-state ↔ united_states parent/child pair."""
    g = _norm_jid(gold_jid)
    p = _norm_jid(pred_jid)
    if not g or not p:
        return False
    if g == p:
        return True
    # Only US state parent map (avoid EU member inflation).
    if g in _US_STATE_JIDS and p == "united_states":
        return True
    if p in _US_STATE_JIDS and g == "united_states":
        return True
    if _PARENT_JURISDICTION.get(g) == p or _PARENT_JURISDICTION.get(p) == g:
        return True
    return False


def _title_or_alias_hit(gold: Mapping[str, Any], pred: Mapping[str, Any]) -> bool:
    """Slug equality on titles/aliases, or distinctive gold alias tokens ⊆ pred title."""
    gold_titles = _gold_title_keys(gold)
    pred_titles = _pred_title_keys(pred)
    if gold_titles and pred_titles and (gold_titles & pred_titles):
        return True

    pred_tokens = _pred_blob_tokens(pred)
    if not pred_tokens:
        return False
    for alias_tokens in _distinctive_alias_tokens(gold):
        if alias_tokens and alias_tokens <= pred_tokens:
            return True
        # Also allow all alias tokens to appear as substrings of the joined pred slug.
        pred_slug = normalize_title_slug(pred.get("title")) or ""
        if pred_slug and all(tok in pred_slug for tok in alias_tokens):
            return True
    return False


def gold_found(gold: Mapping[str, Any], predictions: Sequence[Mapping[str, Any]]) -> bool:
    """Return True if any prediction matches the gold entry.

    Match order / rules:
    1. normalized citation key overlap (boilerplate-tolerant)
    2. source_url host+path significant equality
    3. title/alias slug equality OR distinctive gold-alias token containment
       AND same domain_id AND compatible jurisdiction_id
       (exact, or US-state under united_states parent)
    4. strong domain + citation key overlap with parent-jurisdiction tolerance
       is already covered by (1) for pure citation; when citation is weak/empty,
       parent-tolerant title path is (3).
    """
    gold_cite = str(gold.get("citation") or "").strip()
    gold_url = significant_url_key(gold.get("source_url"))
    gold_jid = _norm_jid(gold.get("jurisdiction_id"))
    gold_did = str(gold.get("domain_id") or "").strip()

    for pred in predictions:
        p = _as_mapping(pred)

        if gold_cite and citations_match(gold_cite, p.get("citation")):
            return True

        if gold_url:
            pred_url = significant_url_key(p.get("source_url"))
            if pred_url and pred_url == gold_url:
                return True

        if gold_jid and gold_did:
            pred_jid = _norm_jid(p.get("jurisdiction_id"))
            pred_did = str(p.get("domain_id") or "").strip()
            if pred_did == gold_did and jurisdictions_compatible(gold_jid, pred_jid):
                if _title_or_alias_hit(gold, p):
                    return True
                # Domain + strong citation already returned above. Extra path:
                # if citations match under parent jids only after domain check —
                # kept for clarity when citation on pred is partial but keys hit.
                if gold_cite and citations_match(gold_cite, p.get("citation")):
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
