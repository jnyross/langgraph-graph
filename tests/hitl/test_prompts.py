"""Tagged HITLPrompt builders and resume resolvers."""

from __future__ import annotations

import pytest

from langgraph_graph.hitl import (
    build_approve_prompt,
    build_choice_prompt,
    build_confirm_prompt,
    build_text_prompt,
    is_agent_inbox_request,
    is_hitl_prompt,
    resolve_approve_prompt,
    resolve_choice,
    resolve_confirm,
    resolve_text,
)


def test_build_confirm_prompt() -> None:
    prompt = build_confirm_prompt(title="Go?", prompt="Continue the run?")
    assert prompt["kind"] == "confirm"
    assert prompt["yes_label"] == "Yes"
    assert is_hitl_prompt(prompt)


def test_build_choice_prompt() -> None:
    prompt = build_choice_prompt(
        title="Region",
        prompt="Pick one",
        options=[{"id": "eu", "label": "EU"}, {"id": "us", "label": "US"}],
    )
    assert prompt["kind"] == "choice"
    assert prompt["options"][0]["id"] == "eu"
    assert prompt["allow_multiple"] is False


def test_build_multi_choice_prompt() -> None:
    prompt = build_choice_prompt(
        title="Domains",
        prompt="Pick many",
        options=[{"id": "privacy", "label": "Privacy"}],
        allow_multiple=True,
    )
    assert prompt["allow_multiple"] is True
    assert resolve_choice({"kind": "choice", "value": ["privacy", "ip"]}) == [
        "privacy",
        "ip",
    ]


def test_build_text_prompt() -> None:
    prompt = build_text_prompt(title="Note", prompt="Add detail", placeholder="…")
    assert prompt["kind"] == "text"
    assert prompt["multiline"] is True


def test_build_approve_prompt() -> None:
    prompt = build_approve_prompt(
        title="Send?",
        prompt="Approve send",
        tool_name="send_message",
        tool_args={"to": "me", "body": "hi"},
    )
    assert prompt["kind"] == "approve"
    assert prompt["action"]["name"] == "send_message"
    assert set(prompt["allowed_decisions"]) == {"approve", "edit", "reject"}


@pytest.mark.parametrize(
    ("resume", "expected"),
    [
        ({"kind": "confirm", "value": True}, True),
        ({"kind": "confirm", "value": False}, False),
        (True, True),
        ("yes", True),
        ("no", False),
    ],
)
def test_resolve_confirm(resume: object, expected: bool) -> None:
    assert resolve_confirm(resume) is expected


def test_resolve_choice_single_and_multi() -> None:
    assert resolve_choice({"kind": "choice", "value": "eu"}) == "eu"
    assert resolve_choice({"kind": "choice", "value": ["eu", "us"]}) == ["eu", "us"]
    assert resolve_choice("apac") == "apac"


def test_resolve_text() -> None:
    assert resolve_text({"kind": "text", "value": "hello"}) == "hello"
    assert resolve_text("plain") == "plain"
    assert resolve_text(None) == ""


def test_resolve_approve_tagged_and_legacy() -> None:
    granted, tool, args, msg = resolve_approve_prompt(
        {"kind": "approve", "decision": {"type": "approve"}},
        default_tool="send_message",
        default_args={"to": "me"},
    )
    assert granted is True
    assert tool == "send_message"
    assert args == {"to": "me"}
    assert msg is None

    granted, tool, args, msg = resolve_approve_prompt(
        {
            "kind": "approve",
            "decision": {
                "type": "edit",
                "edited_action": {
                    "name": "send_message",
                    "args": {"to": "you", "body": "edited"},
                },
            },
        },
        default_tool="send_message",
        default_args={"to": "me"},
    )
    assert granted is True
    assert args == {"to": "you", "body": "edited"}

    granted, _, _, msg = resolve_approve_prompt(
        {"decisions": [{"type": "reject", "message": "Nope"}]},
        default_tool="send_message",
        default_args={"to": "me"},
    )
    assert granted is False
    assert msg == "Nope"


def test_schema_detectors() -> None:
    assert is_hitl_prompt(build_confirm_prompt(title="t", prompt="p"))
    assert not is_hitl_prompt({"action_requests": []})
    assert is_agent_inbox_request(
        {
            "action_requests": [{"name": "x", "args": {}}],
            "review_configs": [{"action_name": "x", "allowed_decisions": ["approve"]}],
        }
    )
