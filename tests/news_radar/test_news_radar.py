"""Unit tests for the news_radar graph."""

from __future__ import annotations

import json
from uuid import uuid4

from langgraph_graph.news_radar.graph import fanout_cells
from langgraph_graph.news_radar.models import (
    RadarInput,
    RejectedSignal,
    SignalCluster,
    SignalDraft,
    SignalRecord,
    WatchCell,
)
from langgraph_graph.news_radar.nodes.cluster_signals import cluster_signals
from langgraph_graph.news_radar.nodes.ingest_input import ingest_input
from langgraph_graph.news_radar.nodes.link_known_laws import link_known_laws
from langgraph_graph.news_radar.nodes.plan_cells import plan_cells
from langgraph_graph.news_radar.nodes.validate_signal import validate_signal
from langgraph_graph.news_radar.nodes.write_radar import write_radar
from langgraph_graph.news_radar.sources import news_host_score, select_news_urls


def test_radar_input_accepts_lookback_and_rumors() -> None:
    inp = RadarInput(
        jurisdictions=["European Union"],
        domains=["privacy"],
        lookback_days=21,
        include_rumors=True,
    )
    assert inp.lookback_days == 21
    assert inp.include_rumors is True
    assert inp.levels == ["country", "supranational"]


def test_ingest_input_generates_run_id_and_levels() -> None:
    state = ingest_input(
        {
            "jurisdictions": ["EU"],
            "domains": ["privacy"],
            "subject": "Meta",
            "lookback_days": 14,
        }
    )
    assert state["jurisdictions"] == ["European Union"]
    assert state["domains"] == ["privacy"]
    assert state["subject"] == "Meta"
    assert state["lookback_days"] == 14
    assert state["run_id"]


def test_plan_cells_expands_and_caps() -> None:
    state = plan_cells(
        {
            "jurisdictions": ["EU", "United States"],
            "domains": ["privacy", "competition"],
            "subject": "Meta",
            "catalog_jurisdictions": [
                {"id": "european_union", "name": "European Union", "level": "supranational"},
                {"id": "united_states", "name": "United States", "level": "country"},
            ],
            "levels": ["country"],
            "max_cells": 1,
        }
    )
    cells = state["cells"]
    assert len(cells) == 1
    assert cells[0].level == "country"
    assert cells[0].jurisdiction_id == "united_states"


def test_fanout_cells_returns_send_or_write_radar() -> None:
    cell_a = WatchCell(
        cell_id="eu::privacy",
        jurisdiction="European Union",
        jurisdiction_id="european_union",
        domain="privacy",
        domain_id="privacy",
    )
    sends = fanout_cells({"cells": [cell_a]})
    assert len(sends) == 1
    assert sends[0].node == "scan_cell"

    empty = fanout_cells({"cells": []})
    assert empty == "write_radar"


def test_select_news_urls_demotes_official_host() -> None:
    hits = [
        {"url": "https://reuters.com/article/data-privacy-bill"},
        {"url": "https://gdpr.eu/news"},
        {"url": "https://reuters.com/another-article"},
    ]
    selected = select_news_urls(hits, limit=3, max_per_host=2)
    urls = [s["url"] for s in selected]
    assert urls[0].startswith("https://reuters.com")
    assert "reuters" in urls[0]
    assert any("gdpr.eu" in u for u in urls)


def test_select_news_urls_respects_max_per_host() -> None:
    hits = [{"url": f"https://example.com/article{i}"} for i in range(10)]
    selected = select_news_urls(hits, limit=4, max_per_host=2)
    assert len(selected) == 2  # host capped at 2


def test_official_host_not_excluded_by_default() -> None:
    hits = [{"url": "https://ico.org.uk/news-and-events/news-release"}]
    score, label = news_host_score(hits[0]["url"], "Press release: something")
    assert label in {"official", "official_press"}
    selected = select_news_urls(hits, limit=1)
    assert len(selected) == 1


def test_validate_signal_accepts_and_rejects() -> None:
    cell = WatchCell(
        cell_id="eu::privacy",
        jurisdiction="European Union",
        jurisdiction_id="european_union",
        domain="privacy",
        domain_id="privacy",
    )
    good = SignalDraft(
        title="EU Data Act amendment scheduled",
        jurisdiction_id="european_union",
        domain_id="privacy",
        source_url="https://example.com/act",
        confidence=0.8,
        cell_id="eu::privacy",
    )
    bad_url = SignalDraft(
        title="No URL signal",
        jurisdiction_id="european_union",
        domain_id="privacy",
        confidence=0.6,
        cell_id="eu::privacy",
    )
    rumor = SignalDraft(
        title=" rumored leaked something longer title",
        jurisdiction_id="european_union",
        domain_id="privacy",
        source_url="https://example.com/rumor",
        confidence=0.6,
        is_rumor=True,
        cell_id="eu::privacy",
    )
    state = validate_signal(
        {
            "cell": cell.model_dump(),
            "drafts": [good, bad_url, rumor],
            "include_rumors": False,
        }
    )
    assert len(state["accepted"]) == 1
    assert state["accepted"][0].title == good.title
    assert len(state["rejected"]) == 2
    assert isinstance(state["rejected"][0], RejectedSignal)


def test_cluster_signals_groups_similar_titles() -> None:
    sigs = [
        SignalRecord(
            title="EU Data Act amendment under debate",
            jurisdiction_id="european_union",
            domain_id="privacy",
            source_name="Reuters",
            source_url="https://reuters.com/a",
            cell_id="eu::privacy",
        ),
        SignalRecord(
            title="European Data Act amendment faces debate",
            jurisdiction_id="european_union",
            domain_id="privacy",
            source_name="Politico",
            source_url="https://politico.eu/b",
            cell_id="eu::privacy",
        ),
        SignalRecord(
            title="US FTC launches privacy probe",
            jurisdiction_id="united_states",
            domain_id="privacy",
            source_name="FT",
            source_url="https://ft.com/c",
            cell_id="us::privacy",
        ),
    ]
    state = cluster_signals({"accepted": sigs, "include_rumors": False})
    clusters = state["clusters"]
    assert len(clusters) == 2
    c0 = clusters[0]
    assert isinstance(c0, SignalCluster)
    assert "data act amendment" in c0.title.lower()
    assert c0.distinct_publisher_count >= 2
    assert c0.status in {"corroborated", "confirmed"}


def test_link_known_laws_tags_duplicate_and_update() -> None:
    sigs = [
        SignalRecord(
            title="General Data Protection Regulation",
            jurisdiction_id="european_union",
            domain_id="privacy",
            source_url="https://example.com/gdpr",
            cell_id="eu::privacy",
        ),
        SignalRecord(
            title="EU AI Act final text agreed",
            jurisdiction_id="european_union",
            domain_id="ip",
            source_url="https://example.com/ai-act",
            cell_id="eu::ip",
        ),
    ]
    known = [
        {
            "law_id": "law-1",
            "title": "General Data Protection Regulation (GDPR)",
            "jurisdiction_id": "european_union",
            "domain_id": "privacy",
            "source_url": "https://example.com/gdpr",
        },
        {
            "law_id": "law-2",
            "title": "Digital Services Act",
            "jurisdiction_id": "european_union",
            "domain_id": "privacy",
        },
    ]
    state = link_known_laws({"signals": sigs, "known_laws": known})
    s0, s1 = state["signals"]
    assert s0.known_law_status == "duplicate_of_known_law"
    assert s0.known_law_match_id == "law-1"
    assert s1.known_law_status == "new"


def test_write_radar_creates_artifacts(tmp_path, monkeypatch) -> None:
    run_id = f"radar-test-{uuid4()}"
    state = {
        "run_id": run_id,
        "subject": "Meta",
        "jurisdictions": ["European Union"],
        "domains": ["privacy"],
        "lookback_days": 7,
        "levels": ["supranational"],
        "include_rumors": False,
        "cells": [
            WatchCell(
                cell_id="eu::privacy",
                jurisdiction="European Union",
                jurisdiction_id="european_union",
                domain="privacy",
                domain_id="privacy",
            )
        ],
        "signals": [
            SignalRecord(
                title="GDPR amendment in committee",
                jurisdiction_id="european_union",
                domain_id="privacy",
                source_url="https://example.com/gdpr-amendment",
                cell_id="eu::privacy",
            )
        ],
        "clusters": [
            SignalCluster(
                title="GDPR amendment in committee",
                domain_id="privacy",
                signal_ids=["sig-1"],
                publisher_names=["Example"],
            )
        ],
        "rejected": [],
        "cell_errors": [],
        "known_laws": [],
        "catalog_version": "v1",
    }
    monkeypatch.setattr(
        "langgraph_graph.news_radar.nodes.write_radar._RADAR_ROOT",
        tmp_path,
    )
    result = write_radar(state)
    assert result["error"] is None

    base = tmp_path / run_id
    assert (base / "manifest.json").exists()
    assert (base / "index.json").exists()
    assert (base / "timeline.json").exists()
    assert (base / "signals").is_dir()
    assert (base / "clusters.json").exists()
    assert (base / "cells" / "eu_privacy.json").exists()
    assert (base / "run_metrics.json").exists()
    assert (base / "delta.json").exists()

    manifest = json.loads((base / "manifest.json").read_text())
    assert manifest["signal_count"] == 1
    assert manifest["run_id"] == run_id


def test_news_radar_studio_graph_compiles() -> None:
    from langgraph_graph.news_radar.graph import graph

    # If Studio import succeeds, the bare compile must be valid.
    assert graph is not None
    assert "scan_cell" in [n for n in graph.get_graph().nodes]
