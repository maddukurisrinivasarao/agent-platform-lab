"""Harness adapters that run the support-ticket task through different agent loops."""

from __future__ import annotations

from typing import Callable, Protocol

from agent_platform_lab.observability import CostTracker, LoopDetector, TraceStore
from agent_platform_lab.state import CheckpointStore, TaskState
from agent_platform_lab.tools import (
    DraftReplyInput,
    ReadTicketInput,
    ReplyDraft,
    Ticket,
    ToolCall,
    ToolRegistry,
    ToolResult,
)
from agent_platform_lab.workflow import SupportTicketWorkflow, WorkflowResult

# Given the ticket ID and the results so far, propose the next tool call, or None when done.
Planner = Callable[[str, tuple[ToolResult, ...]], ToolCall | None]


class HarnessAdapter(Protocol):
    name: str

    def run(self, ticket_id: str) -> WorkflowResult: ...


class ScriptedHarness:
    """Adapter for the fixed-step SupportTicketWorkflow."""

    name = "scripted"

    def __init__(self, workflow: SupportTicketWorkflow) -> None:
        self._workflow = workflow

    def run(self, ticket_id: str) -> WorkflowResult:
        return self._workflow.run(ticket_id)


def mock_support_planner(ticket_id: str, history: tuple[ToolResult, ...]) -> ToolCall | None:
    """Deterministic stand-in for a model: read the ticket, draft a reply, then stop."""
    if not history:
        return ToolCall("read_ticket", ReadTicketInput(ticket_id))
    last_output = history[-1].output
    if isinstance(last_output, Ticket):
        return ToolCall("draft_reply", DraftReplyInput(last_output))
    return None


class PlannerHarness:
    """Adapter for a model-style loop: a planner proposes each tool call until it stops."""

    name = "planner"

    def __init__(
        self,
        tools: ToolRegistry,
        planner: Planner = mock_support_planner,
        *,
        checkpoint_store: CheckpointStore | None = None,
        trace_store: TraceStore | None = None,
        cost_tracker: CostTracker | None = None,
        loop_detector: LoopDetector | None = None,
        max_steps: int = 5,
    ) -> None:
        self._tools = tools
        self._planner = planner
        self._checkpoint_store = checkpoint_store
        self._trace_store = trace_store or TraceStore()
        self._cost_tracker = cost_tracker or CostTracker()
        self._loop_detector = loop_detector or LoopDetector()
        self._max_steps = max_steps

    def _checkpoint(self, task: TaskState) -> None:
        if self._checkpoint_store is not None:
            self._checkpoint_store.save(task)

    def _finish(
        self,
        task: TaskState,
        status: str,
        *,
        ticket: Ticket | None = None,
        draft: ReplyDraft | None = None,
        reason: str | None = None,
    ) -> WorkflowResult:
        self._checkpoint(task)
        return WorkflowResult(
            status,
            ticket=ticket,
            draft=draft,
            reason=reason,
            task_state=task,
            trace_events=self._trace_store.events_for_task(task.task_id),
            total_cost=task.total_cost,
            loop_alert=self._loop_detector.check_task(task.task_id, self._trace_store),
        )

    def run(self, ticket_id: str) -> WorkflowResult:
        task = TaskState(task_id=f"ticket:{ticket_id}", description=f"Process ticket {ticket_id}")
        history: list[ToolResult] = []
        ticket: Ticket | None = None
        draft: ReplyDraft | None = None

        for _ in range(self._max_steps):
            call = self._planner(ticket_id, tuple(history))
            if call is None:
                task.transition(
                    "completed",
                    description=f"Completed support reply for ticket {ticket_id}",
                    payload={"ticket_id": ticket_id, "reply_body": draft.body if draft else None},
                )
                return self._finish(task, "completed", ticket=ticket, draft=draft)

            task.transition("running", current_tool=call.name, description=f"Running {call.name}")
            self._checkpoint(task)
            result = self._tools.invoke(call)
            allowed = result.decision.status == "allow"
            event = self._trace_store.record(
                task_id=task.task_id,
                tool_name=call.name,
                status="started" if allowed else "denied",
                message=f"Ran {call.name}" if allowed else result.decision.reason,
                payload={
                    "ticket_id": ticket_id,
                    "status": result.decision.status,
                    "credential_id": result.credential_id,
                },
            )
            task.trace_events.append(event.event_id)
            if result.cost:
                task.total_cost += result.cost
                self._cost_tracker.record(
                    task_id=task.task_id, tool_name=call.name, amount=result.cost, description=event.message
                )

            if result.decision.status == "approval_required":
                task.transition("waiting_for_approval", description=result.decision.reason)
                return self._finish(task, "blocked", ticket=ticket, reason=result.decision.reason)
            if not allowed:
                task.transition("blocked", description=result.decision.reason)
                return self._finish(task, "blocked", ticket=ticket, reason=result.decision.reason)

            history.append(result)
            if isinstance(result.output, Ticket):
                ticket = result.output
            elif isinstance(result.output, ReplyDraft):
                draft = result.output

            loop_alert = self._loop_detector.check_task(task.task_id, self._trace_store)
            if loop_alert is not None:
                reason = f"Loop detected: '{loop_alert.tool_name}' ran {loop_alert.occurrences} times."
                task.transition("failed", description=reason, loop_detected=True)
                return self._finish(task, "blocked", ticket=ticket, draft=draft, reason=reason)

        reason = f"Planner did not finish within {self._max_steps} steps."
        task.transition("failed", description=reason)
        return self._finish(task, "blocked", ticket=ticket, draft=draft, reason=reason)
