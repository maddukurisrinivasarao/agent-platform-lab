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

## Planned milestones

1. Add typed tools and a workflow runner with mocked tools.
2. Add approval handling, task state, and durable checkpoints.
3. Add versioned evaluation scenarios, metrics, and regression checks.
4. Add correlated traces, cost tracking, and loop detection.
5. Add a second harness adapter and a mock short-lived credential broker.
6. Containerize the worker and document deployment, recovery, and operations.

Use synthetic data and mocked external services throughout the portfolio demo. Never add real credentials to prompts, logs, tests, or repository files.
