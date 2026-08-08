"""State for the hitl_demo graph."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HitlDemoState(BaseModel):
    """Collects answers from successive HITL prompts."""

    input: str = Field(default="demo", description="Optional run label.")
    answers: dict[str, Any] = Field(
        default_factory=dict,
        description="Keyed answers from each HITL step.",
    )
    output: str = Field(default="", description="Final summary for the UI.")
    messages: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Optional OpenAI-style messages for SDK clients.",
    )

    model_config = {"arbitrary_types_allowed": True}
