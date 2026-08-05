"""Tests for the Meta operating jurisdiction catalog and loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from langgraph_graph.meta_legal.jurisdictions import (
    default_catalog_path,
    list_jurisdiction_names,
    load_catalog,
)


def test_default_catalog_path_points_at_repo_json() -> None:
    path = default_catalog_path()
    assert isinstance(path, Path)
    assert path.name == "meta_operating_catalog.json"
    assert path.is_file()
    assert path.parent.name == "jurisdictions"


def test_catalog_loads() -> None:
    catalog = load_catalog()
    assert catalog["version"] == "1"
    assert catalog["subject"] == "Meta"
    assert isinstance(catalog["jurisdictions"], list)
    assert len(catalog["jurisdictions"]) >= 80


def test_at_least_80_country_level_entries() -> None:
    catalog = load_catalog()
    countries = [j for j in catalog["jurisdictions"] if j.get("level") == "country"]
    assert len(countries) >= 80


def test_eu_united_states_california_present() -> None:
    catalog = load_catalog()
    by_id = {j["id"]: j for j in catalog["jurisdictions"]}
    assert "european_union" in by_id
    assert by_id["european_union"]["name"] == "European Union"
    assert by_id["european_union"]["level"] == "supranational"

    assert "united_states" in by_id
    assert by_id["united_states"]["name"] == "United States"
    assert by_id["united_states"]["level"] == "country"

    assert "california" in by_id
    assert by_id["california"]["name"] == "California"
    assert by_id["california"]["level"] == "us_state"
    assert by_id["california"]["parent_id"] == "united_states"


def test_unique_ids() -> None:
    catalog = load_catalog()
    ids = [j["id"] for j in catalog["jurisdictions"]]
    assert len(ids) == len(set(ids))
    assert all(isinstance(i, str) and i.strip() for i in ids)


def test_list_jurisdiction_names_all_and_filtered() -> None:
    catalog = load_catalog()
    all_names = list_jurisdiction_names(catalog)
    assert "European Union" in all_names
    assert "United States" in all_names
    assert "California" in all_names
    assert len(all_names) == len(catalog["jurisdictions"])

    countries = list_jurisdiction_names(catalog, levels=["country"])
    assert "United States" in countries
    assert "European Union" not in countries
    assert "California" not in countries
    assert len(countries) >= 80

    multi = list_jurisdiction_names(catalog, levels=["supranational", "us_state"])
    assert "European Union" in multi
    assert "California" in multi
    assert "United States" not in multi


def test_load_catalog_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.json"
    with pytest.raises(FileNotFoundError):
        load_catalog(missing)


def test_load_catalog_duplicate_ids_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"version":"1","subject":"Meta","jurisdictions":['
        '{"id":"x","name":"X","level":"country"},'
        '{"id":"x","name":"X2","level":"country"}'
        "]}",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_catalog(bad)
