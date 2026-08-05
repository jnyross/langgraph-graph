"""Shared daemon ThreadPoolExecutor for meta_legal workers.

Workers are daemons so a hung network/LLM call cannot pin process exit.
Both search and research_cell previously duplicated this class; it now lives
here and is re-exported via ``tools._pool`` for single-source maintenance.
"""

from __future__ import annotations

import contextlib
from concurrent.futures import ThreadPoolExecutor


class DaemonThreadPoolExecutor(ThreadPoolExecutor):
    """ThreadPoolExecutor whose workers are daemons (safe process exit on hang)."""

    def _adjust_thread_count(self) -> None:  # type: ignore[override]
        super()._adjust_thread_count()
        for t in list(getattr(self, "_threads", ())):
            with contextlib.suppress(Exception):
                t.daemon = True


__all__ = ["DaemonThreadPoolExecutor"]
