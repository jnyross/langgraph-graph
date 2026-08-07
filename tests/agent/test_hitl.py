"""HITL interrupt schema + resume behaviour for the agent graph."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langgraph.types import Command

from langgraph_graph.hitl import (
    build_hitl_request,
    request_text_from_messages,
    resolve_hitl_decision,
)


def test_build_hitl_request_matches_agent_chat_ui_schema() -> None:
    payload = build_hitl_request(
        tool_name="send_message",
        tool_args={"to": "me", "body": "hello"},
        description="Approve send",
    )
    assert "action_requests" in payload
    assert "review_configs" in payload
    assert payload["action_requests"][0]["name"] == "send_message"
    assert payload["action_requests"][0]["args"] == {"to": "me", "body": "hello"}
    assert payload["review_configs"][0]["action_name"] == "send_message"
    assert set(payload["review_configs"][0]["allowed_decisions"]) == {
        "approve",
        "edit",
        "reject",
    }


@pytest.mark.parametrize(
    ("resume", "granted", "tool", "args"),
    [
        ({"decisions": [{"type": "approve"}]}, True, "send_message", {"to": "me"}),
        (True, True, "send_message", {"to": "me"}),
        (
            {
                "decisions": [
                    {
                        "type": "edit",
                        "edited_action": {
                            "name": "write_record",
                            "args": {"table": "notes", "payload": "x"},
                        },
                    }
                ]
            },
            True,
            "write_record",
            {"table": "notes", "payload": "x"},
        ),
        (
            {"decisions": [{"type": "reject", "message": "Nope"}]},
            False,
            "send_message",
            {"to": "me"},
        ),
        (False, False, "send_message", {"to": "me"}),
    ],
)
def test_resolve_hitl_decision(resume: Any, granted: bool, tool: str, args: dict[str, Any]) -> None:
    ok, name, resolved_args, _msg = resolve_hitl_decision(
        resume,
        default_tool="send_message",
        default_args={"to": "me"},
    )
    assert ok is granted
    assert name == tool
    assert resolved_args == args


def test_request_text_from_messages() -> None:
    assert (
        request_text_from_messages(
            [
                {"role": "assistant", "content": "hi"},
                {"role": "user", "content": "do the thing"},
            ]
        )
        == "do the thing"
    )
    assert (
        request_text_from_messages(
            [
                {
                    "type": "human",
                    "content": [{"type": "text", "text": "Remind me to buy milk"}],
                }
            ]
        )
        == "Remind me to buy milk"
    )


def test_request_text_from_agent_chat_ui_blocks() -> None:
    assert (
        request_text_from_messages(
            [
                {"role": "assistant", "content": "hi"},
                {
                    "type": "human",
                    "content": [
                        {"type": "text", "text": "do"},
                        {"type": "text", "text": "the thing"},
                    ],
                },
            ]
        )
        == "do the thing"
    )


def test_act_node_interrupts_with_hitl_request_and_resumes() -> None:
    from langgraph_graph.graph import build_graph

    fake_llm = MagicMock()
    fake_llm.invoke.return_value = MagicMock(content="- step one\n- step two")

    with patch("langgraph_graph.graph._llm", return_value=fake_llm):
        graph = build_graph()
        config = {"configurable": {"thread_id": "hitl-test-1"}}
        result = graph.invoke(
            {
                "input": "Send me a reminder",
                "messages": [{"role": "user", "content": "Send me a reminder"}],
            },
            config=config,
        )

    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["action_requests"][0]["name"] == "send_message"
    assert "review_configs" in payload

    with patch("langgraph_graph.graph._llm", return_value=fake_llm):
        final = graph.invoke(
            Command(resume={"decisions": [{"type": "approve"}]}),
            config=config,
        )

    assert final["approvals"].get("act-1") is True
    assert "[stub] message sent" in final["output"]


def test_act_node_reject_skips_tool() -> None:
    from langgraph_graph.graph import build_graph

    fake_llm = MagicMock()
    fake_llm.invoke.return_value = MagicMock(content="plan")

    with patch("langgraph_graph.graph._llm", return_value=fake_llm):
        graph = build_graph()
        config = {"configurable": {"thread_id": "hitl-test-2"}}
        graph.invoke(
            {
                "messages": [{"role": "user", "content": "Ping me"}],
            },
            config=config,
        )
        final = graph.invoke(
            Command(resume={"decisions": [{"type": "reject", "message": "Not now"}]}),
            config=config,
        )

    assert final["approvals"].get("act-1") is False
    assert final["output"] == "Not now"


def test_follow_up_messages_override_persisted_input() -> None:
    from langgraph_graph.graph import build_graph

    fake_llm = MagicMock()

    def invoke(prompt: str) -> MagicMock:
        if "Second request" in prompt:
            return MagicMock(content="second plan")
        if "First request" in prompt:
            return MagicMock(content="first plan")
        raise AssertionError(f"Unexpected prompt: {prompt}")

    fake_llm.invoke.side_effect = invoke

    with patch("langgraph_graph.graph._llm", return_value=fake_llm):
        graph = build_graph()
        config = {"configurable": {"thread_id": "hitl-test-3"}}
        graph.invoke(
            {
                "messages": [{"role": "user", "content": "First request"}],
            },
            config=config,
        )
        graph.invoke(
            Command(resume={"decisions": [{"type": "approve"}]}),
            config=config,
        )
        result = graph.invoke(
            {
                "messages": [{"role": "user", "content": "Second request"}],
            },
            config=config,
        )

    payload = result["__interrupt__"][0].value
    assert payload["action_requests"][0]["args"]["body"] == "second plan"
