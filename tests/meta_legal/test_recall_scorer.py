"""Tests for independent meta_legal gold set + recall scorer."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from evals.meta_legal.match import (
    gold_found,
    load_gold_set,
    load_predictions,
    match_gold_to_predictions,
    normalize_citation,
    normalize_title_slug,
    significant_url_key,
)
from evals.meta_legal.score_recall import main as score_main
from evals.meta_legal.score_recall import score_recall, summarize

ROOT = Path(__file__).resolve().parents[2]
GOLD_PATH = ROOT / "evals" / "meta_legal" / "gold_set.json"
MANIFEST_PATH = ROOT / "evals" / "meta_legal" / "gold_set_manifest.json"

REQUIRED_FIELDS = {
    "gold_id",
    "title",
    "jurisdiction_id",
    "jurisdiction_name",
    "domain_id",
    "citation",
    "source_url",
    "aliases",
    "obscurity",
}
DOMAINS = {"privacy", "competition", "youth_safety", "ip", "accessibility"}
OBSCURITY = {"high", "medium", "low"}


def test_gold_set_has_exactly_100_valid_entries() -> None:
    laws = load_gold_set(GOLD_PATH)
    assert len(laws) == 100
    ids = [law["gold_id"] for law in laws]
    assert len(set(ids)) == 100

    for law in laws:
        missing = REQUIRED_FIELDS - set(law)
        assert not missing, f"{law.get('gold_id')}: missing {missing}"
        assert law["domain_id"] in DOMAINS
        assert law["obscurity"] in OBSCURITY
        assert isinstance(law["aliases"], list) and law["aliases"]
        assert str(law["citation"]).strip()
        assert str(law["source_url"]).startswith("http")
        assert str(law["jurisdiction_id"]).strip()
        assert str(law["jurisdiction_name"]).strip()

    # Geographic + domain diversity sanity
    jurisdictions = {law["jurisdiction_id"] for law in laws}
    domains_present = {law["domain_id"] for law in laws}
    assert domains_present == DOMAINS
    assert len(jurisdictions) >= 15
    for anchor in (
        "european_union",
        "united_states",
        "california",
        "united_kingdom",
        "brazil",
        "india",
        "australia",
        "canada",
        "japan",
        "south_korea",
        "singapore",
        "south_africa",
    ):
        assert anchor in jurisdictions


def test_gold_manifest_provenance_independent() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["entry_count"] == 100
    assert manifest["built_at"] == "2026-08-05"
    provenance = manifest["provenance"]
    assert provenance["method"] == "independent_deep_research"
    blocked = " ".join(provenance.get("not_derived_from") or [])
    assert "data/dossiers" in blocked


def test_normalize_citation_compacts_alnum() -> None:
    assert normalize_citation("Regulation (EU) 2016/679") == normalize_citation(
        "regulation eu 2016 679"
    )
    assert normalize_citation("15 U.S.C. § 45") == "15usc45"
    assert normalize_citation("") == ""
    assert normalize_citation(None) == ""


def test_normalize_title_slug() -> None:
    assert normalize_title_slug("Digital Markets Act") == "digital_markets_act"
    assert normalize_title_slug("  GDPR  ") == "gdpr"
    assert normalize_title_slug(None) == ""


def test_significant_url_key_strips_tracking_and_slash() -> None:
    a = significant_url_key("https://www.Example.com/path/to/law/?utm_source=x#frag")
    b = significant_url_key("http://example.com/path/to/law")
    assert a == b
    assert a == "//example.com/path/to/law"


def test_match_by_citation() -> None:
    gold = {
        "gold_id": "g1",
        "title":"General Data Protection Regulation",
        "jurisdiction_id": "european_union",
        "domain_id": "privacy",
        "citation": "Regulation (EU) 2016/679",
        "source_url": "https://eur-lex.europa.eu/eli/reg/2016/679/oj",
        "aliases": ["GDPR"],
    }
    preds = [
        {
            "title": "Something else",
            "jurisdiction_id": "united_states",
            "domain_id": "ip",
            "citation": "Regulation (EU) 2016/679",
            "source_url": "https://example.test/other",
        }
    ]
    assert gold_found(gold, preds) is True


def test_match_by_source_url() -> None:
    gold = {
        "gold_id": "g2",
        "title": "Digital Markets Act",
        "jurisdiction_id": "european_union",
        "domain_id": "competition",
        "citation": "Regulation (EU) 2022/1925",
        "source_url": "https://eur-lex.europa.eu/eli/reg/2022/1925/oj",
        "aliases": ["DMA"],
    }
    preds = [
        {
            "title": "Unrelated title",
            "jurisdiction_id": "brazil",
            "domain_id": "privacy",
            "citation": "nope",
            "source_url": "https://www.eur-lex.europa.eu/eli/reg/2022/1925/oj?utm_campaign=x",
        }
    ]
    assert gold_found(gold, preds) is True


def test_match_by_title_alias_same_jurisdiction_domain() -> None:
    gold = {
        "gold_id": "g3",
        "title": "California Consumer Privacy Act",
        "jurisdiction_id": "california",
        "domain_id": "privacy",
        "citation": "Cal. Civ. Code §§ 1798.100 et seq.",
        "source_url": "https://example.test/ccpa",
        "aliases": ["CCPA"],
    }
    # Alias hit + same j/d
    preds_hit = [
        {
            "title": "CCPA",
            "jurisdiction_id": "california",
            "domain_id": "privacy",
            "citation": "different-cite",
            "source_url": "https://other.test/x",
        }
    ]
    assert gold_found(gold, preds_hit) is True

    # Same title slug but wrong jurisdiction → miss
    preds_miss = [
        {
            "title": "California Consumer Privacy Act",
            "jurisdiction_id": "united_states",
            "domain_id": "privacy",
            "citation": "different-cite",
            "source_url": "https://other.test/x",
        }
    ]
    assert gold_found(gold, preds_miss) is False


def test_match_gold_to_predictions_summary() -> None:
    gold_set = [
        {
            "gold_id": "a",
            "title": "Law A",
            "jurisdiction_id": "eu",
            "domain_id": "privacy",
            "citation": "A-1",
            "source_url": "https://a.test/a",
            "aliases": [],
        },
        {
            "gold_id": "b",
            "title": "Law B",
            "jurisdiction_id": "us",
            "domain_id": "ip",
            "citation": "B-1",
            "source_url": "https://b.test/b",
            "aliases": ["Bee"],
        },
    ]
    preds = [
        {
            "title": "Other",
            "jurisdiction_id": "eu",
            "domain_id": "privacy",
            "citation": "A1",
            "source_url": "https://z.test",
        }
    ]
    result = match_gold_to_predictions(gold_set, preds)
    assert result["total"] == 2
    assert result["found"] == 1
    assert result["missing"] == 1
    assert result["recall"] == pytest.approx(0.5)
    assert result["found_ids"] == ["a"]
    assert result["missing_ids"] == ["b"]
    summary = summarize(result)
    assert set(summary) >= {"total", "found", "missing", "recall"}


def test_load_predictions_from_dossier_laws_dir(tmp_path: Path) -> None:
    laws_dir = tmp_path / "laws"
    laws_dir.mkdir()
    (laws_dir / "one.json").write_text(
        json.dumps(
            {
                "law_id": "1",
                "title": "GDPR",
                "jurisdiction_id": "european_union",
                "domain_id": "privacy",
                "citation": "Regulation (EU) 2016/679",
                "source_url": "https://eur-lex.europa.eu/eli/reg/2016/679/oj",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "index.json").write_text(
        json.dumps({"laws": [{"title": "should-not-be-used-when-laws-present"}]}),
        encoding="utf-8",
    )
    preds = load_predictions(tmp_path)
    assert len(preds) == 1
    assert preds[0]["title"] == "GDPR"


def test_load_predictions_from_index_fallback(tmp_path: Path) -> None:
    (tmp_path / "laws").mkdir()
    (tmp_path / "index.json").write_text(
        json.dumps(
            {
                "laws": [
                    {
                        "title": "From Index",
                        "jurisdiction_id": "united_states",
                        "domain_id": "ip",
                        "citation": "17 U.S.C. § 512",
                        "source_url": "https://www.law.cornell.edu/uscode/text/17/512",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    preds = load_predictions(tmp_path)
    assert len(preds) == 1
    assert preds[0]["title"] == "From Index"


def test_load_predictions_from_flat_json(tmp_path: Path) -> None:
    path = tmp_path / "preds.json"
    path.write_text(
        json.dumps(
            [
                {
                    "title": "Flat",
                    "jurisdiction_id": "x",
                    "domain_id": "privacy",
                    "citation": "C1",
                    "source_url": "https://x.test/c1",
                }
            ]
        ),
        encoding="utf-8",
    )
    preds = load_predictions(path)
    assert preds[0]["title"] == "Flat"


def test_score_recall_perfect_from_gold_self(tmp_path: Path) -> None:
    """Predictions that mirror gold citations should hit ~1.0 recall."""
    gold = load_gold_set(GOLD_PATH)
    preds = [
        {
            "title": g["title"],
            "jurisdiction_id": g["jurisdiction_id"],
            "domain_id": g["domain_id"],
            "citation": g["citation"],
            "source_url": g["source_url"],
            "aliases": list(g.get("aliases") or []),
        }
        for g in gold
    ]
    pred_path = tmp_path / "all.json"
    pred_path.write_text(json.dumps(preds), encoding="utf-8")
    result = score_recall(GOLD_PATH, pred_path)
    assert result["total"] == 100
    assert result["found"] == 100
    assert result["recall"] == pytest.approx(1.0)


def test_cli_threshold_exit_codes(tmp_path: Path) -> None:
    gold = [
        {
            "gold_id": "g1",
            "title": "Alpha Law",
            "jurisdiction_id": "eu",
            "jurisdiction_name": "EU",
            "domain_id": "privacy",
            "citation": "ALPHA-1",
            "source_url": "https://a.test/1",
            "aliases": ["Alpha"],
            "obscurity": "low",
        },
        {
            "gold_id": "g2",
            "title": "Beta Law",
            "jurisdiction_id": "us",
            "jurisdiction_name": "US",
            "domain_id": "ip",
            "citation": "BETA-1",
            "source_url": "https://b.test/1",
            "aliases": ["Beta"],
            "obscurity": "low",
        },
    ]
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(json.dumps(gold), encoding="utf-8")

    # 1/2 found → recall 0.5
    preds_path = tmp_path / "preds.json"
    preds_path.write_text(
        json.dumps(
            [
                {
                    "title": "Alpha Law",
                    "jurisdiction_id": "eu",
                    "domain_id": "privacy",
                    "citation": "ALPHA1",
                    "source_url": "https://other.test",
                }
            ]
        ),
        encoding="utf-8",
    )

    # Direct main() exit codes
    assert (
        score_main(
            [
                "--gold",
                str(gold_path),
                "--predictions",
                str(preds_path),
                "--threshold",
                "0.4",
            ]
        )
        == 0
    )
    assert (
        score_main(
            [
                "--gold",
                str(gold_path),
                "--predictions",
                str(preds_path),
                "--threshold",
                "0.95",
            ]
        )
        == 1
    )

    # Subprocess CLI (module entry)
    proc_pass = subprocess.run(
        [
            sys.executable,
            "-m",
            "evals.meta_legal.score_recall",
            "--gold",
            str(gold_path),
            "--predictions",
            str(preds_path),
            "--threshold",
            "0.5",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_pass.returncode == 0
    payload = json.loads(proc_pass.stdout)
    assert payload["total"] == 2
    assert payload["found"] == 1
    assert payload["missing"] == 1
    assert payload["recall"] == pytest.approx(0.5)

    proc_fail = subprocess.run(
        [
            sys.executable,
            "-m",
            "evals.meta_legal.score_recall",
            "--gold",
            str(gold_path),
            "--predictions",
            str(preds_path),
            "--threshold",
            "0.95",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_fail.returncode == 1


def test_cli_dossier_flag(tmp_path: Path) -> None:
    gold = [
        {
            "gold_id": "g1",
            "title": "DMA",
            "jurisdiction_id": "european_union",
            "jurisdiction_name": "European Union",
            "domain_id": "competition",
            "citation": "Regulation (EU) 2022/1925",
            "source_url": "https://eur-lex.europa.eu/eli/reg/2022/1925/oj",
            "aliases": ["Digital Markets Act"],
            "obscurity": "low",
        }
    ]
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(json.dumps(gold), encoding="utf-8")

    dossier = tmp_path / "run1"
    laws = dossier / "laws"
    laws.mkdir(parents=True)
    (laws / "dma.json").write_text(
        json.dumps(
            {
                "law_id": "dma",
                "title": "Digital Markets Act",
                "jurisdiction_id": "european_union",
                "domain_id": "competition",
                "citation": "Reg (EU) 2022/1925",
                "source_url": "https://eur-lex.europa.eu/eli/reg/2022/1925/oj",
            }
        ),
        encoding="utf-8",
    )

    code = score_main(
        [
            "--gold",
            str(gold_path),
            "--dossier",
            str(dossier),
            "--threshold",
            "0.95",
        ]
    )
    assert code == 0
