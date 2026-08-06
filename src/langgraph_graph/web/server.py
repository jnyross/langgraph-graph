"""Minimal HTTP server for the law-matrix website.

Uses only the standard library (``http.server``) plus the existing
aggregation layer — no extra dependencies.

Endpoints
---------
``GET /api/matrix``
    Full aggregated matrix JSON (same as ``generate_matrix_json`` output).

``GET /api/laws?jurisdiction=<id>&domain=<id>&q=<text>``
    Filtered flat law list. All query params are optional and combined with
    AND. ``jurisdiction`` matches ``jurisdiction_id`` (case-insensitive),
    ``domain`` matches ``domain_id`` (case-insensitive), ``q`` is a
    case-insensitive substring search over ``title``, ``citation``,
    ``excerpt``, and ``source_url``.

``GET /api/runs``
    List of runs with their manifests: ``[{run_id, manifest}, ...]``.

Static files
------------
Any other ``GET`` path is served from the ``web/`` directory at the repo
root (if it exists). ``/`` serves ``web/index.html`` when present.
Unknown paths return 404.

Usage
-----
::

    uv run python -m langgraph_graph.web.server
    uv run python -m langgraph_graph.web.server --port 8765
    uv run python src/langgraph_graph/web/server.py --port 8765 --dossier-root data/dossiers

Environment
-----------
``PORT``         – default port (default ``8000``)
``DOSSIER_ROOT`` – override dossier directory
``WEB_ROOT``     – override static file directory
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from langgraph_graph.web.aggregator import collect_all_laws, discover_runs, load_manifest

# Repo root: src/langgraph_graph/web/server.py -> parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_WEB_ROOT = _REPO_ROOT / "web"
_DEFAULT_PORT = int(os.environ.get("PORT", "8000"))


def _web_root(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("WEB_ROOT")
    if env:
        return Path(env)
    return _DEFAULT_WEB_ROOT


def _resolve_dossier_root(explicit: str | Path | None = None) -> Path | None:
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("DOSSIER_ROOT")
    if env:
        return Path(env)
    return None  # let aggregator use its default resolution


# ---------------------------------------------------------------------------
# request handler factory (closure over config)
# ---------------------------------------------------------------------------


def _make_handler(web_dir: Path, dossier_root: Path | None):
    """Create a ``BaseHTTPRequestHandler`` subclass bound to *web_dir*."""

    class MatrixHandler(BaseHTTPRequestHandler):
        # Suppress default log noise or keep it – we keep a minimal log.
        def log_message(self, fmt, *args):  # type: ignore[override]
            # Use stderr; keep it terse
            import sys

            log_line = (
                f"{self.client_address[0]} - - "
                f"[{self.log_date_time_string()}] {fmt % args}\n"
            )
            sys.stderr.write(log_line)

        # ---- helpers ----

        def _send_json(self, obj, status: int = 200) -> None:
            body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_text(
            self,
            text: str,
            content_type: str = "text/plain",
            status: int = 200,
        ) -> None:
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        # ---- routing ----

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)

            # CORS preflight helper
            if path.startswith("/api/"):
                # API routes
                if path == "/api/matrix":
                    self._handle_matrix()
                    return
                if path == "/api/laws":
                    self._handle_laws(qs)
                    return
                if path == "/api/runs":
                    self._handle_runs()
                    return
                # Unknown API
                self._send_json({"error": f"unknown API path: {path}"}, status=404)
                return

            # Static file serving
            self._handle_static(path)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", "0")
            self.end_headers()

        # ---- API handlers ----

        def _handle_matrix(self) -> None:
            try:
                matrix = collect_all_laws(dossier_root)
                self._send_json(matrix)
            except Exception as exc:  # pragma: no cover
                self._send_json({"error": str(exc)}, status=500)

        def _handle_laws(self, qs: dict[str, list[str]]) -> None:
            try:
                matrix = collect_all_laws(dossier_root)
                laws = matrix.get("laws", [])

                jurisdiction = (qs.get("jurisdiction", [None])[0] or "").strip()
                domain = (qs.get("domain", [None])[0] or "").strip()
                q = (qs.get("q", [None])[0] or "").strip()

                filtered = laws
                if jurisdiction:
                    j_lower = jurisdiction.lower()
                    filtered = [
                        r
                        for r in filtered
                        if str(r.get("jurisdiction_id", "")).lower() == j_lower
                    ]
                if domain:
                    d_lower = domain.lower()
                    filtered = [
                        r
                        for r in filtered
                        if str(r.get("domain_id", "")).lower() == d_lower
                    ]
                if q:
                    q_lower = q.lower()
                    def _matches(rec: dict) -> bool:
                        haystack = " ".join(
                            str(rec.get(k) or "")
                            for k in (
                                "title",
                                "citation",
                                "excerpt",
                                "source_url",
                                "jurisdiction_id",
                                "domain_id",
                                "cell_id",
                            )
                        ).lower()
                        return q_lower in haystack

                    filtered = [r for r in filtered if _matches(r)]

                self._send_json(
                    {
                        "count": len(filtered),
                        "total": len(laws),
                        "filters": {
                            "jurisdiction": jurisdiction or None,
                            "domain": domain or None,
                            "q": q or None,
                        },
                        "laws": filtered,
                    }
                )
            except Exception as exc:  # pragma: no cover
                self._send_json({"error": str(exc)}, status=500)

        def _handle_runs(self) -> None:
            try:
                runs = discover_runs(dossier_root)
                items = []
                for run_id in runs:
                    manifest = load_manifest(run_id, dossier_root)
                    items.append({"run_id": run_id, "manifest": manifest})
                self._send_json({"count": len(items), "runs": items})
            except Exception as exc:  # pragma: no cover
                self._send_json({"error": str(exc)}, status=500)

        # ---- static ----

        def _handle_static(self, path: str) -> None:
            # Normalize path
            if path == "/":
                path = "/index.html"
            # Prevent directory traversal
            safe = Path(path.lstrip("/"))
            if ".." in safe.parts:
                self._send_text("Not found", status=404)
                return
            file_path = web_dir / safe
            # If path is a directory, try index.html
            if file_path.is_dir():
                file_path = file_path / "index.html"
            if not file_path.is_file():
                # For SPA-style frontend, unknown non-API paths could return
                # 404 with helpful message. We do not fallback to index.html
                # blindly to avoid masking 404s for assets.
                self._send_text(f"Not found: {path}", status=404)
                return
            # Serve file
            ctype, _ = mimetypes.guess_type(str(file_path))
            if ctype is None:
                ctype = "application/octet-stream"
                if file_path.suffix in (".js", ".mjs"):
                    ctype = "text/javascript; charset=utf-8"
                elif file_path.suffix == ".css":
                    ctype = "text/css; charset=utf-8"
                elif file_path.suffix in (".html", ".htm"):
                    ctype = "text/html; charset=utf-8"
                elif file_path.suffix == ".json":
                    ctype = "application/json; charset=utf-8"
            try:
                data = file_path.read_bytes()
            except OSError:
                self._send_text("Not found", status=404)
                return
            # Handle text charset
            if ctype.startswith("text/") and "charset" not in ctype:
                ctype += "; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            # Simple caching for static assets
            if file_path.suffix in (".js", ".css", ".png", ".jpg", ".svg", ".woff2"):
                self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self.wfile.write(data)

    return MatrixHandler


# ---------------------------------------------------------------------------
# server lifecycle
# ---------------------------------------------------------------------------


def run_server(
    port: int = _DEFAULT_PORT,
    web_dir: str | Path | None = None,
    dossier_root: str | Path | None = None,
    bind: str = "127.0.0.1",
) -> ThreadingHTTPServer:
    """Create and return a configured :class:`ThreadingHTTPServer` (not yet serving).

    Caller should invoke ``serve_forever()`` or use as context manager.
    """
    wd = _web_root(web_dir)
    dr = _resolve_dossier_root(dossier_root)
    handler = _make_handler(wd, dr)
    server = ThreadingHTTPServer((bind, port), handler)
    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Law-matrix web server")
    parser.add_argument(
        "--port",
        type=int,
        default=_DEFAULT_PORT,
        help=f"Port to listen on (default: {_DEFAULT_PORT})",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host (default: 127.0.0.1, use 0.0.0.0 for all)",
    )
    parser.add_argument(
        "--web-root",
        dest="web_root",
        default=None,
        help="Static file directory (default: $WEB_ROOT or ./web)",
    )
    parser.add_argument(
        "--dossier-root",
        dest="dossier_root",
        default=None,
        help="Dossier root (default: $DOSSIER_ROOT or data/dossiers)",
    )
    args = parser.parse_args(argv)

    wd = _web_root(args.web_root)
    dr = _resolve_dossier_root(args.dossier_root)

    print("Law-matrix server")
    print(f"  web root:     {wd} {'(exists)' if wd.is_dir() else '(not found — API only)'}")
    dr_display = dr if dr is not None else Path(os.environ.get("DOSSIER_ROOT", "data/dossiers"))
    print(f"  dossier root: {dr_display}")
    print(f"  listening:    http://{args.host}:{args.port}")
    print("  endpoints:    /api/matrix  /api/laws  /api/runs")
    print(f"  static:       /  -> {wd}/index.html")
    print()

    handler = _make_handler(wd, dr)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
