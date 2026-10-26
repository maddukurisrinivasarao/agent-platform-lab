# Agent Platform Lab

A hands-on project for building a safe, observable runtime and evaluation system for AI agent workflows. The first milestone is intentionally small: establish an action-policy boundary before connecting any model or external system.

## Milestone 1: Typed tools and workflow runner

The policy module evaluates every tool name before dispatch. The tool registry validates typed input and output dataclasses. The support-ticket workflow reads a synthetic ticket and drafts a reply using local mock tools; it does not call a model or send a real reply. A policy denial stops the workflow before the blocked tool executes.

Run the tests from this directory:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Milestone 3: Versioned evaluation scenarios

The evaluation suite in `evals/scenarios/v1.json` runs deterministic workflow scenarios and checks expected workflow/task statuses and reply or policy text. It reports pass rate and outcome counts; any failed scenario makes the command exit non-zero.

Run the evaluation suite from this directory:

```bash
PYTHONPATH=src python3 -m agent_platform_lab.evaluation
```

## Milestone 5: Harness adapters and mock credential broker

`harness.py` defines a common `run(ticket_id)` interface with two adapters: `ScriptedHarness` wraps the fixed-step workflow, and `PlannerHarness` runs a model-style loop in which a planner proposes each tool call. The default planner is a deterministic mock; the loop stops on approval, denial, loop detection, or a step limit. The evaluation suite runs every scenario against both adapters.

`credentials.py` provides a mock `CredentialBroker`. When a registry has one, every allowed tool call gets a fresh token scoped to that tool, validated for scope and expiry just before execution, and revoked immediately after. Traces record only the credential ID, never the token. Tokens are random mock values, not real secrets.

## Milestone 6: Containerized worker and operations

`worker.py` is a command-line worker with `run`, `recover`, and `status` commands. It reads its configuration from environment variables, checkpoints every step with crash-safe writes, reruns interrupted tasks on `recover`, and logs one JSON object per line. The `Dockerfile` packages it as an unprivileged container that keeps state on a `/data` volume and runs `recover` when started without arguments.

```bash
PYTHONPATH=src python3 -m agent_platform_lab.worker run T-1001
docker build -t agent-platform-lab:0.1.0 .
docker run --rm -v agent-state:/data agent-platform-lab:0.1.0 run T-1001
```

See [docs/operations.md](docs/operations.md) for configuration, deployment, recovery, monitoring, and troubleshooting.

## Milestone 7: Evaluation runner tests

`tests/test_evaluation.py` covers the evaluation runner itself: the v1 suite passes on every harness, wrong expectations are reported as failures with the right messages, malformed suites and scenarios missing required fields are rejected with a clear `ValueError`, and the command exits `0` on success and `1` on any failure. These run with the rest of the unit tests.

## Planned milestones

1. Add typed tools and a workflow runner with mocked tools.
2. Add approval handling, task state, and durable checkpoints.
3. Add versioned evaluation scenarios, metrics, and regression checks.
4. Add correlated traces, cost tracking, and loop detection.
5. Add a second harness adapter and a mock short-lived credential broker.
6. Containerize the worker and document deployment, recovery, and operations.
7. Add unit tests for the evaluation runner (suite pass, failure detection, malformed JSON, exit codes).


Use synthetic data and mocked external services throughout the portfolio demo. Never add real credentials to prompts, logs, tests, or repository files.
