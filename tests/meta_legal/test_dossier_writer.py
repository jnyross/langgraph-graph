"""U5: dossier writer persists accepted/rejected findings under a run tree."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from langgraph_graph.meta_legal.models import (
    LawRecord,
    LawRecordDraft,
    RejectedRecord,
    ResearchCell,
)
from langgraph_graph.meta_legal.nodes.write_dossier import (
    safe_fs_id,
    write_dossier,
    write_dossier_to_root,
)


def _law(
    *,
    law_id: str,
    title: str,
    jurisdiction_id: str = "eu",
    domain_id: str = "privacy",
    cell_id: str = "eu::privacy",
) -> LawRecord:
    return LawRecord(
        law_id=law_id,
        title=title,
        jurisdiction_id=jurisdiction_id,
        domain_id=domain_id,
        cell_id=cell_id,
        citation="Art. 1",
        source_url="https://example.test/law",
        source_type="primary",
        excerpt="Sample excerpt.",
        meta_nexus_rationale="Platform obligation for Meta.",
    )


def test_accepted_writes_law_files_and_manifest(tmp_path: Path) -> None:
    record = _law(law_id="gdpr-art-5", title="GDPR Article 5")
    cell = ResearchCell(
        cell_id="eu::privacy",
        jurisdiction="European Union",
        jurisdiction_id="eu",
        domain="privacy",
        domain_id="privacy",
    )

    dossier = write_dossier_to_root(
        tmp_path,
        run_id="run-happy",
        jurisdictions=["European Union"],
        domains=["privacy"],
        subject="Meta",
        accepted=[record],
        rejected=[],
        cells=[cell],
        model="deepseek/deepseek-v4-flash",
    )

    assert dossier == tmp_path / "run-happy"
    assert (dossier / "manifest.json").is_file()
    assert (dossier / "index.json").is_file()

    safe_law = safe_fs_id("gdpr-art-5")
    assert (dossier / "laws" / f"{safe_law}.json").is_file()
    assert (dossier / "laws" / f"{safe_law}.md").is_file()

    law_payload = json.loads((dossier / "laws" / f"{safe_law}.json").read_text(encoding="utf-8"))
    assert law_payload["law_id"] == "gdpr-art-5"
    assert law_payload["title"] == "GDPR Article 5"
    assert law_payload["validated"] is True

    md = (dossier / "laws" / f"{safe_law}.md").read_text(encoding="utf-8")
    assert "GDPR Article 5" in md
    assert "gdpr-art-5" in md

    safe_cell = safe_fs_id("eu::privacy")
    assert "::" not in safe_cell
    findings_path = dossier / "cells" / safe_cell / "findings.json"
    assert findings_path.is_file()
    findings = json.loads(findings_path.read_text(encoding="utf-8"))
    assert findings["count"] == 1
    assert findings["law_ids"] == ["gdpr-art-5"]

    manifest = json.loads((dossier / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == "run-happy"
    assert manifest["accepted_count"] == 1
    assert manifest["rejected_count"] == 0
    assert manifest["subject"] == "Meta"
    assert manifest["jurisdictions"] == ["European Union"]
    assert manifest["domains"] == ["privacy"]
    assert "eu::privacy" in manifest["cell_ids"]

    index = json.loads((dossier / "index.json").read_text(encoding="utf-8"))
    assert index["accepted_count"] == 1
    assert index["law_ids"] == ["gdpr-art-5"]
    assert index["model"] == "deepseek/deepseek-v4-flash"


def test_rejected_only_under_rejected(tmp_path: Path) -> None:
    draft = LawRecordDraft(
        law_id="weak-cite",
        title="Weak Citation Draft",
        jurisdiction_id="us",
        domain_id="privacy",
        cell_id="us::privacy",
        citation="",
        source_url="https://blog.example/post",
    )
    rejected = RejectedRecord(
        record=draft,
        reason="missing primary citation",
        cell_id="us::privacy",
    )

    dossier = write_dossier_to_root(
        tmp_path,
        run_id="run-reject",
        jurisdictions=["United States"],
        domains=["privacy"],
        accepted=[],
        rejected=[rejected],
    )

    laws_dir = dossier / "laws"
    assert laws_dir.is_dir()
    assert list(laws_dir.glob("*.json")) == []
    assert list(laws_dir.glob("*.md")) == []

    # No cell findings for empty accepted
    cells_dir = dossier / "cells"
    assert cells_dir.is_dir()
    assert list(cells_dir.iterdir()) == []

    safe_cell = safe_fs_id("us::privacy")
    rejected_path = dossier / "rejected" / f"{safe_cell}.json"
    assert rejected_path.is_file()
    payload = json.loads(rejected_path.read_text(encoding="utf-8"))
    assert payload["count"] == 1
    assert payload["rejected"][0]["reason"] == "missing primary citation"
    assert payload["rejected"][0]["record"]["law_id"] == "weak-cite"

    # Rejected must not appear under laws/
    for path in dossier.rglob("*"):
        if path.is_file() and path.parent.name == "laws":
            pytest.fail(f"unexpected law file: {path}")

    manifest = json.loads((dossier / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["accepted_count"] == 0
    assert manifest["rejected_count"] == 1


def test_zero_accepted_still_writes_manifest(tmp_path: Path) -> None:
    dossier = write_dossier_to_root(
        tmp_path,
        run_id="run-empty",
        jurisdictions=["EU"],
        domains=["ip"],
        subject="Meta",
        accepted=[],
        rejected=[],
        cells=[],
    )

    assert (dossier / "manifest.json").is_file()
    assert (dossier / "index.json").is_file()
    manifest = json.loads((dossier / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == "run-empty"
    assert manifest["accepted_count"] == 0
    assert manifest["rejected_count"] == 0
    assert manifest["error_count"] == 0
    assert manifest["dossier_path"] == str(dossier)

    index = json.loads((dossier / "index.json").read_text(encoding="utf-8"))
    assert index["law_ids"] == []
    assert index["accepted_count"] == 0


def test_slash_and_space_ids_are_filesystem_safe(tmp_path: Path) -> None:
    record = _law(
        law_id="EU/Reg 2022/2065 DSA",
        title="Digital Services Act",
        jurisdiction_id="European Union",
        domain_id="youth safety",
        cell_id="European Union::youth safety",
    )

    dossier = write_dossier_to_root(
        tmp_path,
        run_id="run-safe",
        jurisdictions=["European Union"],
        domains=["youth_safety"],
        accepted=[record],
        rejected=[],
    )

    safe_law = safe_fs_id("EU/Reg 2022/2065 DSA")
    safe_cell = safe_fs_id("European Union::youth safety")
    assert "/" not in safe_law
    assert " " not in safe_law
    assert "::" not in safe_cell
    assert "/" not in safe_cell
    assert " " not in safe_cell

    assert (dossier / "laws" / f"{safe_law}.json").is_file()
    assert (dossier / "laws" / f"{safe_law}.md").is_file()
    assert (dossier / "cells" / safe_cell / "findings.json").is_file()

    # Entire tree paths must be creatable (no residual path separators in names)
    for path in dossier.rglob("*"):
        name = path.name
        if path.is_file():
            assert "/" not in name
            assert "\\" not in name


def test_rejected_without_cell_id_goes_to_all(tmp_path: Path) -> None:
    draft = LawRecordDraft(
        law_id="orphan",
        title="Orphan Draft",
        jurisdiction_id="br",
        domain_id="competition",
    )
    rejected = RejectedRecord(record=draft, reason="no cell", cell_id="")

    dossier = write_dossier_to_root(
        tmp_path,
        run_id="run-all",
        jurisdictions=["Brazil"],
        domains=["competition"],
        accepted=[],
        rejected=[rejected],
    )

    assert (dossier / "rejected" / "all.json").is_file()
    payload = json.loads((dossier / "rejected" / "all.json").read_text(encoding="utf-8"))
    assert payload["count"] == 1
    assert payload["cell_id"] is None


def test_write_dossier_node_uses_env_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOSSIER_ROOT", str(tmp_path))
    record = _law(law_id="node-1", title="Node Law")
    result = write_dossier(
        {
            "run_id": "from-state",
            "jurisdictions": ["EU"],
            "domains": ["privacy"],
            "subject": "Meta",
            "cells": [],
            "accepted": [record],
            "rejected": [],
            "cell_errors": [],
            "dossier_path": "",
        }
    )

    assert result["run_id"] == "from-state"
    assert result["dossier_path"] == str(tmp_path / "from-state")
    assert (tmp_path / "from-state" / "manifest.json").is_file()


def test_write_dossier_generates_run_id_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOSSIER_ROOT", str(tmp_path))
    result = write_dossier(
        {
            "run_id": "",
            "jurisdictions": ["EU"],
            "domains": ["privacy"],
            "subject": "Meta",
            "cells": [],
            "accepted": [],
            "rejected": [],
            "cell_errors": [],
            "dossier_path": "",
        }
    )
    assert result["run_id"]
    assert result["dossier_path"].endswith(result["run_id"])
    assert (Path(result["dossier_path"]) / "manifest.json").is_file()


def test_unwritable_root_surfaces_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(0o500)
    nested = blocked / "nope"
    # On some systems mkdir under 0500 still fails for non-owner; force file-as-root case.
    file_root = tmp_path / "not-a-dir"
    file_root.write_text("x", encoding="utf-8")
    monkeypatch.setenv("DOSSIER_ROOT", str(file_root))

    result = write_dossier(
        {
            "run_id": "fail-run",
            "jurisdictions": ["EU"],
            "domains": ["privacy"],
            "subject": "Meta",
            "cells": [],
            "accepted": [],
            "rejected": [],
            "cell_errors": [],
            "dossier_path": "",
        }
    )
    assert "error" in result
    assert "Failed to write dossier" in result["error"]
    assert result["run_id"] == "fail-run"

    # Pure helper should raise for the same condition
    with pytest.raises(OSError):
        write_dossier_to_root(
            file_root,
            run_id="fail-run",
            jurisdictions=["EU"],
            domains=["privacy"],
            accepted=[],
            rejected=[],
        )

    blocked.chmod(0o700)


def test_safe_fs_id_replaces_double_colon() -> None:
    assert safe_fs_id("eu::privacy") == "eu__privacy"
    assert "::" not in safe_fs_id("a::b::c")
    assert " " not in safe_fs_id("Foo Bar")
    assert "/" not in safe_fs_id("a/b")
