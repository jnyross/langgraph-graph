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
