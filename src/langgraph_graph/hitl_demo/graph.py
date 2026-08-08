"""Deterministic HITL demo: confirm → choice → text → approve.

No LLM calls. Designed for the minimal HITL UI (`apps/hitl-ui`) and Codex
browser workflows. Studio / ``langgraph dev`` export is the module-level
``graph`` (no custom checkpointer). Scripts use ``build_graph()``.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from langgraph_graph.hitl import (
    build_approve_prompt,
    build_choice_prompt,
    build_confirm_prompt,
    build_text_prompt,
    resolve_approve_prompt,
    resolve_choice,
    resolve_confirm,
    resolve_text,
)
from langgraph_graph.hitl_demo.state import HitlDemoState


def ask_confirm(state: HitlDemoState) -> dict[str, Any]:
    """Ask the human to confirm they want to continue the demo."""
    prompt = build_confirm_prompt(
        title="Continue demo?",
        prompt="This run walks through confirm, choice, free text, and approve.",
        yes_label="Continue",
        no_label="Stop",
    )
    resume = interrupt(prompt)
    confirmed = resolve_confirm(resume)
    answers = {**state.answers, "confirm": confirmed}
    return {"answers": answers}


def ask_choice(state: HitlDemoState) -> dict[str, Any]:
    """Skip remaining prompts if the human declined the confirm step."""
    if not state.answers.get("confirm"):
        return {
            "output": "Demo stopped at confirm.",
            "answers": state.answers,
        }

    prompt = build_choice_prompt(
        title="Pick a region",
        prompt="Which region should the demo pretend to research?",
        options=[
            {"id": "eu", "label": "European Union"},
            {"id": "us", "label": "United States"},
            {"id": "apac", "label": "Asia-Pacific"},
        ],
    )
    resume = interrupt(prompt)
    choice = resolve_choice(resume)
    answers = {**state.answers, "choice": choice}
    return {"answers": answers}


def ask_text(state: HitlDemoState) -> dict[str, Any]:
    if not state.answers.get("confirm"):
        return {}

    prompt = build_text_prompt(
        title="Subject note",
        prompt="Add a short note about what to focus on.",
        placeholder="e.g. youth safety enforcement",
        multiline=True,
    )
    resume = interrupt(prompt)
    text = resolve_text(resume).strip()
    answers = {**state.answers, "text": text}
    return {"answers": answers}


def ask_approve(state: HitlDemoState) -> dict[str, Any]:
    if not state.answers.get("confirm"):
        return {}

    region = state.answers.get("choice", "unknown")
    note = state.answers.get("text") or "(no note)"
    tool_name = "send_message"
    tool_args: dict[str, Any] = {
        "to": "demo",
        "body": f"Region={region}; note={note}",
    }
    prompt = build_approve_prompt(
        title="Approve side effect",
        prompt="Approve this stub external send before it 'runs'.",
        tool_name=tool_name,
        tool_args=tool_args,
        allowed_decisions=["approve", "edit", "reject"],
    )
    resume = interrupt(prompt)
    granted, resolved_tool, resolved_args, reject_message = resolve_approve_prompt(
        resume,
        default_tool=tool_name,
        default_args=tool_args,
    )
    answers = {
        **state.answers,
        "approve": {
            "granted": granted,
            "tool": resolved_tool,
            "args": resolved_args,
            "reject_message": reject_message,
        },
    }
    return {"answers": answers}


def summarize(state: HitlDemoState) -> dict[str, Any]:
    """Produce a short final summary for the UI."""
    if not state.answers.get("confirm"):
        output = state.output or "Demo stopped at confirm."
        return {"output": output}

    approve = state.answers.get("approve") or {}
    if approve.get("granted"):
        action = f"{approve.get('tool')}({approve.get('args')})"
        status = f"approved → {action}"
    else:
        status = f"rejected → {approve.get('reject_message') or 'no reason'}"

    lines = [
        "HITL demo complete.",
        f"confirm: {state.answers.get('confirm')}",
        f"choice: {state.answers.get('choice')}",
        f"text: {state.answers.get('text')}",
        f"approve: {status}",
    ]
    output = "\n".join(lines)
    messages = list(state.messages)
    if not messages:
        messages = [{"role": "user", "content": state.input or "demo"}]
    messages = messages + [{"role": "assistant", "content": output}]
    return {"output": output, "messages": messages}


def _route_after_confirm(state: HitlDemoState) -> str:
    if state.answers.get("confirm"):
        return "ask_choice"
    return "summarize"


def _assemble_graph() -> StateGraph:
    g = StateGraph(HitlDemoState)
    g.add_node("ask_confirm", ask_confirm)
    g.add_node("ask_choice", ask_choice)
    g.add_node("ask_text", ask_text)
    g.add_node("ask_approve", ask_approve)
    g.add_node("summarize", summarize)

    g.add_edge(START, "ask_confirm")
    g.add_conditional_edges(
        "ask_confirm",
        _route_after_confirm,
        {"ask_choice": "ask_choice", "summarize": "summarize"},
    )
    g.add_edge("ask_choice", "ask_text")
    g.add_edge("ask_text", "ask_approve")
    g.add_edge("ask_approve", "summarize")
    g.add_edge("summarize", END)
    return g


def build_graph(checkpointer: Any = None):
    """Compile for local scripts/tests (MemorySaver by default)."""
    if checkpointer is None:
        checkpointer = MemorySaver()
    elif checkpointer is False:
        checkpointer = None
    return _assemble_graph().compile(checkpointer=checkpointer)


# LangSmith Studio / ``langgraph dev`` entry — Agent Server injects a checkpointer.
graph = _assemble_graph().compile()
