from __future__ import annotations

from langgraph_graph.jurisdiction_catalog import build_graph
from langgraph_graph.jurisdiction_catalog.models import Candidate, Verification
from langgraph_graph.jurisdiction_catalog.nodes.diff_catalog import compute_diff
from langgraph_graph.jurisdiction_catalog.nodes.plan_candidates import plan_candidates
from langgraph_graph.jurisdiction_catalog.nodes.validate_candidate import validate_candidate
from langgraph_graph.meta_legal.jurisdictions import load_catalog


def test_planning_is_deterministic_and_parent_aware() -> None:
    first = plan_candidates({"levels": ["country", "state_province", "us_state"]})
    second = plan_candidates({"levels": ["country", "state_province", "us_state"]})
    assert [x.id for x in first["candidates"]] == [x.id for x in second["candidates"]]
    ids = {x.id for x in first["candidates"]}
    assert "georgia" in ids and "georgia_us" in ids
    assert "quebec_canada" in ids


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
            "id": "a", "name": "A2", "level": "country", "parent_id": None,
            "domains_priority": ["all"],
        },
        {
            "id": "b", "name": "B", "level": "country", "parent_id": None,
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
