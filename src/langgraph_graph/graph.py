"""Graph definition: the heart of the project.

Nodes:
    plan   — turn the user request into a short plan
    act    — propose an action and HITL-interrupt before executing it
    reply  — summarise for the user

The `act` node uses LangGraph's `interrupt()` to pause for human approval before
any tool with an external side effect runs. The interrupt payload uses the
Agent Chat UI / Agent Inbox HITLRequest schema so Studio and the chat UI both
render approve / edit / reject controls.
"""

from __future__ import annotations

import os
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from langgraph_graph.hitl import (
    build_hitl_request,
    request_text_from_messages,
    resolve_hitl_decision,
)
from langgraph_graph.state import AgentState
from langgraph_graph.tools import ALL_TOOLS


def _llm():
    """Lazily build a chat model from env config (OpenAI-compatible)."""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=os.environ.get("MODEL", "ollama/chatgpt-oss:latest"),
        base_url=os.environ.get("BASE_URL", "http://localhost:11434/v1"),
        api_key=os.environ.get("API_KEY", "ollama"),
    )


def _user_request(state: AgentState) -> str:
    """Resolve the user request from the latest chat message or `input` fallback."""
    request = request_text_from_messages(state.messages)
    if request:
        return request
    return state.input.strip()


def plan_node(state: AgentState) -> dict[str, Any]:
    """Produce a short plan from the user's input."""
    request = _user_request(state)
    prompt = (
        "Break this request into 1-3 concise steps. "
        "Return plain lines, no numbering.\n\n"
        f"Request: {request}"
    )
    try:
        raw = str(_llm().invoke(prompt).content)
    except Exception as exc:
        # Keep HITL demos usable when the local model endpoint is down.
        raw = f"Handle request: {request}\n(note: planner fallback; model unavailable: {exc})"
    steps = [line.strip("- ").strip() for line in str(raw).splitlines() if line.strip()]
    messages = list(state.messages)
    if not messages and request:
        messages = [{"role": "user", "content": request}]
    return {
        "input": request,
        "plan": steps,
        "messages": messages + [{"role": "assistant", "content": str(raw)}],
    }


def act_node(state: AgentState) -> dict[str, Any]:
    """Propose an action and pause for human approval before executing it.

    Interrupt payload matches Agent Chat UI's HITLRequest schema. On resume,
    Agent Chat UI sends ``{"decisions": [{"type": "approve"|"edit"|"reject", ...}]}``.
    Boolean resume values remain supported for CLI / Studio convenience.
    """
    plan_summary = "; ".join(state.plan) or _user_request(state)
    tool_name = "send_message"
    tool_args: dict[str, Any] = {"to": "me", "body": plan_summary}
    action_id = "act-1"

    hitl_request = build_hitl_request(
        tool_name=tool_name,
        tool_args=tool_args,
        description=(
            "Approve this external side effect before it runs.\n\n"
            f"Tool: {tool_name}\n"
            f"Args: {tool_args}"
        ),
        allowed_decisions=["approve", "edit", "reject"],
    )

    # interrupt() returns whatever the human supplies at resume time.
    decision = interrupt(hitl_request)

    granted, resolved_tool, resolved_args, reject_message = resolve_hitl_decision(
        decision,
        default_tool=tool_name,
        default_args=tool_args,
    )
    approvals: dict[str, bool] = {**state.approvals, action_id: granted}
    output = ""
    if granted:
        tool = next((t for t in ALL_TOOLS if t.name == resolved_tool), None)
        if tool is not None:
            output = tool.invoke(resolved_args)  # type: ignore[arg-type]
        else:
            output = f"Unknown tool {resolved_tool!r}; nothing executed."
    else:
        output = reject_message or "Action rejected by human; nothing executed."
    return {"approvals": approvals, "pending_action": None, "output": output}


def reply_node(state: AgentState) -> dict[str, Any]:
    """Final user-facing summary."""
    text = state.output or "(no action taken)"
    return {"output": text, "messages": state.messages + [{"role": "assistant", "content": text}]}


def _assemble_graph() -> StateGraph:
    """Build the StateGraph topology (nodes/edges only; not compiled)."""
    g = StateGraph(AgentState)
    g.add_node("plan", plan_node)
    g.add_node("act", act_node)
    g.add_node("reply", reply_node)

    g.add_edge(START, "plan")
    g.add_edge("plan", "act")
    g.add_edge("act", "reply")
    g.add_edge("reply", END)
    return g


def build_graph(checkpointer: Any = None):
    """Compile the graph for local CLI / scripts.

    Defaults to MemorySaver when checkpointer is None. Pass an explicit
    checkpointer to use it, or checkpointer=False to compile with none.
    """
    if checkpointer is None:
        checkpointer = MemorySaver()
    elif checkpointer is False:
        checkpointer = None
    return _assemble_graph().compile(checkpointer=checkpointer)


# LangSmith Studio / `langgraph dev` entry — Agent Server injects a checkpointer.
graph = _assemble_graph().compile()
