"""Smoke tests for the HITL UI static + proxy server."""

from __future__ import annotations

from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.request import urlopen

from langgraph_graph.hitl_ui.server import _make_handler, _ui_root


def test_serves_index_html() -> None:
    ui_dir = _ui_root()
    handler = _make_handler(ui_dir, "http://127.0.0.1:9")
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            body = resp.read().decode()
            assert resp.status == 200
            assert "HITL Control" in body
        with urlopen(f"http://127.0.0.1:{port}/app.js", timeout=5) as resp:
            js = resp.read().decode()
            assert "resumeWith" in js
    finally:
        server.shutdown()
        server.server_close()
