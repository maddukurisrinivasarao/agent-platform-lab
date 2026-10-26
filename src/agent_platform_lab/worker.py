"""Command-line worker that processes tickets with durable checkpoints and crash recovery.

Configuration comes from environment variables so the same image runs in any environment:

  AGENT_STATE_DIR          directory for the checkpoint file (default: ./state)
  AGENT_HARNESS            "scripted" or "planner" (default: planner)
  AGENT_ALLOWED_ACTIONS    comma-separated allow-list (default: read_ticket,draft_reply)
  AGENT_APPROVAL_REQUIRED  comma-separated actions that pause for approval (default: none)
  AGENT_CREDENTIAL_TTL     credential lifetime in seconds (default: 30)
  AGENT_TICKETS_FILE       XML ticket database (default: data/tickets.xml)
  AGENT_REPLY_WRITER       "template" or "llm" (default: template)
  AGENT_LLM_PROVIDER       groq, openrouter, ollama, or anthropic (default: groq)
  AGENT_LLM_MODEL          model ID for that provider (default: openai/gpt-oss-120b)

The llm writer reads its API key from GROQ_API_KEY_2, OPENROUTER_API_KEY, or ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from agent_platform_lab.credentials import CredentialBroker
from agent_platform_lab.harness import HarnessAdapter, PlannerHarness, ScriptedHarness
from agent_platform_lab.policy import ActionPolicy
from agent_platform_lab.llm_client import ClientSingleton
from agent_platform_lab.replies import ReplyWriter, llm_reply, template_reply
from agent_platform_lab.state import CheckpointStore, TaskState
from agent_platform_lab.tickets import load_tickets_xml
from agent_platform_lab.tools import create_tool_registry
from agent_platform_lab.workflow import SupportTicketWorkflow, WorkflowResult

# Tasks in these states were interrupted mid-run; every tool is read-only or draft-only,
# so recovery safely restarts them from the first step.
INTERRUPTED_STATUSES = frozenset({"created", "running", "approved"})
FAILED_STATUSES = frozenset({"blocked", "failed", "rejected"})


@dataclass(frozen=True)
class WorkerConfig:
    state_dir: Path
    harness: str
    allowed_actions: frozenset[str]
    approval_required: frozenset[str]
    credential_ttl: float
    tickets_file: Path
    reply_writer: str
    llm_provider: str
    llm_model: str

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "WorkerConfig":
        env = dict(os.environ if env is None else env)

        def actions(name: str, default: str) -> frozenset[str]:
            return frozenset(item.strip() for item in env.get(name, default).split(",") if item.strip())

        harness = env.get("AGENT_HARNESS", "planner")
        if harness not in ("scripted", "planner"):
            raise ValueError(f"AGENT_HARNESS must be 'scripted' or 'planner', got '{harness}'.")
        reply_writer = env.get("AGENT_REPLY_WRITER", "template")
        if reply_writer not in ("template", "llm"):
            raise ValueError(f"AGENT_REPLY_WRITER must be 'template' or 'llm', got '{reply_writer}'.")
        llm_provider = env.get("AGENT_LLM_PROVIDER", "groq")
        if llm_provider not in ("groq", "openrouter", "ollama", "anthropic"):
            raise ValueError(
                f"AGENT_LLM_PROVIDER must be groq, openrouter, ollama, or anthropic, got '{llm_provider}'."
            )
        return cls(
            state_dir=Path(env.get("AGENT_STATE_DIR", "state")),
            harness=harness,
            allowed_actions=actions("AGENT_ALLOWED_ACTIONS", "read_ticket,draft_reply"),
            approval_required=actions("AGENT_APPROVAL_REQUIRED", ""),
            credential_ttl=float(env.get("AGENT_CREDENTIAL_TTL", "30")),
            tickets_file=Path(env.get("AGENT_TICKETS_FILE", "data/tickets.xml")),
            reply_writer=reply_writer,
            llm_provider=llm_provider,
            llm_model=env.get("AGENT_LLM_MODEL", "openai/gpt-oss-120b"),
        )


class Worker:
    def __init__(self, config: WorkerConfig) -> None:
        self.config = config
        self.checkpoints = CheckpointStore(config.state_dir / "checkpoints.json")

    def _harness(self) -> HarnessAdapter:
        policy = ActionPolicy(
            allowed_actions=self.config.allowed_actions,
            approval_required=self.config.approval_required,
        )
        reply_writer: ReplyWriter = template_reply
        if self.config.reply_writer == "llm":
            ClientSingleton.configure(self.config.llm_provider, self.config.llm_model)
            ClientSingleton.get_llm_client()  # Fail at startup, not mid-ticket, if the SDK is missing.
            reply_writer = llm_reply
        tools = create_tool_registry(
            policy,
            load_tickets_xml(self.config.tickets_file),
            reply_writer,
            credential_broker=CredentialBroker(ttl_seconds=self.config.credential_ttl),
        )
        if self.config.harness == "scripted":
            return ScriptedHarness(SupportTicketWorkflow(tools, checkpoint_store=self.checkpoints))
        return PlannerHarness(tools, checkpoint_store=self.checkpoints)

    def process(self, ticket_ids: list[str]) -> list[WorkflowResult]:
        harness = self._harness()
        return [self._run_one(harness, ticket_id) for ticket_id in ticket_ids]

    def _run_one(self, harness: HarnessAdapter, ticket_id: str) -> WorkflowResult:
        try:
            return harness.run(ticket_id)
        except Exception as error:
            # Mark the task failed so recovery does not retry a ticket that crashes every time.
            task_id = f"ticket:{ticket_id}"
            task = self.checkpoints.load(task_id) or TaskState(task_id=task_id)
            reason = f"{type(error).__name__}: {error}"
            task.transition("failed", description=reason)
            self.checkpoints.save(task)
            return WorkflowResult("blocked", reason=reason, task_state=task)

    def interrupted_tasks(self) -> tuple[TaskState, ...]:
        return tuple(task for task in self.checkpoints.all() if task.status in INTERRUPTED_STATUSES)

    def recover(self) -> list[WorkflowResult]:
        ticket_ids = [task.task_id.removeprefix("ticket:") for task in self.interrupted_tasks()]
        return self.process(ticket_ids)


def _summary(result: WorkflowResult) -> dict[str, object]:
    task = result.task_state
    return {
        "task_id": task.task_id if task else None,
        "workflow_status": result.status,
        "task_status": task.status if task else None,
        "total_cost": round(result.total_cost, 4),
        "reason": result.reason,
        "reply": result.draft.body if result.draft else None,
    }


def _emit(event: str, **fields: object) -> None:
    # One JSON object per line so log collectors can parse worker output directly.
    print(json.dumps({"event": event, **fields}, sort_keys=True), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-worker", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="process one or more tickets")
    run_parser.add_argument("ticket_ids", nargs="+", metavar="TICKET_ID")
    commands.add_parser("recover", help="rerun tasks interrupted by a crash")
    commands.add_parser("status", help="print every checkpointed task")
    args = parser.parse_args(argv)

    try:
        worker = Worker(WorkerConfig.from_env())
        if args.command == "status":
            for task in worker.checkpoints.all():
                _emit("task_status", task_id=task.task_id, status=task.status, updated_at=task.updated_at)
            return 0

        if args.command == "recover":
            _emit("recovery_started", interrupted=len(worker.interrupted_tasks()))
            results = worker.recover()
        else:
            results = worker.process(args.ticket_ids)
    except Exception as error:  # Surface any failure as a structured log line and non-zero exit.
        _emit("worker_error", error_type=type(error).__name__, message=str(error))
        return 2

    for result in results:
        _emit("task_finished", **_summary(result))
    if worker.config.reply_writer == "llm":
        _emit(
            "llm_usage",
            provider=worker.config.llm_provider,
            model=worker.config.llm_model,
            **ClientSingleton.get_usage(),
        )
    failed = any(result.task_state and result.task_state.status in FAILED_STATUSES for result in results)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
