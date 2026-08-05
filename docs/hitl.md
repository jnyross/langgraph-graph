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

## Relaxation

After an action has been observed N times on a thread with no incidents, it may
be moved to an auto-approve ledger recorded in `state.approvals`. This is a
deliberate, logged decision — never the default.
