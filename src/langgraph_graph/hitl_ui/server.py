"""Serve ``apps/hitl-ui`` and proxy ``/lg/*`` to the LangGraph Agent Server.

Usage::

    uv run python -m langgraph_graph.hitl_ui.server
    uv run python -m langgraph_graph.hitl_ui.server --port 3100 --upstream http://127.0.0.1:2024

Environment
-----------
``HITL_UI_PORT``           – default port (default ``3100``)
``HITL_UI_UPSTREAM``       – LangGraph API base (default ``http://127.0.0.1:2024``)
``HITL_UI_ROOT``           – override static directory
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import socket
import sys
from http.client import HTTPConnection, HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_UI_ROOT = _REPO_ROOT / "apps" / "hitl-ui"
_DEFAULT_PORT = int(os.environ.get("HITL_UI_PORT", "3100"))
_DEFAULT_UPSTREAM = os.environ.get("HITL_UI_UPSTREAM", "http://127.0.0.1:2024")

# Paths the HITL UI needs to hit on the upstream LangGraph Agent Server.
_ALLOWED_UPSTREAM_PATHS: list[tuple[str, re.Pattern[str]]] = [
    ("GET", re.compile(r"^/threads/[^/]+/state$")),
    ("POST", re.compile(r"^/threads/[^/]+/runs/wait$")),
    ("POST", re.compile(r"^/threads$")),
]


def _is_allowed_upstream_path(method: str, path: str) -> bool:
    return any(
        allowed_method == method and pattern.match(path)
        for allowed_method, pattern in _ALLOWED_UPSTREAM_PATHS
    )


def _ui_root(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("HITL_UI_ROOT")
    if env:
        return Path(env)
    return _DEFAULT_UI_ROOT


def _is_loopback(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return False
        return all(
            ipaddress.ip_address(info[4][0]).is_loopback for info in infos
        )
    return addr.is_loopback


def _allowed_host_names(bind_host: str) -> set[str]:
    """Return acceptable Host header hostnames for the UI server."""
    names = {"127.0.0.1", "localhost", "::1"}
    host = bind_host.lower()
    if host not in names and host not in {"0.0.0.0", "::", ""}:
        names.add(host)
    return names


def _make_handler(
    ui_dir: Path,
    upstream: str,
    allowed_hosts: set[str] | None = None,
    csrf_token: str | None = None,
):
    upstream_parsed = urlparse(upstream)
    upstream_host = upstream_parsed.hostname or "127.0.0.1"
    upstream_port = upstream_parsed.port or (443 if upstream_parsed.scheme == "https" else 80)
    upstream_is_https = upstream_parsed.scheme == "https"

    class HitlUiHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:  # type: ignore[override]
            sys.stderr.write(
                f"{self.client_address[0]} - - [{self.log_date_time_string()}] {fmt % args}\n"
            )

        def _check_host(self) -> bool:
            if allowed_hosts is None:
                return True
            host_header = self.headers.get("Host", "")
            if not host_header:
                self.send_error(403, "Invalid Host header")
                return False
            parsed = urlparse(f"http://{host_header}")
            hostname = (parsed.hostname or "").lower()
            if hostname not in allowed_hosts:
                self.send_error(403, "Invalid Host header")
                return False
            return True

        def do_OPTIONS(self) -> None:  # noqa: N802
            if not self._check_host():
                return
            self.send_response(204)
            self._cors_headers()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            if not self._check_host():
                return
            if self.path.startswith("/lg"):
                self._proxy()
                return
            self._serve_static()

        def do_POST(self) -> None:  # noqa: N802
            if not self._check_host():
                return
            if self.path.startswith("/lg"):
                self._proxy()
                return
            self.send_error(405, "POST only supported under /lg")

        def do_PUT(self) -> None:  # noqa: N802
            if not self._check_host():
                return
            if self.path.startswith("/lg"):
                self._proxy()
                return
            self.send_error(405, "PUT only supported under /lg")

        def do_DELETE(self) -> None:  # noqa: N802
            if not self._check_host():
                return
            if self.path.startswith("/lg"):
                self._proxy()
                return
            self.send_error(405, "DELETE only supported under /lg")

        def do_PATCH(self) -> None:  # noqa: N802
            if not self._check_host():
                return
            if self.path.startswith("/lg"):
                self._proxy()
                return
            self.send_error(405, "PATCH only supported under /lg")

        def _is_allowed_origin(self, origin: str) -> bool:
            host = self.headers.get("Host")
            if not host:
                return False
            # The UI is served from the same origin as the proxy; only allow that origin.
            return origin.lower() == f"http://{host}".lower()

        def _cors_headers(self) -> None:
            origin = self.headers.get("Origin")
            if not origin or not self._is_allowed_origin(origin):
                return
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header(
                "Access-Control-Allow-Methods",
                "GET, POST, PUT, PATCH, DELETE, OPTIONS",
            )
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type, Authorization, x-api-key, x-hitl-csrf-token",
            )

        def _serve_static(self) -> None:
            parsed = urlparse(self.path)
            rel = parsed.path.lstrip("/") or "index.html"
            target = (ui_dir / rel).resolve()
            try:
                target.relative_to(ui_dir.resolve())
            except ValueError:
                self.send_error(403, "Forbidden")
                return
            if target.is_dir():
                target = target / "index.html"
            if not target.is_file():
                self.send_error(404, f"Not found: {rel}")
                return
            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            raw = target.read_text(encoding="utf-8")
            if target.name == "index.html" and csrf_token is not None:
                raw = raw.replace("{{HITL_CSRF_TOKEN}}", csrf_token)
            data = raw.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _proxy(self) -> None:
            if csrf_token is not None:
                token_header = self.headers.get("X-HITL-CSRF-Token")
                if token_header != csrf_token:
                    self.send_error(403, "Invalid CSRF token")
                    return

            # Strip the /lg prefix: /lg/threads -> /threads
            parsed = urlparse(self.path)
            upstream_path = parsed.path[3:] or "/"
            if not upstream_path.startswith("/"):
                upstream_path = "/" + upstream_path
            if parsed.query:
                upstream_path = f"{upstream_path}?{parsed.query}"

            if not _is_allowed_upstream_path(self.command, parsed.path[3:] or "/"):
                self.send_error(403, "Disallowed upstream path")
                return

            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else None

            conn: HTTPConnection | HTTPSConnection
            if upstream_is_https:
                conn = HTTPSConnection(upstream_host, upstream_port, timeout=300)
            else:
                conn = HTTPConnection(upstream_host, upstream_port, timeout=300)

            safe_headers = {
                "content-type",
                "authorization",
                "x-api-key",
                "accept",
                "accept-language",
            }
            headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower() in safe_headers
            }
            headers["Host"] = (
                f"{upstream_host}:{upstream_port}"
                if upstream_port not in {80, 443}
                else upstream_host
            )
            if body is not None:
                headers["Content-Length"] = str(len(body))

            try:
                conn.request(self.command, upstream_path, body=body, headers=headers)
                resp = conn.getresponse()
                resp_body = resp.read()
            except OSError:
                payload = json.dumps({"error": "upstream unreachable"}).encode()
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self._cors_headers()
                self.end_headers()
                self.wfile.write(payload)
                return
            finally:
                conn.close()

            self.send_response(resp.status)
            hop_by_hop = {
                "connection",
                "transfer-encoding",
                "keep-alive",
                "proxy-authenticate",
                "proxy-authorization",
                "te",
                "trailers",
                "upgrade",
                "content-encoding",
                "content-length",
            }
            for key, value in resp.getheaders():
                if key.lower().startswith("access-control-") or key.lower() in hop_by_hop:
                    continue
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(resp_body)))
            self._cors_headers()
            self.end_headers()
            self.wfile.write(resp_body)

    return HitlUiHandler


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Serve the minimal HITL UI")
    parser.add_argument("--port", type=int, default=_DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--upstream", default=_DEFAULT_UPSTREAM)
    parser.add_argument("--ui-root", default=None)
    args = parser.parse_args(argv)

    ui_dir = _ui_root(args.ui_root)
    if not ui_dir.is_dir():
        raise SystemExit(f"HITL UI directory not found: {ui_dir}")

    if not _is_loopback(args.host):
        raise SystemExit(
            f"HITL UI server can only bind to loopback addresses for security; "
            f"{args.host!r} is not allowed."
        )

    allowed_hosts = _allowed_host_names(args.host)
    csrf_token = secrets.token_urlsafe(32)
    handler = _make_handler(
        ui_dir,
        args.upstream,
        allowed_hosts=allowed_hosts,
        csrf_token=csrf_token,
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"HITL UI → http://{args.host}:{args.port}/?assistantId=hitl_demo")
    print(f"Proxying /lg/* → {args.upstream}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping HITL UI server")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
