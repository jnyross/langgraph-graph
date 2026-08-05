"""Unit tests for plan_cells cartesian expansion."""

from __future__ import annotations

from langgraph_graph.meta_legal.nodes.plan_cells import (
    expand_cells,
    expand_explicit_cells,
    plan_cells,
)


def test_cartesian_two_by_three_deterministic_ids() -> None:
    jurisdictions = ["European Union", "United States"]
    domains = ["privacy", "competition", "accessibility"]
    cells = expand_cells(jurisdictions, domains, subject="Meta")

    assert len(cells) == 6
    expected_ids = [
        "european_union::privacy",
        "european_union::competition",
        "european_union::accessibility",
        "united_states::privacy",
        "united_states::competition",
        "united_states::accessibility",
    ]
    assert [c.cell_id for c in cells] == expected_ids
    assert [c.jurisdiction_id for c in cells] == [
        "european_union",
        "european_union",
        "european_union",
        "united_states",
        "united_states",
        "united_states",
    ]
    assert [c.domain_id for c in cells] == [
        "privacy",
        "competition",
        "accessibility",
        "privacy",
        "competition",
        "accessibility",
    ]
    assert all(c.status == "pending" for c in cells)
    assert all(c.subject == "Meta" for c in cells)


def test_domain_aliases_ip_and_youth_safety() -> None:
    cells = expand_cells(["EU"], ["IP", "Youth Safety"], subject="Meta")
    assert len(cells) == 2
    assert cells[0].domain == "ip"
    assert cells[0].domain_id == "ip"
    assert cells[0].cell_id == "european_union::ip"
    assert cells[1].domain == "youth_safety"
    assert cells[1].domain_id == "youth_safety"
    assert cells[1].cell_id == "european_union::youth_safety"


def test_duplicate_pairs_collapse() -> None:
    cells = expand_cells(
        ["EU", "European Union", "eu"],
        ["privacy", "Privacy", "data protection"],
        subject="Meta",
    )
    assert len(cells) == 1
    assert cells[0].cell_id == "european_union::privacy"
    assert cells[0].jurisdiction == "European Union"
    assert cells[0].domain_id == "privacy"


def test_eu_alias_does_not_invent_members() -> None:
    cells = expand_cells(["EU"], ["privacy"])
    assert len(cells) == 1
    cell = cells[0]
    assert cell.jurisdiction == "European Union"
    assert cell.jurisdiction_id == "european_union"
    assert cell.cell_id == "european_union::privacy"
    # No member-state expansion (DE, FR, …)
    assert "germany" not in cell.jurisdiction.lower()
    assert "france" not in cell.jurisdiction.lower()


def test_empty_inputs_yield_no_cells() -> None:
    assert expand_cells([], ["privacy"]) == []
    assert expand_cells(["EU"], []) == []
    assert expand_cells([], []) == []
    assert expand_cells(["", "  "], ["privacy"]) == []
    assert expand_cells(["EU"], ["", "  "]) == []


def test_plan_cells_skips_when_error_set() -> None:
    result = plan_cells(
        {
            "jurisdictions": ["European Union"],
            "domains": ["privacy"],
            "subject": "Meta",
            "error": "invalid input: boom",
            "cells": [],
            "drafts": [],
            "accepted": [],
            "rejected": [],
            "cell_errors": [],
            "dossier_path": "",
            "run_id": "r1",
        }
    )
    assert result == {"cells": []}


def test_plan_cells_expands_from_state() -> None:
    result = plan_cells(
        {
            "jurisdictions": ["United Kingdom", "California"],
            "domains": ["ip", "competition", "youth_safety"],
            "subject": "Meta Platforms",
            "error": None,
            "cells": [],
            "drafts": [],
            "accepted": [],
            "rejected": [],
            "cell_errors": [],
            "dossier_path": "",
            "run_id": "r2",
        }
    )
    cells = result["cells"]
    assert len(cells) == 6
    assert [c.cell_id for c in cells] == [
        "united_kingdom::ip",
        "united_kingdom::competition",
        "united_kingdom::youth_safety",
        "california::ip",
        "california::competition",
        "california::youth_safety",
    ]
    assert all(c.subject == "Meta Platforms" for c in cells)


def test_expand_explicit_cells_only_given_pairs() -> None:
    cells = expand_explicit_cells(
        [
            {"jurisdiction": "European Union", "domain": "privacy"},
            {"jurisdiction": "California", "domain": "competition"},
            {"jurisdiction": "European Union", "domain": "privacy"},  # dup
        ],
        subject="Meta",
    )
    assert len(cells) == 2
    assert [c.cell_id for c in cells] == [
        "european_union::privacy",
        "california::competition",
    ]
    assert cells[0].jurisdiction == "European Union"
    assert cells[1].domain_id == "competition"


def test_expand_explicit_cells_accepts_name_and_id_keys() -> None:
    cells = expand_explicit_cells(
        [
            {
                "jurisdiction_name": "United Kingdom",
                "domain_id": "ip",
            },
            {
                "jurisdiction_id": "south_korea",
                "domain": "Youth Safety",
            },
        ]
    )
    assert [c.cell_id for c in cells] == [
        "united_kingdom::ip",
        "south_korea::youth_safety",
    ]
    assert cells[1].jurisdiction == "South Korea"


def test_plan_cells_prefers_explicit_over_cartesian() -> None:
    result = plan_cells(
        {
            "jurisdictions": ["European Union", "United States"],
            "domains": ["privacy", "competition", "ip"],
            "explicit_cells": [
                {"jurisdiction": "European Union", "domain": "privacy"},
                {"jurisdiction": "United States", "domain": "ip"},
            ],
            "subject": "Meta",
            "error": None,
            "cells": [],
            "drafts": [],
            "accepted": [],
            "rejected": [],
            "cell_errors": [],
            "dossier_path": "",
            "run_id": "r3",
        }
    )
    cells = result["cells"]
    assert len(cells) == 2
    assert [c.cell_id for c in cells] == [
        "european_union::privacy",
        "united_states::ip",
    ]


def test_plan_cells_empty_explicit_falls_back_to_cartesian() -> None:
    result = plan_cells(
        {
            "jurisdictions": ["India"],
            "domains": ["accessibility"],
            "explicit_cells": [],
            "subject": "Meta",
            "error": None,
            "cells": [],
            "drafts": [],
            "accepted": [],
            "rejected": [],
            "cell_errors": [],
            "dossier_path": "",
            "run_id": "r4",
        }
    )
    cells = result["cells"]
    assert len(cells) == 1
    assert cells[0].cell_id == "india::accessibility"
