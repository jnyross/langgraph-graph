/**
 * Minimal HITL UI client for LangGraph Agent Server.
 *
 * Defaults to same-origin `/lg` proxy (see hitl_ui server). Query params:
 *   assistantId, threadId, apiUrl (override; default `/lg`)
 */

const params = new URLSearchParams(window.location.search);
const apiBase = (params.get("apiUrl") || "/lg").replace(/\/$/, "");
const assistantInput = document.getElementById("assistantId");
const threadInput = document.getElementById("threadId");
const statusEl = document.getElementById("status");
const logEl = document.getElementById("log");
const outputEl = document.getElementById("output");
const promptPanel = document.getElementById("promptPanel");
const promptTitle = document.getElementById("promptTitle");
const promptBody = document.getElementById("promptBody");
const promptControls = document.getElementById("promptControls");
const startBtn = document.getElementById("startBtn");
const attachBtn = document.getElementById("attachBtn");

assistantInput.value = params.get("assistantId") || "hitl_demo";
if (params.get("threadId")) {
  threadInput.value = params.get("threadId");
}

let busy = false;
let currentPrompt = null;

function setStatus(text) {
  statusEl.textContent = text;
}

function log(line) {
  const stamp = new Date().toLocaleTimeString();
  logEl.textContent = `${logEl.textContent}[${stamp}] ${line}\n`.trimStart();
  logEl.scrollTop = logEl.scrollHeight;
}

function setBusy(next) {
  busy = next;
  startBtn.disabled = next;
  attachBtn.disabled = next;
}

async function api(path, options = {}) {
  const res = await fetch(`${apiBase}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail =
      typeof data === "object" && data
        ? data.detail || data.error || JSON.stringify(data)
        : text;
    throw new Error(`${res.status} ${path}: ${detail}`);
  }
  return data;
}

function extractInterrupt(result) {
  if (!result || typeof result !== "object") return null;
  const raw = result.__interrupt__;
  if (!raw) return null;
  const first = Array.isArray(raw) ? raw[0] : raw;
  if (!first) return null;
  if (typeof first === "object" && "value" in first) return first.value;
  return first;
}

function isAgentInbox(value) {
  return (
    value &&
    typeof value === "object" &&
    Array.isArray(value.action_requests) &&
    value.action_requests.length > 0 &&
    Array.isArray(value.review_configs)
  );
}

function hidePrompt({ clear = true } = {}) {
  promptPanel.hidden = true;
  promptControls.innerHTML = "";
  if (clear) currentPrompt = null;
}

function showPrompt(title, body) {
  promptPanel.hidden = false;
  promptTitle.textContent = title;
  promptBody.textContent = body || "";
  promptControls.innerHTML = "";
}

function actionRow(buttons) {
  const row = document.createElement("div");
  row.className = "actions";
  for (const btn of buttons) {
    const el = document.createElement("button");
    el.type = "button";
    el.textContent = btn.label;
    if (btn.className) el.className = btn.className;
    el.addEventListener("click", btn.onClick);
    row.appendChild(el);
  }
  promptControls.appendChild(row);
}

async function resumeWith(resume) {
  const assistantId = assistantInput.value.trim() || "hitl_demo";
  const threadId = threadInput.value.trim();
  if (!threadId) throw new Error("Missing thread id");
  setBusy(true);
  hidePrompt({ clear: false });
  setStatus("Resuming…");
  log(`resume ${JSON.stringify(resume)}`);
  try {
    const result = await api(`/threads/${threadId}/runs/wait`, {
      method: "POST",
      body: JSON.stringify({
        assistant_id: assistantId,
        command: { resume },
      }),
    });
    await handleResult(result);
  } catch (err) {
    setStatus(String(err.message || err));
    log(`error: ${err.message || err}`);
    if (currentPrompt) renderPrompt(currentPrompt);
  } finally {
    setBusy(false);
  }
}

function renderConfirm(prompt) {
  showPrompt(prompt.title || "Confirm", prompt.prompt || "");
  actionRow([
    {
      label: prompt.yes_label || "Yes",
      onClick: () => resumeWith({ kind: "confirm", value: true }),
    },
    {
      label: prompt.no_label || "No",
      className: "secondary",
      onClick: () => resumeWith({ kind: "confirm", value: false }),
    },
  ]);
}

function renderChoice(prompt) {
  showPrompt(prompt.title || "Choose", prompt.prompt || "");
  const list = document.createElement("div");
  list.className = "option-list";
  const multi = Boolean(prompt.allow_multiple);
  const selected = new Set();

  for (const opt of prompt.options || []) {
    const label = document.createElement("label");
    label.className = "option";
    const input = document.createElement("input");
    input.type = multi ? "checkbox" : "radio";
    input.name = "hitl-choice";
    input.value = opt.id;
    input.addEventListener("change", () => {
      if (multi) {
        if (input.checked) selected.add(opt.id);
        else selected.delete(opt.id);
      } else {
        selected.clear();
        selected.add(opt.id);
        list.querySelectorAll(".option").forEach((el) => el.classList.remove("selected"));
      }
      label.classList.toggle("selected", input.checked);
    });
    label.appendChild(input);
    label.appendChild(document.createTextNode(opt.label || opt.id));
    list.appendChild(label);
  }
  promptControls.appendChild(list);

  actionRow([
    {
      label: "Submit",
      onClick: () => {
        if (!selected.size) {
          setStatus("Pick at least one option.");
          return;
        }
        const value = multi ? [...selected] : [...selected][0];
        resumeWith({ kind: "choice", value });
      },
    },
  ]);
}

function renderText(prompt) {
  showPrompt(prompt.title || "Input", prompt.prompt || "");
  const field = document.createElement(prompt.multiline === false ? "input" : "textarea");
  if (field.tagName === "INPUT") field.type = "text";
  field.placeholder = prompt.placeholder || "";
  promptControls.appendChild(field);
  actionRow([
    {
      label: "Submit",
      onClick: () => resumeWith({ kind: "text", value: field.value }),
    },
  ]);
}

function renderApproveTagged(prompt) {
  const action = prompt.action || {};
  const allowed = new Set(prompt.allowed_decisions || ["approve", "edit", "reject"]);
  showPrompt(prompt.title || "Approve", prompt.prompt || "");

  const argsGrid = document.createElement("div");
  argsGrid.className = "args-grid";
  const argInputs = {};
  const args = action.args && typeof action.args === "object" ? action.args : {};
  for (const [key, value] of Object.entries(args)) {
    const label = document.createElement("label");
    label.textContent = key;
    const input = document.createElement("textarea");
    input.value = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    argInputs[key] = input;
    label.appendChild(input);
    argsGrid.appendChild(label);
  }
  if (Object.keys(argInputs).length) promptControls.appendChild(argsGrid);

  const rejectBox = document.createElement("textarea");
  rejectBox.placeholder = "Rejection reason (required to reject)";
  rejectBox.hidden = !allowed.has("reject");
  if (allowed.has("reject")) promptControls.appendChild(rejectBox);

  const buttons = [];
  if (allowed.has("approve")) {
    buttons.push({
      label: "Approve",
      onClick: () =>
        resumeWith({
          kind: "approve",
          decision: { type: "approve" },
        }),
    });
  }
  if (allowed.has("edit")) {
    buttons.push({
      label: "Edit & approve",
      className: "secondary",
      onClick: () => {
        const editedArgs = {};
        for (const [key, input] of Object.entries(argInputs)) {
          const raw = input.value;
          try {
            editedArgs[key] = JSON.parse(raw);
          } catch {
            editedArgs[key] = raw;
          }
        }
        resumeWith({
          kind: "approve",
          decision: {
            type: "edit",
            edited_action: {
              name: action.name || "action",
              args: editedArgs,
            },
          },
        });
      },
    });
  }
  if (allowed.has("reject")) {
    buttons.push({
      label: "Reject",
      className: "danger",
      onClick: () => {
        const message = rejectBox.value.trim();
        if (!message) {
          setStatus("Enter a rejection reason.");
          return;
        }
        resumeWith({
          kind: "approve",
          decision: { type: "reject", message },
        });
      },
    });
  }
  actionRow(buttons);
}

function renderAgentInbox(prompt) {
  const action = prompt.action_requests[0] || {};
  const config =
    (prompt.review_configs || []).find((c) => c.action_name === action.name) ||
    prompt.review_configs[0] ||
    {};
  renderApproveTagged({
    kind: "approve",
    title: action.name || "Approve action",
    prompt: action.description || "Review this action.",
    action: { name: action.name, args: action.args || {} },
    allowed_decisions: config.allowed_decisions || ["approve", "edit", "reject"],
  });
}

function renderPrompt(prompt) {
  currentPrompt = prompt;
  if (!prompt || typeof prompt !== "object") {
    showPrompt("Interrupt", JSON.stringify(prompt, null, 2));
    actionRow([
      {
        label: "Approve (true)",
        onClick: () => resumeWith(true),
      },
      {
        label: "Reject (false)",
        className: "secondary",
        onClick: () => resumeWith(false),
      },
    ]);
    return;
  }

  if (isAgentInbox(prompt)) {
    renderAgentInbox(prompt);
    return;
  }

  switch (prompt.kind) {
    case "confirm":
      renderConfirm(prompt);
      break;
    case "choice":
      renderChoice(prompt);
      break;
    case "text":
      renderText(prompt);
      break;
    case "approve":
      renderApproveTagged(prompt);
      break;
    default:
      showPrompt(prompt.title || "Interrupt", prompt.prompt || JSON.stringify(prompt, null, 2));
      actionRow([
        {
          label: "Submit raw JSON",
          onClick: () => {
            const raw = window.prompt("Resume JSON", '{"value":true}');
            if (!raw) return;
            try {
              resumeWith(JSON.parse(raw));
            } catch (err) {
              setStatus(`Invalid JSON: ${err.message}`);
            }
          },
        },
      ]);
  }
}

async function handleResult(result) {
  const interrupt = extractInterrupt(result);
  if (interrupt) {
    const kind = interrupt.kind || (isAgentInbox(interrupt) ? "agent_inbox" : "unknown");
    setStatus(`Waiting for human input (${kind}).`);
    log(`interrupt kind=${kind}`);
    renderPrompt(interrupt);
    return;
  }

  hidePrompt();
  const output =
    (result && (result.output || result.values?.output)) ||
    (typeof result === "object" ? JSON.stringify(result, null, 2) : String(result));
  outputEl.hidden = false;
  outputEl.textContent = typeof output === "string" ? output : JSON.stringify(output, null, 2);
  setStatus("Run complete.");
  log("run complete");
}

async function createThread() {
  const thread = await api("/threads", {
    method: "POST",
    body: JSON.stringify({}),
  });
  return thread.thread_id;
}

async function startRun() {
  if (busy) return;
  setBusy(true);
  hidePrompt();
  outputEl.hidden = true;
  outputEl.textContent = "";
  setStatus("Starting…");
  try {
    const assistantId = assistantInput.value.trim() || "hitl_demo";
    let threadId = threadInput.value.trim();
    if (!threadId) {
      threadId = await createThread();
      threadInput.value = threadId;
      const url = new URL(window.location.href);
      url.searchParams.set("assistantId", assistantId);
      url.searchParams.set("threadId", threadId);
      window.history.replaceState({}, "", url);
      log(`created thread ${threadId}`);
    }

    const input =
      assistantId === "hitl_demo"
        ? { input: "hitl-ui", messages: [{ role: "user", content: "hitl-ui" }] }
        : {
            input: "Approve a demo message from HITL Control.",
            messages: [
              {
                role: "user",
                content: "Approve a demo message from HITL Control.",
              },
            ],
          };

    log(`run assistant=${assistantId}`);
    const result = await api(`/threads/${threadId}/runs/wait`, {
      method: "POST",
      body: JSON.stringify({
        assistant_id: assistantId,
        input,
      }),
    });
    await handleResult(result);
  } catch (err) {
    setStatus(String(err.message || err));
    log(`error: ${err.message || err}`);
  } finally {
    setBusy(false);
  }
}

async function attachThread() {
  if (busy) return;
  const threadId = threadInput.value.trim();
  if (!threadId) {
    setStatus("Enter a thread id to attach.");
    return;
  }
  setBusy(true);
  hidePrompt();
  setStatus("Loading thread state…");
  try {
    const state = await api(`/threads/${threadId}/state`);
    // Thread state may expose tasks/interrupts differently; prefer values + tasks.
    const values = state.values || state;
    const tasks = state.tasks || [];
    let interrupt = null;
    for (const task of tasks) {
      const interrupts = task.interrupts || [];
      if (interrupts.length) {
        const first = interrupts[0];
        interrupt = first.value ?? first;
        break;
      }
    }
    if (!interrupt && values?.__interrupt__) {
      interrupt = extractInterrupt(values);
    }
    if (interrupt) {
      log(`attached thread ${threadId} with interrupt`);
      setStatus("Attached — pending interrupt.");
      renderPrompt(interrupt);
    } else if (values?.output) {
      outputEl.hidden = false;
      outputEl.textContent = values.output;
      setStatus("Attached — thread already complete.");
      log(`attached thread ${threadId} complete`);
    } else {
      // No interrupt yet — start/continue a wait with empty input is wrong;
      // try wait with no input via command-less resume of existing interrupted? 
      // Instead kick a wait only if idle by starting with null input is for static interrupts.
      setStatus("Attached — no pending interrupt. Use Start run on a fresh thread.");
      log(`attached thread ${threadId}; no interrupt found`);
    }
  } catch (err) {
    setStatus(String(err.message || err));
    log(`error: ${err.message || err}`);
  } finally {
    setBusy(false);
  }
}

startBtn.addEventListener("click", startRun);
attachBtn.addEventListener("click", attachThread);

log(`api=${apiBase}`);
if (params.get("threadId")) {
  attachThread();
}
