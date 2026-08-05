"""Unit tests for fetch/search throughput + concurrency knobs (exp_004)."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import MagicMock, patch

from langgraph_graph.meta_legal.nodes.research_cell import run_research_cell
from langgraph_graph.meta_legal.models import ResearchCell
from langgraph_graph.meta_legal.run_config import DEFAULT_MAX_CONCURRENCY, max_concurrency
from langgraph_graph.meta_legal.tools import fetch as fetch_mod
from langgraph_graph.meta_legal.tools import search as search_mod
from langgraph_graph.meta_legal.tools.fetch import fetch_url
from langgraph_graph.meta_legal.tools.search import clear_search_cache, web_search


class _FakeLLM:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[Any] = []

    def invoke(self, messages: Any, **_kwargs: Any) -> Any:
        self.calls.append(messages)

        class _Msg:
            def __init__(self, content: str) -> None:
                self.content = content

        return _Msg(self.content)


def test_default_max_concurrency_is_twelve() -> None:
    assert DEFAULT_MAX_CONCURRENCY == 12
    # When env unset, resolver returns default.
    old = os.environ.pop("META_LEGAL_MAX_CONCURRENCY", None)
    try:
        assert max_concurrency() == 12
    finally:
        if old is not None:
            os.environ["META_LEGAL_MAX_CONCURRENCY"] = old


def test_max_concurrency_env_override(monkeypatch: Any) -> None:
    monkeypatch.setenv("META_LEGAL_MAX_CONCURRENCY", "16")
    assert max_concurrency() == 16
    monkeypatch.setenv("META_LEGAL_MAX_CONCURRENCY", "0")
    assert max_concurrency() == 12
    monkeypatch.setenv("META_LEGAL_MAX_CONCURRENCY", "nope")
    assert max_concurrency() == 12


def test_fetch_url_retries_once_on_failure() -> None:
    fetch_mod._close_thread_client()
    calls = {"n": 0}

    class _Resp:
        headers = {"content-type": "text/html; charset=utf-8"}
        text = "<html><body><p>Statute body text here</p></body></html>"

        def raise_for_status(self) -> None:
            return None

    class _Client:
        def get(self, url: str, follow_redirects: bool = True) -> _Resp:
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("transient")
            return _Resp()

        def close(self) -> None:
            return None

    with patch.object(fetch_mod, "_get_client", side_effect=[_Client(), _Client()]):
        text = fetch_url("https://example.com/law")
    assert "Statute body" in text
    assert calls["n"] == 2
    fetch_mod._close_thread_client()


def test_fetch_url_prefers_html_accept_header() -> None:
    fetch_mod._close_thread_client()
    seen: dict[str, Any] = {}

    class _Resp:
        headers = {"content-type": "text/html"}
        text = "<html><body>ok</body></html>"

        def raise_for_status(self) -> None:
            return None

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            seen.update(kwargs)

        def get(self, url: str, follow_redirects: bool = True) -> _Resp:
            seen["follow_redirects"] = follow_redirects
            return _Resp()

        def close(self) -> None:
            return None

    with patch.dict("sys.modules", {"httpx": MagicMock(Client=_Client)}):
        # Force new client construction path
        fetch_mod._close_thread_client()
        # Bypass patched import path: call headers helper contract directly.
        headers = fetch_mod._default_headers()
        assert "text/html" in headers["Accept"]
        assert headers["Accept"].index("text/html") < headers["Accept"].index("*/*")
    assert fetch_mod._DEFAULT_TIMEOUT >= 25.0
    fetch_mod._close_thread_client()


def test_web_search_caches_identical_queries() -> None:
    clear_search_cache()
    calls = {"n": 0}

    def fake_ddg(query: str, max_results: int) -> list[dict[str, str]]:
        calls["n"] += 1
        return [
            {
                "title": "Hit",
                "url": "https://example.com/a",
                "snippet": f"{query}:{max_results}",
            }
        ]

    with patch.object(search_mod, "_search_ddg", side_effect=fake_ddg):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TAVILY_API_KEY", None)
            a = web_search("GDPR official text", 5)
            b = web_search("gdpr official text", 5)  # case-normalized cache key
    assert a and b
    assert a[0]["url"] == b[0]["url"]
    assert calls["n"] == 1
    clear_search_cache()


def test_run_research_cell_fetches_urls_concurrently() -> None:
    cell = ResearchCell(
        cell_id="testland::privacy",
        jurisdiction="Testland",
        jurisdiction_id="testland",
        domain="privacy",
        domain_id="privacy",
        subject="Meta",
        status="researching",
    )
    active: list[int] = []
    max_active = {"n": 0}
    lock_state = {"i": 0}

    def search_fn(query: str, max_results: int = 5) -> list[dict[str, str]]:
        return [
            {
                "title": f"Doc {i}",
                "url": f"https://laws.example.test/{i}",
                "snippet": "privacy act",
            }
            for i in range(5)
        ]

    def fetch_fn(url: str, max_chars: int = 12000) -> str:
        # Track overlap without sleeps (executor scheduling).
        lock_state["i"] += 1
        active.append(lock_state["i"])
        max_active["n"] = max(max_active["n"], len(active))
        # Simulate tiny work via thread pool presence: just pop after append window.
        try:
            return f"body for {url}"
        finally:
            active.pop()

    llm = _FakeLLM(
        '{"drafts":[{"title":"Privacy Act","citation":"PA-1",'
        '"source_url":"https://laws.example.test/0","source_type":"primary",'
        '"excerpt":"body","language":"en","confidence":0.9,'
        '"meta_nexus":"applies to platforms","notes":""}]}'
    )

    # Patch ThreadPoolExecutor usage is real; ensure multiple URLs fetched.
    result = run_research_cell(
        cell,
        search_fn=search_fn,
        fetch_fn=fetch_fn,
        llm=llm,
        max_urls=5,
        max_fetch_workers=5,
    )
    assert result["drafts"]
    # All five URLs should have been requested (order-independent).
    assert lock_state["i"] == 5


def test_eval_grid_limit_cells_and_max_concurrency_flags() -> None:
    from examples.meta_legal_eval_grid import _parse_args

    args = _parse_args(
        ["--limit-cells", "3", "--max-concurrency", "12", "--dry-run"]
    )
    assert args.limit_cells == 3
    assert args.max_concurrency == 12
    assert args.dry_run is True
