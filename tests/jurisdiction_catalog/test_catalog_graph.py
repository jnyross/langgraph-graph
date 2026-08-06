from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from langgraph_graph.jurisdiction_catalog import build_graph
from langgraph_graph.jurisdiction_catalog.models import (
    Assessment,
    Candidate,
    Evidence,
    Verification,
)
from langgraph_graph.jurisdiction_catalog.nodes.diff_catalog import compute_diff
from langgraph_graph.jurisdiction_catalog.nodes.plan_candidates import plan_candidates
from langgraph_graph.jurisdiction_catalog.nodes.validate_candidate import validate_candidate
from langgraph_graph.jurisdiction_catalog.nodes.widen_seed import widen_seed
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
            "uncertain",
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
            return Assessment(**assessment)

    class LLM:
        def with_structured_output(self, schema):
            return Structured()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(
        module,
        "web_search",
        lambda query, max_results: [
            {
                "url": "https://example.test/x",
                "title": "X platform authority",
                "snippet": "X evidence",
            }
        ],
    )
    monkeypatch.setattr(module, "fetch_url", lambda url, max_chars: "X official evidence")
    monkeypatch.setattr(module, "get_llm", lambda: LLM())
    candidate = Candidate(id="x", name="X", level="country")
    result = module.verify_jurisdiction({"candidate": candidate})
    assert result["verifications"][0].verdict == expected


def test_verification_filters_off_topic_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    module = importlib.import_module(
        "langgraph_graph.jurisdiction_catalog.nodes.verify_jurisdiction"
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(
        module,
        "web_search",
        lambda query, max_results: [
            {
                "url": "https://example.test/kazakhstan",
                "title": "FTC v. Meta",
                "snippet": "Kazakhstan regulator",
            }
        ],
    )
    monkeypatch.setattr(module, "fetch_url", lambda url, max_chars: "Kazakhstan authority")
    candidate = Candidate(id="japan", name="Japan", level="country")
    result = module.verify_jurisdiction({"candidate": candidate})
    verification = result["verifications"][0]
    assert verification.verdict == "uncertain"
    assert verification.evidence == []
    assert "no relevant evidence" in verification.errors[0]


def test_verification_keeps_only_relevant_mixed_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    module = importlib.import_module(
        "langgraph_graph.jurisdiction_catalog.nodes.verify_jurisdiction"
    )

    class Structured:
        def invoke(self, messages):
            return Assessment(
                services_available=True,
                authority_exists=True,
                verdict="include",
                confidence=0.9,
                rationale="relevant",
            )

    class LLM:
        def with_structured_output(self, schema):
            return Structured()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(
        module,
        "web_search",
        lambda query, max_results: [
            {"url": "https://example.test/japan", "title": "Japan law", "snippet": ""},
            {
                "url": "https://example.test/kazakhstan",
                "title": "Kazakhstan law",
                "snippet": "",
            },
        ],
    )
    monkeypatch.setattr(module, "fetch_url", lambda url, max_chars: f"Source text for {url}")
    monkeypatch.setattr(module, "get_llm", lambda: LLM())
    candidate = Candidate(id="japan", name="Japan", level="country")
    result = module.verify_jurisdiction({"candidate": candidate})
    verification = result["verifications"][0]
    assert verification.verdict == "include"
    assert len(verification.evidence) == 1
    assert "japan" in verification.evidence[0].url


def test_verification_requires_strong_evidence_before_exclusion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    module = importlib.import_module(
        "langgraph_graph.jurisdiction_catalog.nodes.verify_jurisdiction"
    )

    class Structured:
        def invoke(self, messages):
            return Assessment(
                services_available=False,
                authority_exists=True,
                verdict="exclude",
                confidence=0.9,
                rationale="direct blocking evidence",
            )

    class LLM:
        def with_structured_output(self, schema):
            return Structured()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(
        module,
        "web_search",
        lambda query, max_results: [
            {"url": "https://example.test/iran-one", "title": "Iran blocking", "snippet": ""},
            {"url": "https://example.test/iran-two", "title": "Iran restrictions", "snippet": ""},
        ],
    )
    monkeypatch.setattr(module, "fetch_url", lambda url, max_chars: "Iran direct blocking evidence")
    monkeypatch.setattr(module, "get_llm", lambda: LLM())
    candidate = Candidate(id="iran", name="Iran", level="country")
    result = module.verify_jurisdiction({"candidate": candidate})
    assert result["verifications"][0].verdict == "exclude"


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


def test_promotion_catalog_read_failure_is_recorded_and_temp_removed(tmp_path, monkeypatch) -> None:
    import importlib

    module = importlib.import_module("langgraph_graph.jurisdiction_catalog.nodes.write_catalog")
    live = tmp_path / "live.json"
    live.write_text("not-json", encoding="utf-8")
    calls = 0

    def failing_loader(path=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "version": "1",
                "subject": "Meta",
                "jurisdictions": [{"id": "x", "name": "X", "level": "country"}],
            }
        raise ValueError("invalid promoted catalog")

    monkeypatch.setattr(module, "default_catalog_path", lambda: live)
    monkeypatch.setattr(module, "load_catalog", failing_loader)
    output = tmp_path / "failed"
    module.write_catalog(
        {
            "run_id": "failed",
            "write_target": str(tmp_path),
            "promote": True,
            "validated": [{"id": "x", "name": "X", "level": "country"}],
            "rejected": [],
            "candidates": [],
            "diff": {},
        }
    )
    report = (output / "report.md").read_text(encoding="utf-8")
    assert "promotion validation/write failed" in report
    assert not (output / ".promotion_catalog.json").exists()
    assert live.read_text(encoding="utf-8") == "not-json"


def test_graph_topology_and_compile() -> None:
    from langgraph_graph.jurisdiction_catalog import graph

    names = set(graph.get_graph().nodes)
    assert {
        "ingest_input",
        "plan_candidates",
        "discover_candidates",
        "verify_jurisdiction",
        "validate_candidate",
        "widen_seed",
        "aggregate",
        "diff_catalog",
        "write_catalog",
    } <= names
    assert build_graph(False).get_graph() is not None


def test_langgraph_json_file_path_entries_load() -> None:
    config = json.loads(Path("langgraph.json").read_text(encoding="utf-8"))
    for graph_id, entry in config["graphs"].items():
        path_text, attribute = entry.rsplit(":", 1)
        path = Path(path_text)
        spec = importlib.util.spec_from_file_location(f"file_path_graph_{graph_id}", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert getattr(module, attribute) is not None


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


def test_widen_seed_appends_discovered_candidate_idempotently(tmp_path) -> None:
    seed = tmp_path / "seed.json"
    seed.write_text(
        json.dumps(
            {
                "version": "2",
                "source": "test",
                "candidates": [{"id": "existing", "name": "Existing", "level": "country"}],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    candidate = Candidate(
        id="new_body",
        name="New Body",
        level="supranational",
        source="discovered",
    )
    state = {
        "seed_path": str(seed),
        "auto_widen_seed": True,
        "discovery_ran": True,
        "discovered_candidates": [candidate],
        "candidates": [candidate],
        "rejected": [{"candidate": candidate.model_dump(), "reason": "uncertain"}],
    }
    widen_seed(state)
    first = seed.read_bytes()
    document = json.loads(first)
    assert document["discovered_candidates"][0]["source"] == "discovered"
    widen_seed(state)
    assert seed.read_bytes() == first


@pytest.mark.parametrize(
    ("state_key", "state_value"),
    [("auto_widen_seed", False), ("discovery_ran", False)],
)
def test_widen_seed_disabled_or_offline_leaves_seed_untouched(
    tmp_path, state_key: str, state_value: bool
) -> None:
    seed = tmp_path / "seed.json"
    original = '{"version":"2","candidates":[]}\n'
    seed.write_text(original, encoding="utf-8")
    candidate = Candidate(
        id="new_body",
        name="New Body",
        level="supranational",
        source="discovered",
    )
    state = {
        "seed_path": str(seed),
        "auto_widen_seed": True,
        "discovery_ran": True,
        "discovered_candidates": [candidate],
        "candidates": [candidate],
        state_key: state_value,
    }
    widen_seed(state)
    assert seed.read_text(encoding="utf-8") == original


def test_widen_seed_skips_structurally_invalid_candidate(tmp_path) -> None:
    seed = tmp_path / "seed.json"
    original = '{"version":"2","candidates":[]}\n'
    seed.write_text(original, encoding="utf-8")
    candidate = Candidate(
        id="bad",
        name="Bad",
        level="unsupported",
        source="discovered",
    )
    widen_seed(
        {
            "seed_path": str(seed),
            "auto_widen_seed": True,
            "discovery_ran": True,
            "discovered_candidates": [candidate],
            "candidates": [candidate],
            "rejected": [
                {
                    "candidate": candidate.model_dump(),
                    "reason": "unsupported_level",
                }
            ],
        }
    )
    assert seed.read_text(encoding="utf-8") == original
