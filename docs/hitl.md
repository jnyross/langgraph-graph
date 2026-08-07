# HITL policy

LangGraph's `interrupt()` is the only approval mechanism in this project.
Prompts are not approvals — an interrupt is a hard pause that yields control
back to a human and resumes only on their input.

## Mandatory interrupts before

| Category | Example | Why |
|----------|---------|-----|
| External send | message, email, webhook | Cannot un-send |
| Spend | paid API call, purchase | Money |
| Production write | DB update, file mutate | State change |
| HR / PII export | exporting personal data | Compliance / privacy |

## UI: Agent Chat UI

Primary interactive surface for HITL is **Agent Chat UI**
(`apps/agent-chat-ui`, upstream [langchain-ai/agent-chat-ui](https://github.com/langchain-ai/agent-chat-ui)).

1. Start the Agent Server: `uv run langgraph dev`
2. Start the UI: `./scripts/run_agent_chat_ui.sh`
3. Chat with graph id **`agent`** — when `act` pauses, approve / edit / reject in the inbox UI

LangSmith Studio remains available for the same interrupts during development.

## Interrupt payload (Agent Inbox / HITLRequest)

The `act` node interrupts with:

```json
{
  "action_requests": [
    {
      "name": "send_message",
      "args": { "to": "me", "body": "..." },
      "description": "Approve this external side effect before it runs."
    }
  ],
  "review_configs": [
    {
      "action_name": "send_message",
      "allowed_decisions": ["approve", "edit", "reject"]
    }
  ]
}
```

## Resume payload

Agent Chat UI resumes with:

```python
Command(resume={"decisions": [{"type": "approve"}]})
# or {"type": "reject", "message": "..."}
# or {"type": "edit", "edited_action": {"name": "...", "args": {...}}}
```

Legacy boolean `Command(resume=True|False)` still works for CLI convenience.

Helpers live in `src/langgraph_graph/hitl.py`.

## Relaxation

After an action has been observed N times on a thread with no incidents, it may
be moved to an auto-approve ledger recorded in `state.approvals`. This is a
deliberate, logged decision — never the default.
