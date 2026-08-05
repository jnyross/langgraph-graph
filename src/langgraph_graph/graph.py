"""Graph definition: the heart of the project.

Nodes:
    plan   — turn the user request into a short plan
    act    — propose an action and HITL-interrupt before executing it
    reply  — summarise for the user

The `act` node uses LangGraph's `interrupt()` to pause for human approval before
any tool with an external side effect runs. This is the project's HITL policy.
"""

from __future__ import annotations

import os
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

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


def plan_node(state: AgentState) -> dict[str, Any]:
    """Produce a short plan from the user's input."""
    llm = _llm()
    prompt = (
        "Break this request into 1-3 concise steps. "
        "Return plain lines, no numbering.\n\n"
        f"Request: {state.input}"
    )
    raw = llm.invoke(prompt).content
    steps = [line.strip("- ").strip() for line in str(raw).splitlines() if line.strip()]
    return {"plan": steps, "messages": state.messages + [{"role": "assistant", "content": str(raw)}]}


def act_node(state: AgentState) -> dict[str, Any]:
    """Propose an action and pause for human approval before executing it.

    The first time we reach this node for a given action, we set
    `pending_action` and `interrupt()`. LangGraph resumes here with the human's
    decision; approved actions execute the bound tool, rejected ones are skipped.
    """
    plan_summary = "; ".join(state.plan) or state.input
    action = {"id": "act-1", "tool": "send_message", "args": {"to": "me", "body": plan_summary}}

    # interrupt() returns whatever the human supplies at resume time.
    decision = interrupt(
        {
            "prompt": "Approve this action?",
            "action": action,
        }
    )

    granted = bool(decision) if decision is not None else False
    approvals = {**state.approvals, action["id"]: granted}
    output = ""
    if granted:
        tool = next((t for t in ALL_TOOLS if t.name == action["tool"]), None)
        if tool is not None:
            output = tool.invoke(action["args"])
    else:
        output = "Action rejected by human; nothing executed."
    return {"approvals": approvals, "pending_action": None, "output": output}


def reply_node(state: AgentState) -> dict[str, Any]:
    """Final user-facing summary."""
    text = state.output or "(no action taken)"
    return {"output": text, "messages": state.messages + [{"role": "assistant", "content": text}]}


def build_graph():
    """Compile the graph with an in-memory checkpointer.

    Swap MemorySaver for SqliteSaver/PostgresSaver for durable runs.
    """
    g = StateGraph(AgentState)
    g.add_node("plan", plan_node)
    g.add_node("act", act_node)
    g.add_node("reply", reply_node)

    g.add_edge(START, "plan")
    g.add_edge("plan", "act")
    g.add_edge("act", "reply")
    g.add_edge("reply", END)

    return g.compile(checkpointer=MemorySaver())
