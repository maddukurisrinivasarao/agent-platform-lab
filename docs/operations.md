# Operations guide

This guide covers deploying, running, recovering, and troubleshooting the agent worker. Everything in this project uses synthetic tickets and mock tools; never configure real credentials.

## What the worker does

`agent-worker` (module `agent_platform_lab.worker`) processes support tickets through a harness, saves a checkpoint after every step, and can recover tasks that a crash interrupted.

| Command | Purpose | Exit code |
|---|---|---|
| `agent-worker run T-1001 [T-...]` | Process one or more tickets | `0` all completed or waiting for approval, `1` any blocked or failed |
| `agent-worker recover` | Rerun tasks left in `created`, `running`, or `approved` | same as `run` |
| `agent-worker status` | Print every checkpointed task | `0` |

Any configuration or startup error exits with `2`.

## Configuration

All settings are environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `AGENT_STATE_DIR` | `./state` (`/data` in the image) | Directory holding `checkpoints.json` |
| `AGENT_HARNESS` | `planner` | `planner` (model-style loop) or `scripted` (fixed steps) |
| `AGENT_ALLOWED_ACTIONS` | `read_ticket,draft_reply` | Comma-separated tool allow-list |
| `AGENT_APPROVAL_REQUIRED` | empty | Tools that pause for human approval; must also be allow-listed |
| `AGENT_CREDENTIAL_TTL` | `30` | Lifetime in seconds of each mock tool credential |
| `AGENT_TICKETS_FILE` | `data/tickets.xml` (`/app/data/tickets.xml` in the image) | XML ticket database |
| `AGENT_REPLY_WRITER` | `template` | `template` (fixed text, free) or `llm` (billed per call by the provider) |
| `AGENT_LLM_PROVIDER` | `groq` | `groq`, `openrouter`, `ollama` (local, free), or `anthropic` |
| `AGENT_LLM_MODEL` | `openai/gpt-oss-120b` | Model ID for that provider |
| `GROQ_API_KEY_2` / `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` | unset | Key for the chosen provider (Ollama needs none); never logged |

### Ticket database

Tickets live in an XML file. Each ticket needs an `id`, a `subject`, and a `body`:

```xml
<tickets>
  <ticket id="T-1001">
    <subject>Unable to access my account</subject>
    <body>I reset my password but still cannot sign in.</body>
  </ticket>
</tickets>
```

The file is read when the worker starts. Invalid XML, missing fields, and duplicate IDs stop the worker with a `worker_error`. Use synthetic tickets only.

### LLM reply writer

All providers go through `ClientSingleton` in `llm_client.py`, which builds one client per process and normalizes every response to a `.content` string.

```bash
pip install ".[groq]"               # or .[openrouter], .[ollama], .[anthropic]
export GROQ_API_KEY_2=...           # never commit this or put it in a file in the repo
AGENT_REPLY_WRITER=llm agent-worker run T-1002

# Another provider
AGENT_REPLY_WRITER=llm AGENT_LLM_PROVIDER=ollama AGENT_LLM_MODEL=qwen2.5-coder:7b agent-worker run T-1002
```

After the tickets, the worker logs an `llm_usage` event with the real prompt, completion, and total token counts for the run.

The customer's ticket text is sent to the model inside `<ticket>` tags, and the system prompt tells the model to treat it as data, not instructions (ticket `T-1005` contains an injection attempt to try this). The prompt also forbids promising refunds or account changes. Replies are drafts and are never sent. An API error or empty reply marks the task `failed`. Requests time out after 120 seconds.

In the container, pass the key at run time: `docker run --rm -e GROQ_API_KEY_2 -e AGENT_REPLY_WRITER=llm -v agent-state:/data agent-platform-lab:0.1.0 run T-1002`.

The mock per-call costs in traces (`0.12`, `0.35`) do not reflect real token charges; use the `llm_usage` event or the provider's console for real spend.

## Deployment

### Local (no container)

```bash
PYTHONPATH=src python3 -m unittest discover -s tests   # verify first
PYTHONPATH=src python3 -m agent_platform_lab.evaluation
PYTHONPATH=src python3 -m agent_platform_lab.worker run T-1001
```

### Container

```bash
docker build -t agent-platform-lab:0.1.0 .
docker volume create agent-state

# Process a ticket
docker run --rm -v agent-state:/data agent-platform-lab:0.1.0 run T-1001

# Inspect checkpoints
docker run --rm -v agent-state:/data agent-platform-lab:0.1.0 status
```

The image runs as an unprivileged user (UID 10001), contains no tests or credentials, and keeps all state on the `/data` volume. Run the unit tests and evaluation suite before building; the image does not include them.

With no arguments the container runs `recover`. For a long-lived deployment, run it with a restart policy (for example `--restart on-failure`) so every restart first finishes interrupted work.

## Recovery

**How state is saved.** After every step the worker writes the task's status, current tool, total cost, and trace event IDs to `checkpoints.json`. Each write goes to a temporary file that is then renamed over the original, so a crash during a write leaves the previous complete file in place, never a half-written one.

**After a crash or restart:**

1. Run `agent-worker status` to see each task's last saved state.
2. Run `agent-worker recover`. Tasks in `created`, `running`, or `approved` restart from the first step.
3. Check the `task_finished` log lines for the outcome.

Restarting from the first step is safe because every tool is read-only or draft-only: re-reading a ticket or re-drafting a reply has no side effect. Any future tool with real side effects (sending email, issuing refunds) will need per-step resume or idempotency keys before this remains true.

**Tasks recovery leaves alone:**

| Status | Why | Action |
|---|---|---|
| `completed` | Already done | None |
| `waiting_for_approval` | Needs a human decision | Approval handling is not built yet; rerun the ticket with an updated policy if appropriate |
| `failed` | The task crashed, looped, or hit the step limit | Read the `reason`, fix the cause, then `run` the ticket again |
| `blocked` | The policy denied a tool | Review `AGENT_ALLOWED_ACTIONS` |

A ticket that raises an error is marked `failed` and the worker moves on to the next ticket, so one bad ticket never blocks recovery of the others.

**Losing the state volume** loses checkpoint history only; tickets can be reprocessed with `run`.

## Monitoring and logs

The worker writes one JSON object per line to stdout:

```json
{"event": "task_finished", "task_id": "ticket:T-1001", "workflow_status": "completed", "task_status": "completed", "total_cost": 0.47, "reason": null, "reply": "Thanks for contacting support about 'Unable to access my account'. We will review your request and follow up."}
```

| Event | When |
|---|---|
| `task_finished` | A ticket finished, paused, or failed |
| `recovery_started` | `recover` began; `interrupted` is the number of tasks found |
| `task_status` | One line per task from `status` |
| `worker_error` | Configuration or startup failure |

Signals worth alerting on:

- **Non-zero exit codes.** `1` means a task was blocked or failed; `2` means the worker could not start.
- **`task_status: "failed"` with a reason starting `Loop detected`.** The planner repeated a tool; investigate the planner.
- **`waiting_for_approval` count growing.** Approvals are piling up.
- **`total_cost` per task.** A sudden rise points to extra tool calls.

Credential tokens never appear in logs or traces; only credential IDs (`cred-...`) do.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `worker_error` mentioning `AGENT_HARNESS` | Typo in the variable | Use `planner` or `scripted` |
| `worker_error` saying approval actions must be allow-listed | `AGENT_APPROVAL_REQUIRED` lists a tool missing from `AGENT_ALLOWED_ACTIONS` | Add it to both |
| Task `failed` with `KeyError: Unknown ticket` | Ticket ID not in the XML file | Add it to `AGENT_TICKETS_FILE` or check the ID |
| `worker_error` saying `No module named 'groq'`, `'openai'`, or `'anthropic'` | SDK for `AGENT_LLM_PROVIDER` not installed | `pip install ".[groq]"` (or the matching extra) |
| `worker_error` or task `failed` mentioning the API key or `AuthenticationError` | Missing or invalid key for the provider | Set `GROQ_API_KEY_2`, `OPENROUTER_API_KEY`, or `ANTHROPIC_API_KEY` |
| Task `failed` with `APIConnectionError` and provider `ollama` | Ollama server not running | Start Ollama and `ollama pull` the model |
| Task `failed` with `returned no reply text` | The model returned an empty answer | Rerun the ticket; draft that reply by hand if it repeats |
| Task `blocked` with `not allow-listed` | Tool missing from the allow-list | Update `AGENT_ALLOWED_ACTIONS` |
| Every tool call denied with `has expired` | `AGENT_CREDENTIAL_TTL` is `0` | Use a positive TTL |
| `PermissionError` writing checkpoints in the container | Mounted host directory not writable by UID 10001 | Use a named volume, or `chown 10001` the host directory |

## Known limitations

- Approval handling is not built: nothing moves a task from `waiting_for_approval` to `approved`.
- Recovery restarts tasks from the first step rather than resuming at the saved step.
- Traces and cost entries are kept in memory; only their totals and event IDs survive a restart.
- One worker per state volume. Two workers writing the same `checkpoints.json` can overwrite each other's updates.
