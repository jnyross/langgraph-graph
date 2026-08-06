from __future__ import annotations

import json

import pytest

from langgraph_graph.jurisdiction_catalog import build_graph
from langgraph_graph.jurisdiction_catalog.models import Candidate, Evidence, Verification
from langgraph_graph.jurisdiction_catalog.nodes.diff_catalog import compute_diff
from langgraph_graph.jurisdiction_catalog.nodes.plan_candidates import plan_candidates
from langgraph_graph.jurisdiction_catalog.nodes.validate_candidate import validate_candidate
from langgraph_graph.meta_legal.jurisdictions import load_catalog
from langgraph_graph.meta_legal.models import slugify


def test_planning_is_deterministic_and_parent_aware() -> None:
    first = plan_candidates({"levels": ["country", "state_province", "us_state"]})
    second = plan_candidates({"levels": ["country", "state_province", "us_state"]})
    assert [x.id for x in first["candidates"]] == [x.id for x in second["candidates"]]
    ids = {x.id for x in first["candidates"]}
    assert "georgia" in ids and "georgia_us" in ids
    assert f"{slugify('Québec')}_canada" in ids


def test_validation_requires_evidence_and_confidence() -> None:
    candidate = Candidate(id="x", name="X", level="country")
    result = validate_candidate(
        {
            "candidate": candidate,
            "verification": Verification(candidate_id="x", verdict="include"),
        }
    )
    assert not result.get("validated")
    assert result["rejected"][0]["reason"] == "insufficient_evidence,low_confidence"


def test_diff_reports_added_changed_and_removed() -> None:
    old = [
        {"id": "a", "name": "A", "level": "country", "parent_id": None, "domains_priority": ["all"]}
    ]
    new = [
        {
            "id": "a",
            "name": "A2",
            "level": "country",
            "parent_id": None,
            "domains_priority": ["all"],
        },
        {
            "id": "b",
            "name": "B",
            "level": "country",
            "parent_id": None,
            "domains_priority": ["all"],
        },
    ]
    diff = compute_diff(new, old)
    assert [x["id"] for x in diff.added] == ["b"]
    assert [x["id"] for x in diff.removed] == []
    assert [x["id"] for x in diff.changed] == ["a"]


def test_offline_graph_writes_round_trippable_catalog(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = build_graph(False).invoke(
        {"levels": ["supranational"], "write_target": str(tmp_path), "run_id": "offline"}
    )
    output = tmp_path / "offline"
    assert output.joinpath("catalog.json").is_file()
    assert output.joinpath("diff.json").is_file()
    assert output.joinpath("report.md").is_file()
    assert output.joinpath("run_metrics.json").is_file()
    assert result["output_path"] == str(output)
    assert load_catalog(output / "catalog.json")["version"] == "2"


@pytest.mark.parametrize(
    ("assessment", "expected"),
    [
        (
            {
                "services_available": True,
                "authority_exists": True,
                "verdict": "include",
                "confidence": 0.9,
                "rationale": "both",
            },
            "include",
        ),
        (
            {
                "services_available": True,
                "authority_exists": False,
                "verdict": "exclude",
                "confidence": 0.9,
                "rationale": "no authority",
            },
            "exclude",
        ),
        (
            {
                "services_available": True,
                "authority_exists": True,
                "verdict": "uncertain",
                "confidence": 0.2,
                "rationale": "thin",
            },
            "uncertain",
        ),
    ],
)
def test_verification_uses_both_conditions(
    monkeypatch: pytest.MonkeyPatch, assessment: dict, expected: str
) -> None:
    import importlib

    module = importlib.import_module(
        "langgraph_graph.jurisdiction_catalog.nodes.verify_jurisdiction"
    )

    class Structured:
        def invoke(self, messages):
            return assessment

    class LLM:
        def with_structured_output(self, schema):
            return Structured()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(
        module,
        "web_search",
        lambda query, max_results: [{"url": "https://example.test", "title": "e", "snippet": "e"}],
    )
    monkeypatch.setattr(module, "fetch_url", lambda url, max_chars: "official evidence")
    monkeypatch.setattr(module, "get_llm", lambda: LLM())
    candidate = Candidate(id="x", name="X", level="country")
    result = module.verify_jurisdiction({"candidate": candidate})
    assert result["verifications"][0].verdict == expected


def test_validation_binds_each_candidate_in_multi_candidate_fan_in() -> None:
    first = Candidate(id="first", name="First", level="country")
    second = Candidate(id="second", name="Second", level="country")
    result = validate_candidate(
        {
            "candidates": [first, second],
            "verifications": [
                Verification(
                    candidate_id="first",
                    candidate=first,
                    verdict="include",
                    confidence=0.9,
                    evidence=[Evidence(url="https://example.test/1")],
                ),
                Verification(
                    candidate_id="second",
                    candidate=second,
                    verdict="exclude",
                ),
            ],
        }
    )
    assert [item.id for item in result["validated"]] == ["first"]
    assert result["rejected"][0]["candidate"]["id"] == "second"


def test_promotion_sanity_gate(tmp_path, monkeypatch) -> None:
    import importlib

    module = importlib.import_module("langgraph_graph.jurisdiction_catalog.nodes.write_catalog")

    live = tmp_path / "live.json"
    current = {
        "version": "1",
        "subject": "Meta",
        "jurisdictions": [{"id": str(i), "name": str(i), "level": "country"} for i in range(10)],
    }
    live.write_text(json.dumps(current), encoding="utf-8")
    monkeypatch.setattr(module, "default_catalog_path", lambda: live)
    monkeypatch.setattr(module, "load_catalog", lambda path=None: current)
    module.write_catalog(
        {
            "run_id": "promotion",
            "write_target": str(tmp_path),
            "promote": True,
            "validated": [{"id": "one", "name": "One", "level": "country"}],
            "rejected": [],
            "candidates": [],
            "diff": {},
        }
    )
    assert json.loads(live.read_text(encoding="utf-8")) == current
    assert "sanity floor" in (tmp_path / "promotion" / "report.md").read_text()


def test_graph_topology_and_compile() -> None:
    from langgraph_graph.jurisdiction_catalog import graph

    names = set(graph.get_graph().nodes)
    assert {
        "ingest_input",
        "plan_candidates",
        "discover_candidates",
        "verify_jurisdiction",
        "validate_candidate",
        "aggregate",
        "diff_catalog",
        "write_catalog",
    } <= names
    assert build_graph(False).get_graph() is not None


def test_ingest_error_and_empty_candidates_write_artifacts(tmp_path) -> None:
    result = build_graph(False).invoke(
        {
            "levels": "not-a-list",
            "write_target": str(tmp_path),
            "run_id": "invalid",
        }
    )
    output = tmp_path / "invalid"
    assert result.get("error")
    assert output.joinpath("diff.json").is_file()
    assert output.joinpath("report.md").is_file()


def test_shipped_catalog_loads_with_strict_levels() -> None:
    catalog = load_catalog()
    assert catalog["jurisdictions"]
    assert all(item["level"] for item in catalog["jurisdictions"])
