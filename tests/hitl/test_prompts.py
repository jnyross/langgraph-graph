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
        ({"kind": "confirm", "value": "false"}, False),
        ({"kind": "text", "value": "no"}, False),
        ({"kind": "text", "value": True}, False),
        ({"kind": "choice", "value": True}, False),
        ({"value": True}, True),
        ({"type": "approve"}, True),
        ({"decisions": [{"type": "approve"}]}, True),
        ({"decisions": [{"type": "reject"}]}, False),
        (True, True),
        ("yes", True),
        ("approve", True),
        ("no", False),
    ],
)
def test_resolve_confirm(resume: object, expected: bool) -> None:
    assert resolve_confirm(resume) is expected


def test_resolve_choice_single_and_multi() -> None:
    assert resolve_choice({"kind": "choice", "value": "eu"}) == "eu"
    assert resolve_choice({"kind": "choice", "value": ["eu", "us"]}) == ["eu", "us"]
    assert resolve_choice("apac") == "apac"
    assert resolve_choice({"kind": "confirm", "value": True}) == ""
    assert resolve_choice({"kind": "approve", "decision": {"type": "reject"}}) == ""
    assert resolve_choice({"unknown": "dict"}) == ""


def test_resolve_text() -> None:
    assert resolve_text({"kind": "text", "value": "hello"}) == "hello"
    assert resolve_text("plain") == "plain"
    assert resolve_text(None) == ""
    assert resolve_text({"kind": "confirm", "value": "yes"}) == ""
    assert resolve_text({"kind": "choice", "value": "eu"}) == ""
    assert resolve_text({"unknown": "dict"}) == ""


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

    granted, _, _, msg = resolve_approve_prompt(
        {"decisions": []},
        default_tool="send_message",
        default_args={"to": "me"},
    )
    assert granted is False
    assert msg == "No decision provided."

    granted, _, _, msg = resolve_approve_prompt(
        ["reject"],
        default_tool="send_message",
        default_args={"to": "me"},
    )
    assert granted is False
    assert msg == "No decision provided."


def test_schema_detectors() -> None:
    assert is_hitl_prompt(build_confirm_prompt(title="t", prompt="p"))
    assert not is_hitl_prompt({"action_requests": []})
    assert is_agent_inbox_request(
        {
            "action_requests": [{"name": "x", "args": {}}],
            "review_configs": [{"action_name": "x", "allowed_decisions": ["approve"]}],
        }
    )


def test_resolve_approve_rejects_other_prompt_kinds() -> None:
    for kind in ("confirm", "choice", "text"):
        granted, _, _, msg = resolve_approve_prompt(
            {"kind": kind, "value": True},
            default_tool="send_message",
            default_args={},
        )
        assert granted is False
        assert msg == "No decision provided."
