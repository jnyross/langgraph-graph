"""Typed graph state.

Keep this the single source of truth for what flows between nodes. Tools and
nodes read/write fields here; the checkpointer persists it so runs can resume.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentState(BaseModel):
    """State that travels through every node of the graph."""

    input: str = Field(default="", description="The user's original request.")
    messages: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Conversation as OpenAI-style message dicts.",
    )
    plan: list[str] = Field(default_factory=list, description="Planned steps.")
    pending_action: dict[str, Any] | None = Field(
        default=None,
        description="Action awaiting human approval before execution.",
    )
    approvals: dict[str, bool] = Field(
        default_factory=dict,
        description="Per-action approval ledger (action_id -> granted).",
    )
    output: str = Field(default="", description="Final response to the user.")

    model_config = {"arbitrary_types_allowed": True}
