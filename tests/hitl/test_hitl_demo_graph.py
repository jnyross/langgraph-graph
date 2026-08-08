"""End-to-end smoke for the hitl_demo graph."""

from __future__ import annotations

from langgraph.types import Command

from langgraph_graph.hitl_demo import build_graph


def test_hitl_demo_happy_path() -> None:
    graph = build_graph()
    config = {"configurable": {"thread_id": "hitl-demo-1"}}

    state = graph.invoke({"input": "demo"}, config=config)
    assert "__interrupt__" in state
    assert state["__interrupt__"][0].value["kind"] == "confirm"

    state = graph.invoke(Command(resume={"kind": "confirm", "value": True}), config=config)
    assert state["__interrupt__"][0].value["kind"] == "choice"

    state = graph.invoke(Command(resume={"kind": "choice", "value": "eu"}), config=config)
    assert state["__interrupt__"][0].value["kind"] == "text"

    state = graph.invoke(
        Command(resume={"kind": "text", "value": "youth safety"}),
        config=config,
    )
    assert state["__interrupt__"][0].value["kind"] == "approve"

    final = graph.invoke(
        Command(resume={"kind": "approve", "decision": {"type": "approve"}}),
        config=config,
    )
    assert "__interrupt__" not in final
    assert final["answers"]["confirm"] is True
    assert final["answers"]["choice"] == "eu"
    assert final["answers"]["text"] == "youth safety"
    assert final["answers"]["approve"]["granted"] is True
    assert "HITL demo complete" in final["output"]


def test_hitl_demo_stop_on_confirm_false() -> None:
    graph = build_graph()
    config = {"configurable": {"thread_id": "hitl-demo-2"}}

    graph.invoke({"input": "demo"}, config=config)
    final = graph.invoke(
        Command(resume={"kind": "confirm", "value": False}),
        config=config,
    )
    assert "__interrupt__" not in final
    assert final["answers"]["confirm"] is False
    assert "stopped" in final["output"].lower()


def test_hitl_demo_rerun_clears_stale_output_on_confirm_false() -> None:
    graph = build_graph()
    config = {"configurable": {"thread_id": "hitl-demo-rerun"}}

    graph.invoke({"input": "demo"}, config=config)
    graph.invoke(Command(resume={"kind": "confirm", "value": True}), config=config)
    graph.invoke(Command(resume={"kind": "choice", "value": "eu"}), config=config)
    graph.invoke(Command(resume={"kind": "text", "value": "youth safety"}), config=config)
    final = graph.invoke(
        Command(resume={"kind": "approve", "decision": {"type": "approve"}}),
        config=config,
    )
    assert "HITL demo complete" in final["output"]

    rerun = graph.invoke({"input": "demo"}, config=config)
    assert rerun["__interrupt__"][0].value["kind"] == "confirm"

    stopped = graph.invoke(
        Command(resume={"kind": "confirm", "value": False}),
        config=config,
    )
    assert stopped["output"] == "Demo stopped at confirm."


def test_studio_graph_export_has_no_checkpointer() -> None:
    from langgraph_graph.hitl_demo.graph import graph

    # Studio contract: module-level graph must not attach a custom checkpointer.
    assert graph.checkpointer is None
