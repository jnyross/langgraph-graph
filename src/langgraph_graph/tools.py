"""Tool registry.

Tools here are the ONLY place external side effects happen. Each tool is wrapped
by the HITL node in `graph.py` so nothing fires without an approved interrupt.

Add new tools following the `@tool` pattern below. Keep them small and typed.
"""

from __future__ import annotations

from langchain_core.tools import tool


@tool
def send_message(to: str, body: str) -> str:
    """Send a message to a recipient. External side effect — requires HITL."""
    # TODO: wire to real channel (Telegram/iMessage/email).
    return f"[stub] message sent to {to}: {body!r}"


@tool
def write_record(table: str, payload: str) -> str:
    """Write a record to a data store. Production write — requires HITL."""
    # TODO: wire to real store.
    return f"[stub] wrote to {table}: {payload!r}"


ALL_TOOLS = [send_message, write_record]
