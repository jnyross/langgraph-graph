"""HITL helpers for Agent Chat UI / Agent Inbox interrupts.

Agent Chat UI renders interactive approve / edit / reject controls when the
interrupt payload matches the HITLRequest schema:

    {
      "action_requests": [{"name": "...", "args": {...}, "description": "..."}],
      "review_configs": [{"action_name": "...", "allowed_decisions": [...]}],
    }

Resume values arrive as:

    {"decisions": [{"type": "approve"} | {"type": "reject", ...} | {"type": "edit", ...}]}
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

DecisionType = Literal["approve", "edit", "reject"]


class ActionRequest(TypedDict, total=False):
    name: str
    args: dict[str, Any]
    description: str


class ReviewConfig(TypedDict, total=False):
    action_name: str
    allowed_decisions: list[DecisionType]
    args_schema: dict[str, Any]


class HITLRequest(TypedDict):
    action_requests: list[ActionRequest]
    review_configs: list[ReviewConfig]


class EditedAction(TypedDict):
    name: str
    args: dict[str, Any]


class Decision(TypedDict, total=False):
    type: DecisionType
    message: str
    edited_action: EditedAction


def build_hitl_request(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    description: str,
    allowed_decisions: list[DecisionType] | None = None,
) -> HITLRequest:
    """Build an Agent Chat UI–compatible interrupt payload for one tool call."""
    decisions = allowed_decisions or ["approve", "edit", "reject"]
    return {
        "action_requests": [
            {
                "name": tool_name,
                "args": tool_args,
                "description": description,
            }
        ],
        "review_configs": [
            {
                "action_name": tool_name,
                "allowed_decisions": decisions,
            }
        ],
    }


def _first_decision(resume_value: Any) -> Decision | None:
    """Normalize resume payloads from Agent Chat UI, Studio, or CLI."""
    if resume_value is None:
        return None

    # Legacy boolean resume (older CLI / Studio habit).
    if isinstance(resume_value, bool):
        return {"type": "approve" if resume_value else "reject"}

    if isinstance(resume_value, str):
        lowered = resume_value.strip().lower()
        if lowered in {"approve", "accept", "yes", "y", "true", "1"}:
            return {"type": "approve"}
        if lowered in {"reject", "deny", "no", "n", "false", "0", "ignore"}:
            return {"type": "reject"}
        return {"type": "reject", "message": resume_value}

    if isinstance(resume_value, dict):
        decisions = resume_value.get("decisions")
        if isinstance(decisions, list) and decisions:
            first = decisions[0]
            if isinstance(first, dict) and "type" in first:
                return first  # type: ignore[return-value]
        if "type" in resume_value:
            return resume_value  # type: ignore[return-value]

    if isinstance(resume_value, list) and resume_value:
        first = resume_value[0]
        if isinstance(first, dict) and "type" in first:
            return first  # type: ignore[return-value]

    # Truthy/falsey fallback for unexpected shapes.
    return {"type": "approve" if bool(resume_value) else "reject"}


def resolve_hitl_decision(
    resume_value: Any,
    *,
    default_tool: str,
    default_args: dict[str, Any],
) -> tuple[bool, str, dict[str, Any], str | None]:
    """Interpret a resume value into (granted, tool_name, tool_args, reject_message)."""
    decision = _first_decision(resume_value)
    if decision is None:
        return False, default_tool, default_args, "No decision provided."

    dtype = str(decision.get("type", "")).lower()
    if dtype in {"approve", "accept"}:
        return True, default_tool, default_args, None

    if dtype == "edit":
        edited = decision.get("edited_action") or {}
        name = str(edited.get("name") or default_tool)
        args = edited.get("args")
        if not isinstance(args, dict):
            args = default_args
        return True, name, args, None

    message = decision.get("message")
    if isinstance(message, str) and message.strip():
        return False, default_tool, default_args, message.strip()
    return False, default_tool, default_args, "Action rejected by human; nothing executed."


def _content_to_text(content: Any) -> str:
    """Normalize Agent Chat UI / LangChain message content into plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts: list[str] = []
        for block in content:
            if isinstance(block, str):
                if block.strip():
                    texts.append(block.strip())
                continue
            if isinstance(block, dict):
                block_type = block.get("type")
                text = block.get("text")
            else:
                block_type = getattr(block, "type", None)
                text = getattr(block, "text", None)
            if isinstance(text, str) and text.strip():
                if block_type in {None, "text", "input_text"}:
                    texts.append(text.strip())
        return " ".join(texts).strip()
    # LangChain / SDK content-block objects sometimes appear as a single block.
    text = getattr(content, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    return str(content).strip()


def request_text_from_messages(messages: list[Any], fallback: str = "") -> str:
    """Best-effort user text from OpenAI-style message dicts (Agent Chat UI input)."""
    for message in reversed(messages or []):
        if isinstance(message, dict):
            role = message.get("role") or message.get("type")
            text = _content_to_text(message.get("content"))
            if role in {"user", "human"} and text:
                return text
        else:
            # LangChain message objects, if they slip through.
            role = getattr(message, "type", None) or getattr(message, "role", None)
            text = _content_to_text(getattr(message, "content", None))
            if role in {"human", "user"} and text:
                return text
    return fallback
