"""Unit tests for Firecrawl fetch/search backends (exp_008)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from langgraph_graph.meta_legal.tools import fetch as fetch_mod
from langgraph_graph.meta_legal.tools import search as search_mod
from langgraph_graph.meta_legal.tools.fetch import fetch_url
from langgraph_graph.meta_legal.tools.search import (
    clear_search_cache,
    reset_search_breaker,
    web_search,
)


def test_fetch_via_firecrawl_happy_path_truncates(monkeypatch: Any) -> None:
    body = {"success": True, "data": {"markdown": "X" * 50}}
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = body

    mock_httpx = MagicMock()
    mock_httpx.post.return_value = response
    monkeypatch.setitem(__import__("sys").modules, "httpx", mock_httpx)

    text = fetch_mod._fetch_via_firecrawl("https://example.com/law", max_chars=20)
    assert text == "X" * 20
    mock_httpx.post.assert_called_once()
    kwargs = mock_httpx.post.call_args
    assert kwargs.args[0].endswith("/v2/scrape")
    assert kwargs.kwargs["json"]["formats"] == ["markdown"]
    assert kwargs.kwargs["json"]["onlyMainContent"] is True
    assert kwargs.kwargs["json"]["timeout"] == 8000
    assert kwargs.kwargs["timeout"] == 10.0


def test_fetch_url_auto_falls_through_to_httpx(monkeypatch: Any) -> None:
    fetch_mod.clear_fetch_cache()
    monkeypatch.setenv("META_LEGAL_FETCH_BACKEND", "auto")
    monkeypatch.setattr(fetch_mod, "_fetch_via_firecrawl", lambda *_a, **_k: "")
    monkeypatch.setattr(fetch_mod, "_fetch_via_httpx", lambda *_a, **_k: "fallback")
    assert fetch_url("https://example.com/x", max_chars=100) == "fallback"


def test_fetch_url_httpx_backend_skips_firecrawl(monkeypatch: Any) -> None:
    fetch_mod.clear_fetch_cache()
    monkeypatch.setenv("META_LEGAL_FETCH_BACKEND", "httpx")
    calls: list[str] = []

    def _fc(*_a: Any, **_k: Any) -> str:
        calls.append("firecrawl")
        return "should-not-use"

    def _hx(*_a: Any, **_k: Any) -> str:
        calls.append("httpx")
        return "via-httpx"

    monkeypatch.setattr(fetch_mod, "_fetch_via_firecrawl", _fc)
    monkeypatch.setattr(fetch_mod, "_fetch_via_httpx", _hx)
    assert fetch_url("https://example.com/x", max_chars=100) == "via-httpx"
    assert calls == ["httpx"]


def test_search_firecrawl_cli_parses_payload(monkeypatch: Any) -> None:
    payload = {
        "data": {
            "web": [
                {
                    "title": "GDPR",
                    "url": "https://eur-lex.europa.eu/eli/reg/2016/679/oj",
                    "description": "General Data Protection Regulation",
                }
            ]
        }
    }
    completed = MagicMock()
    completed.returncode = 0
    completed.stdout = json.dumps(payload)

    monkeypatch.setattr(search_mod, "_FIRECRAWL_CLI", True)
    monkeypatch.setattr(search_mod.subprocess, "run", lambda *_a, **_k: completed)

    hits = search_mod._search_firecrawl_cli("GDPR official text", max_results=5)
    assert len(hits) == 1
    assert hits[0]["title"] == "GDPR"
    assert hits[0]["url"].startswith("https://eur-lex.europa.eu/")
    assert "Data Protection" in hits[0]["snippet"]


def test_search_firecrawl_cli_missing_binary(monkeypatch: Any) -> None:
    monkeypatch.setattr(search_mod, "_FIRECRAWL_CLI", False)
    assert search_mod._search_firecrawl_cli("anything", 3) == []


def test_web_search_prefers_firecrawl_over_ddg(monkeypatch: Any) -> None:
    clear_search_cache()
    reset_search_breaker()
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(search_mod, "_FIRECRAWL_CLI", True)

    fc_hits = [
        {
            "title": "ePrivacy",
            "url": "https://eur-lex.europa.eu/eli/dir/2002/58/oj",
            "snippet": "Directive 2002/58/EC",
        }
    ]
    ddg_calls: list[str] = []

    monkeypatch.setattr(search_mod, "_search_firecrawl_cli", lambda *_a, **_k: fc_hits)

    def _ddg(*_a: Any, **_k: Any) -> list[dict[str, str]]:
        ddg_calls.append("called")
        return [{"title": "ddg", "url": "https://ddg.example", "snippet": "nope"}]

    monkeypatch.setattr(search_mod, "_search_ddg", _ddg)

    hits = web_search("EU ePrivacy Directive 2002/58 official text", max_results=5)
    assert hits == fc_hits
    assert ddg_calls == []
    clear_search_cache()
    reset_search_breaker()


def test_web_search_firecrawl_empty_skips_ddg(monkeypatch: Any) -> None:
    """With CLI present, empty Firecrawl results must not stampede DDG."""
    clear_search_cache()
    reset_search_breaker()
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(search_mod, "_FIRECRAWL_CLI", True)
    monkeypatch.setattr(search_mod, "_search_firecrawl_cli", lambda *_a, **_k: [])
    ddg_calls: list[str] = []

    def _ddg(*_a: Any, **_k: Any) -> list[dict[str, str]]:
        ddg_calls.append("called")
        return [{"title": "ddg", "url": "https://ddg.example", "snippet": "nope"}]

    monkeypatch.setattr(search_mod, "_search_ddg", _ddg)
    assert web_search("no hits query xyz", max_results=5) == []
    assert ddg_calls == []
    clear_search_cache()
    reset_search_breaker()


def test_web_search_auto_tries_firecrawl_api_before_cli_and_ddg(monkeypatch: Any) -> None:
    """auto + FIRECRAWL_API_KEY: REST API is probed before CLI/DDG fallbacks."""
    clear_search_cache()
    reset_search_breaker()
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
    monkeypatch.setattr(search_mod, "_FIRECRAWL_CLI", True)
    calls: list[str] = []

    fc_api_hits = [{"title": "DSA", "url": "https://eur-lex.europa.eu/dsa", "snippet": "s"}]

    def _api(*_a: Any, **_k: Any) -> list[dict[str, str]]:
        calls.append("api")
        return fc_api_hits

    def _cli(*_a: Any, **_k: Any) -> list[dict[str, str]]:
        calls.append("cli")
        return []

    def _ddg(*_a: Any, **_k: Any) -> list[dict[str, str]]:
        calls.append("ddg")
        return []

    monkeypatch.setattr(search_mod, "_search_firecrawl_api", _api)
    monkeypatch.setattr(search_mod, "_search_firecrawl_cli", _cli)
    monkeypatch.setattr(search_mod, "_search_ddg", _ddg)

    hits = web_search("digital services act text", max_results=5)
    assert hits == fc_api_hits
    assert calls == ["api"]
    clear_search_cache()
    reset_search_breaker()


def test_web_search_auto_empty_firecrawl_api_falls_to_cli(monkeypatch: Any) -> None:
    """auto + FIRECRAWL_API_KEY: empty API result probes the CLI, never DDG."""
    clear_search_cache()
    reset_search_breaker()
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
    monkeypatch.setattr(search_mod, "_FIRECRAWL_CLI", True)
    calls: list[str] = []

    def _api(*_a: Any, **_k: Any) -> list[dict[str, str]]:
        calls.append("api")
        return []

    def _cli(*_a: Any, **_k: Any) -> list[dict[str, str]]:
        calls.append("cli")
        return []

    def _ddg(*_a: Any, **_k: Any) -> list[dict[str, str]]:
        calls.append("ddg")
        return []

    monkeypatch.setattr(search_mod, "_search_firecrawl_api", _api)
    monkeypatch.setattr(search_mod, "_search_firecrawl_cli", _cli)
    monkeypatch.setattr(search_mod, "_search_ddg", _ddg)

    assert web_search("empty api query xyz", max_results=5) == []
    assert calls == ["api", "cli"]
    clear_search_cache()
    reset_search_breaker()


def test_fetch_breaker_skips_doomed_post_after_consecutive_failures(
    monkeypatch: Any,
) -> None:
    """N consecutive Firecrawl failures open the breaker: the POST is skipped
    entirely and auto mode falls straight through to httpx."""
    fetch_mod.clear_fetch_cache()
    fetch_mod.reset_fetch_breaker()
    monkeypatch.delenv("META_LEGAL_FETCH_BREAKER_N", raising=False)
    monkeypatch.delenv("META_LEGAL_FETCH_BREAKER_COOLDOWN_S", raising=False)
    monkeypatch.setenv("META_LEGAL_FETCH_BACKEND", "firecrawl")
    posts = {"n": 0}

    def _failing_request(*_a: Any, **_k: Any) -> str:
        posts["n"] += 1
        return ""

    monkeypatch.setattr(fetch_mod, "_fetch_via_firecrawl_request", _failing_request)

    for i in range(3):
        assert fetch_url(f"https://example.com/dead/{i}", max_chars=100) == ""
    assert posts["n"] == 3
    assert fetch_mod._fetch_breaker_state() == "open"
    # Breaker open: no further POSTs are paid.
    assert fetch_url("https://example.com/dead/fresh", max_chars=100) == ""
    assert posts["n"] == 3
    fetch_mod.reset_fetch_breaker()
    assert fetch_mod._fetch_breaker_state() == "closed"


def test_fetch_breaker_success_resets_streak(monkeypatch: Any) -> None:
    fetch_mod.clear_fetch_cache()
    fetch_mod.reset_fetch_breaker()
    monkeypatch.setenv("META_LEGAL_FETCH_BACKEND", "firecrawl")
    responses = ["", "", "ok body"]

    def _flaky_request(*_a: Any, **_k: Any) -> str:
        return responses.pop(0) if responses else "ok body"

    monkeypatch.setattr(fetch_mod, "_fetch_via_firecrawl_request", _flaky_request)
    assert fetch_url("https://example.com/a", max_chars=100) == ""
    assert fetch_url("https://example.com/b", max_chars=100) == ""
    assert fetch_url("https://example.com/c", max_chars=100) == "ok body"
    assert fetch_mod._fetch_breaker_state() == "closed"
    fetch_mod.reset_fetch_breaker()
