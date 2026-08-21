"""U3: research worker unit tests (mocked search/fetch/LLM only)."""

from __future__ import annotations

from typing import Any

from langgraph_graph.meta_legal.models import LawRecordDraft, ResearchCell
from langgraph_graph.meta_legal.nodes.research_cell import (
    build_search_queries,
    research_cell,
    run_research_cell,
    seed_urls_for_cell,
    select_urls,
)


class _FakeLLM:
    """Minimal chat-model stand-in: invoke(messages) -> object with .content JSON."""

    def __init__(self, content: str, *, model_name: str = "deepseek/deepseek-v4-flash") -> None:
        self.content = content
        self.model_name = model_name
        self.calls: list[Any] = []

    def invoke(self, messages: Any, **_kwargs: Any) -> Any:
        self.calls.append(messages)

        class _Msg:
            def __init__(self, content: str) -> None:
                self.content = content

        return _Msg(self.content)

    def with_structured_output(self, *_a: Any, **_k: Any) -> Any:
        raise TypeError("structured output unused in unit tests")


def _sample_cell(**overrides: Any) -> ResearchCell:
    data = {
        "cell_id": "european_union::privacy",
        "jurisdiction": "European Union",
        "jurisdiction_id": "european_union",
        "domain": "privacy",
        "domain_id": "privacy",
        "subject": "Meta",
        "status": "researching",
    }
    data.update(overrides)
    return ResearchCell(**data)


def test_run_research_cell_happy_path_returns_draft() -> None:
    cell = _sample_cell()

    def search_fn(query: str, max_results: int = 5) -> list[dict[str, str]]:
        assert query
        assert max_results >= 1
        return [
            {
                "title": "GDPR official text",
                "url": "https://eur-lex.europa.eu/eli/reg/2016/679/oj",
                "snippet": "General Data Protection Regulation applies to controllers.",
            },
            {
                "title": "Random blog",
                "url": "https://example.com/blog/gdpr",
                "snippet": "secondary commentary",
            },
        ]

    def fetch_fn(url: str, max_chars: int = 12000) -> str:
        if "eur-lex" in url:
            return (
                "Regulation (EU) 2016/679 (GDPR) lays down rules relating to the protection "
                "of natural persons with regard to the processing of personal data and rules "
                "relating to the free movement of personal data. It applies to online platforms "
                "established in the Union and to offering of services to data subjects "
                "in the Union."
            )[:max_chars]
        return ""

    llm = _FakeLLM(
        """
        {
          "drafts": [
            {
              "title": "General Data Protection Regulation (GDPR)",
              "citation": "Regulation (EU) 2016/679",
              "source_url": "https://eur-lex.europa.eu/eli/reg/2016/679/oj",
              "source_type": "primary",
              "excerpt": "rules for protection of natural persons' personal data",
              "meta_nexus": "platform_obligation",
              "meta_nexus_rationale": "Meta processes EU user data as a platform controller.",
              "language": "en",
              "effective_date": "2018-05-25",
              "status": "in_force",
              "confidence": 0.91
            }
          ]
        }
        """
    )

    result = run_research_cell(cell, search_fn=search_fn, fetch_fn=fetch_fn, llm=llm)

    assert "drafts" in result
    assert len(result["drafts"]) >= 1
    draft = result["drafts"][0]
    assert isinstance(draft, LawRecordDraft)
    assert draft.source_url.startswith("http")
    assert draft.meta_nexus in {
        "named_party",
        "platform_obligation",
        "sector_rule",
        "other",
    }
    assert draft.cell_id == cell.cell_id
    assert draft.jurisdiction_id == "european_union"
    assert draft.domain_id == "privacy"
    assert draft.worker_model
    assert llm.calls or any(
        getattr(d, "worker_model", "") == "seed_harvest" for d in result["drafts"]
    )


def test_research_cell_accepts_flat_send_payload_dict() -> None:
    payload = {
        "cell_id": "united_states::competition",
        "jurisdiction": "United States",
        "jurisdiction_id": "united_states",
        "domain": "competition",
        "domain_id": "competition",
        "subject": "Meta",
    }

    def search_fn(query: str, max_results: int = 5) -> list[dict[str, str]]:
        return [
            {
                "title": "FTC Act",
                "url": "https://www.ftc.gov/legal-library/browse/statutes/federal-trade-commission-act",
                "snippet": "unfair methods of competition",
            }
        ]

    def fetch_fn(url: str, max_chars: int = 12000) -> str:
        return "Section 5 prohibits unfair methods of competition in or affecting commerce."

    llm = _FakeLLM(
        '{"drafts":[{"title":"FTC Act §5","citation":"15 U.S.C. §45",'
        '"source_url":"https://www.ftc.gov/legal-library/browse/statutes/federal-trade-commission-act",'
        '"source_type":"primary","excerpt":"unfair methods of competition",'
        '"meta_nexus":"platform_obligation","meta_nexus_rationale":"US platform competition rules",'
        '"confidence":0.8}]}'
    )

    out = run_research_cell(payload, search_fn=search_fn, fetch_fn=fetch_fn, llm=llm)
    assert out["drafts"][0].domain_id == "competition"


def test_empty_search_harvests_when_fetches_succeed() -> None:
    # Seedless jurisdiction: empty search no longer short-circuits; drafts are
    # emitted only from successful seed fetches (worker_model='seed_harvest').
    cell = _sample_cell(
        cell_id="atlantis::ip",
        jurisdiction="Atlantis",
        jurisdiction_id="atlantis",
        domain="ip",
        domain_id="ip",
    )

    def search_fn(query: str, max_results: int = 5) -> list[dict[str, str]]:
        return []

    def fetch_fn(url: str, max_chars: int = 12000) -> str:
        return "Instrument text: " + url

    class _BoomLLM:
        def invoke(self, *_a: Any, **_k: Any) -> Any:
            raise AssertionError("llm should not be required when harvest floor works")

    result = run_research_cell(
        cell,
        search_fn=search_fn,
        fetch_fn=fetch_fn,
        llm=_BoomLLM(),
    )

    assert len(result["drafts"]) >= 1
    assert all(d.worker_model == "seed_harvest" for d in result["drafts"])
    assert all(d.source_url.startswith("http") for d in result["drafts"])
    assert any("wipo.int" in d.source_url or "fao.org" in d.source_url for d in result["drafts"])
    # Soft warnings ok; hard "search returned no results" only when drafts empty.
    assert not any(
        err.message == "search returned no results" for err in result.get("cell_errors", [])
    )


def test_empty_search_all_fetches_fail_yields_no_drafts() -> None:
    # All seed fetches failing yields [] so the caller's LLM gate can engage.
    cell = _sample_cell(
        cell_id="atlantis::ip",
        jurisdiction="Atlantis",
        jurisdiction_id="atlantis",
        domain="ip",
        domain_id="ip",
    )

    def search_fn(query: str, max_results: int = 5) -> list[dict[str, str]]:
        return []

    def fetch_fn(url: str, max_chars: int = 12000) -> str:
        raise RuntimeError("fetch backend down")

    class _BoomLLM:
        def invoke(self, *_a: Any, **_k: Any) -> Any:
            raise AssertionError("llm should not be required when harvest floor works")

    result = run_research_cell(
        cell,
        search_fn=search_fn,
        fetch_fn=fetch_fn,
        llm=_BoomLLM(),
    )

    assert result["drafts"] == []



def test_build_search_queries_eu_privacy_instrument_first() -> None:
    cell = _sample_cell()
    queries = build_search_queries(cell)
    assert queries
    joined = "\n".join(queries)
    assert any("GDPR" in q or "eur-lex" in q.lower() for q in queries)
    # Instrument-first: not every query starts with Meta
    assert not all(q.lower().startswith("meta") for q in queries)
    # At most one subject-nexus query leads with Meta
    meta_leading = sum(1 for q in queries if q.lower().startswith("meta"))
    assert meta_leading <= 1
    assert "official text" in joined.lower() or "site:eur-lex" in joined.lower()


def test_seed_urls_for_eu_privacy() -> None:
    cell = _sample_cell()
    seeds = seed_urls_for_cell(cell)
    assert seeds
    assert any("eur-lex.europa.eu" in u for u in seeds)
    assert any("2016/679" in u for u in seeds)


def test_empty_search_continues_with_seed_urls() -> None:
    cell = _sample_cell()

    def search_fn(query: str, max_results: int = 5) -> list[dict[str, str]]:
        return []

    fetched: list[str] = []

    def fetch_fn(url: str, max_chars: int = 12000) -> str:
        fetched.append(url)
        if "eur-lex" in url and "679" in url:
            return (
                "Regulation (EU) 2016/679 (GDPR) protects natural persons with regard "
                "to the processing of personal data."
            )[:max_chars]
        return "seed page"

    llm = _FakeLLM(
        '{"drafts":[{"title":"GDPR","citation":"Regulation (EU) 2016/679",'
        '"source_url":"https://eur-lex.europa.eu/eli/reg/2016/679/oj",'
        '"source_type":"primary","excerpt":"processing of personal data",'
        '"meta_nexus":"platform_obligation","meta_nexus_rationale":"EU platform data",'
        '"confidence":0.9}]}'
    )

    result = run_research_cell(cell, search_fn=search_fn, fetch_fn=fetch_fn, llm=llm)
    assert fetched, "seed URLs should be fetched when search is empty"
    assert any("eur-lex" in u for u in fetched)
    assert len(result["drafts"]) >= 1


def test_host_score_demotes_meta_marketing() -> None:
    hits = [
        {
            "title": "Meta privacy center",
            "url": "https://www.meta.com/privacy",
            "snippet": "marketing",
        },
        {
            "title": "GDPR",
            "url": "https://eur-lex.europa.eu/eli/reg/2016/679/oj",
            "snippet": "official",
        },
        {
            "title": "Facebook help",
            "url": "https://www.facebook.com/privacy/policy",
            "snippet": "product",
        },
        {
            "title": "EDPB guidance",
            "url": "https://edpb.europa.eu/our-work-tools/general-guidance_en",
            "snippet": "guidance",
        },
    ]
    urls = select_urls(hits, limit=2)
    assert urls
    assert "eur-lex.europa.eu" in urls[0] or "edpb.europa.eu" in urls[0]
    assert not any("meta.com" in u or "facebook.com" in u for u in urls)


def test_partial_fetch_failure_still_yields_drafts() -> None:
    # Seedless cell so search hits drive fetch (seed-first path would skip search).
    cell = _sample_cell(
        cell_id="atlantis::youth_safety",
        jurisdiction="Atlantis",
        jurisdiction_id="atlantis",
        domain="youth_safety",
        domain_id="youth_safety",
    )

    def search_fn(query: str, max_results: int = 5) -> list[dict[str, str]]:
        return [
            {
                "title": "Online Safety Act",
                "url": "https://www.legislation.gov.uk/ukpga/2023/50/contents",
                "snippet": "duties of care for user-to-user services",
            },
            {
                "title": "Broken mirror",
                "url": "https://broken.example.invalid/osa",
                "snippet": "mirror copy",
            },
        ]

    def fetch_fn(url: str, max_chars: int = 12000) -> str:
        if "broken.example" in url:
            raise TimeoutError("simulated fetch failure")
        if "legislation.gov.uk" in url:
            return (
                "Online Safety Act 2023 imposes duties on providers of regulated "
                "user-to-user services to protect children from harmful content."
            )
        return ""

    llm = _FakeLLM(
        """
        {
          "drafts": [
            {
              "title": "Online Safety Act 2023",
              "citation": "UK Public General Acts 2023 c. 50",
              "source_url": "https://www.legislation.gov.uk/ukpga/2023/50/contents",
              "source_type": "primary",
              "excerpt": "duties on providers of regulated U2U services to protect children",
              "meta_nexus": "platform_obligation",
              "meta_nexus_rationale": "Meta operates U2U services used by UK children.",
              "confidence": 0.88
            }
          ]
        }
        """
    )

    result = run_research_cell(cell, search_fn=search_fn, fetch_fn=fetch_fn, llm=llm)

    assert len(result["drafts"]) >= 1
    draft = result["drafts"][0]
    assert draft.source_url
    assert draft.meta_nexus
    # soft-fail should record the broken URL without aborting the cell
    errors = result.get("cell_errors") or []
    assert any("broken.example" in err.message for err in errors)


def test_research_cell_never_raises_on_total_tool_failure(monkeypatch: Any) -> None:
    def search_fn(query: str, max_results: int = 5) -> list[dict[str, str]]:
        raise RuntimeError("search backend down")

    def fetch_fn(url: str, max_chars: int = 12000) -> str:
        raise RuntimeError("fetch backend down")

    class _BadLLM:
        def invoke(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("llm down")

    out = run_research_cell(
        {
            "cell_id": "x::privacy",
            "jurisdiction": "X",
            "jurisdiction_id": "x",
            "domain": "privacy",
            "domain_id": "privacy",
        },
        search_fn=search_fn,
        fetch_fn=fetch_fn,
        llm=_BadLLM(),
    )
    assert out["drafts"] == []  # fetch-backed emission: no drafts when all tools fail
    assert out.get("cell_errors")
    assert out.get("accepted") == []

    # Node entry must also soft-fail. Patch tools so the test stays offline.
    monkeypatch.setattr(
        "langgraph_graph.meta_legal.nodes.research_cell.default_web_search",
        search_fn,
    )
    monkeypatch.setattr(
        "langgraph_graph.meta_legal.nodes.research_cell.default_fetch_url",
        fetch_fn,
    )
    monkeypatch.setattr(
        "langgraph_graph.meta_legal.nodes.research_cell.get_llm",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("llm unavailable")),
    )
    wrapped = research_cell({"cell_id": "y::privacy", "jurisdiction": "Y", "domain": "privacy"})
    assert "drafts" in wrapped
    assert isinstance(wrapped.get("drafts"), list)


def _harvest_covered_llm_case(monkeypatch: Any) -> tuple[Any, dict[str, list[Any]]]:
    """Harvest yields 3+ drafts (floor covered); return (fake_llm, result)."""
    cell = _sample_cell()
    seeds = seed_urls_for_cell(cell)
    harvested = [
        LawRecordDraft(
            title=f"Harvested instrument {i}",
            citation=f"Harvest citation {i}",
            source_url=seeds[i % len(seeds)],
            source_type="primary",
            excerpt="harvested excerpt",
            meta_nexus="platform_obligation",
            language="en",
            confidence=0.8,
            worker_model="seed_harvest",
            cell_id=cell.cell_id,
            jurisdiction_id=cell.jurisdiction_id,
            domain_id=cell.domain_id,
        )
        for i in range(3)
    ]

    def fake_harvest(resolved: Any, **_kwargs: Any) -> list[LawRecordDraft]:
        return harvested

    monkeypatch.setattr(
        "langgraph_graph.meta_legal.nodes.research_cell.harvest_seed_instruments",
        fake_harvest,
    )

    def search_fn(query: str, max_results: int = 5) -> list[dict[str, str]]:
        return [
            {
                "title": "LLM-only source",
                "url": "https://example.com/llm-source",
                "snippet": "secondary commentary",
            }
        ]

    def fetch_fn(url: str, max_chars: int = 12000) -> str:
        return "Some page body."[:max_chars]

    llm = _FakeLLM(
        """
        {
          "drafts": [
            {
              "title": "LLM-extracted instrument",
              "citation": "LLM citation",
              "source_url": "https://example.com/llm-source",
              "source_type": "secondary",
              "excerpt": "llm excerpt",
              "meta_nexus": "platform_obligation",
              "meta_nexus_rationale": "platform duty",
              "language": "en",
              "status": "in_force",
              "confidence": 0.9
            }
          ]
        }
        """
    )
    result = run_research_cell(cell, search_fn=search_fn, fetch_fn=fetch_fn, llm=llm)
    return llm, result


def test_force_llm_env_invokes_llm_even_when_harvest_covers(monkeypatch: Any) -> None:
    monkeypatch.setenv("META_LEGAL_FORCE_LLM", "1")
    llm, result = _harvest_covered_llm_case(monkeypatch)

    assert llm.calls, "forced knob must run LLM extraction even with 3+ harvested drafts"
    titles = {d.title for d in result["drafts"]}
    assert "LLM-extracted instrument" in titles


def test_default_env_skips_llm_when_harvest_covers(monkeypatch: Any) -> None:
    monkeypatch.delenv("META_LEGAL_FORCE_LLM", raising=False)
    llm, result = _harvest_covered_llm_case(monkeypatch)

    assert llm.calls == [], "default env must skip LLM extraction when harvest covers"
    titles = {d.title for d in result["drafts"]}
    assert "LLM-extracted instrument" not in titles
