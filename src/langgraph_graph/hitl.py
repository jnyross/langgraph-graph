"""HITL helpers for Agent Chat UI / Agent Inbox and the minimal HITL UI.

Two interrupt contracts coexist:

1. **Agent Inbox / HITLRequest** (existing ``agent`` graph + Agent Chat UI)::

    {
      "action_requests": [{"name": "...", "args": {...}, "description": "..."}],
      "review_configs": [{"action_name": "...", "allowed_decisions": [...]}],
    }

   Resume::

    {"decisions": [{"type": "approve"|"edit"|"reject", ...}]}

2. **Tagged HITLPrompt** (minimal HITL UI + ``hitl_demo`` graph)::

    {"kind": "confirm"|"choice"|"text"|"approve", "title": "...", "prompt": "...", ...}

   Resume::

    {"kind": "confirm", "value": true|false}
    {"kind": "choice", "value": "<id>" | ["<id>", ...]}
    {"kind": "text", "value": "<string>"}
    {"kind": "approve", "decision": {"type": "approve"|"edit"|"reject", ...}}
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict, cast

DecisionType = Literal["approve", "edit", "reject"]
PromptKind = Literal["confirm", "choice", "text", "approve"]


# ---------------------------------------------------------------------------
# Agent Inbox (HITLRequest) — used by Agent Chat UI
# ---------------------------------------------------------------------------


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
    """Normalize resume payloads from Agent Chat UI, Studio, CLI, or HITL UI."""
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
        # Tagged approve resume from the minimal HITL UI.
        if resume_value.get("kind") == "approve":
            nested = resume_value.get("decision")
            if isinstance(nested, dict) and "type" in nested:
                return cast(Decision, nested)
            decisions = resume_value.get("decisions")
            if isinstance(decisions, list) and decisions:
                first = decisions[0]
                if isinstance(first, dict) and "type" in first:
                    return cast(Decision, first)

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


# ---------------------------------------------------------------------------
# Tagged HITLPrompt — used by apps/hitl-ui and hitl_demo
# ---------------------------------------------------------------------------


class ChoiceOption(TypedDict):
    id: str
    label: str


class ApproveAction(TypedDict, total=False):
    name: str
    args: dict[str, Any]


class HITLPrompt(TypedDict, total=False):
    """Tagged interrupt payload for the minimal HITL UI."""

    kind: PromptKind
    title: str
    prompt: str
    # confirm
    yes_label: str
    no_label: str
    # choice
    options: list[ChoiceOption]
    allow_multiple: bool
    # text
    placeholder: str
    multiline: bool
    # approve
    action: ApproveAction
    allowed_decisions: list[DecisionType]


def build_confirm_prompt(
    *,
    title: str,
    prompt: str,
    yes_label: str = "Yes",
    no_label: str = "No",
) -> HITLPrompt:
    return {
        "kind": "confirm",
        "title": title,
        "prompt": prompt,
        "yes_label": yes_label,
        "no_label": no_label,
    }


def build_choice_prompt(
    *,
    title: str,
    prompt: str,
    options: list[ChoiceOption] | list[dict[str, str]],
    allow_multiple: bool = False,
) -> HITLPrompt:
    normalized: list[ChoiceOption] = []
    for opt in options:
        normalized.append({"id": str(opt["id"]), "label": str(opt["label"])})
    return {
        "kind": "choice",
        "title": title,
        "prompt": prompt,
        "options": normalized,
        "allow_multiple": allow_multiple,
    }


def build_text_prompt(
    *,
    title: str,
    prompt: str,
    placeholder: str = "",
    multiline: bool = True,
) -> HITLPrompt:
    return {
        "kind": "text",
        "title": title,
        "prompt": prompt,
        "placeholder": placeholder,
        "multiline": multiline,
    }


def build_approve_prompt(
    *,
    title: str,
    prompt: str,
    tool_name: str,
    tool_args: dict[str, Any],
    allowed_decisions: list[DecisionType] | None = None,
) -> HITLPrompt:
    return {
        "kind": "approve",
        "title": title,
        "prompt": prompt,
        "action": {"name": tool_name, "args": tool_args},
        "allowed_decisions": allowed_decisions or ["approve", "edit", "reject"],
    }


def is_hitl_prompt(value: Any) -> bool:
    """True when ``value`` looks like a tagged HITLPrompt."""
    return (
        isinstance(value, dict)
        and value.get("kind") in {"confirm", "choice", "text", "approve"}
        and isinstance(value.get("title"), str)
    )


def is_agent_inbox_request(value: Any) -> bool:
    """True when ``value`` matches the Agent Inbox HITLRequest shape."""
    if not isinstance(value, dict):
        return False
    actions = value.get("action_requests")
    configs = value.get("review_configs")
    return isinstance(actions, list) and bool(actions) and isinstance(configs, list) and bool(configs)


def resolve_confirm(resume_value: Any) -> bool:
    """Return the boolean answer from a confirm resume payload."""
    if isinstance(resume_value, bool):
        return resume_value
    if isinstance(resume_value, dict):
        if resume_value.get("kind") == "confirm":
            return bool(resume_value.get("value"))
        if "value" in resume_value and isinstance(resume_value["value"], bool):
            return resume_value["value"]
    if isinstance(resume_value, str):
        return resume_value.strip().lower() in {"yes", "y", "true", "1", "confirm", "ok"}
    return bool(resume_value)


def resolve_choice(resume_value: Any) -> str | list[str]:
    """Return the selected option id(s) from a choice resume payload."""
    if isinstance(resume_value, dict) and "value" in resume_value:
        value = resume_value["value"]
        if isinstance(value, list):
            return [str(v) for v in value]
        return str(value)
    if isinstance(resume_value, list):
        return [str(v) for v in resume_value]
    if isinstance(resume_value, str):
        return resume_value
    raise ValueError(f"Invalid choice resume value: {resume_value!r}")


def resolve_text(resume_value: Any) -> str:
    """Return the free-text answer from a text resume payload."""
    if isinstance(resume_value, dict) and "value" in resume_value:
        return str(resume_value["value"] if resume_value["value"] is not None else "")
    if isinstance(resume_value, str):
        return resume_value
    if resume_value is None:
        return ""
    return str(resume_value)


def resolve_approve_prompt(
    resume_value: Any,
    *,
    default_tool: str,
    default_args: dict[str, Any],
) -> tuple[bool, str, dict[str, Any], str | None]:
    """Resolve an approve-kind (or legacy Agent Inbox) resume into tool execution."""
    return resolve_hitl_decision(
        resume_value,
        default_tool=default_tool,
        default_args=default_args,
    )


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
