"""A deterministic support-ticket workflow using policy-checked mock tools."""

from dataclasses import dataclass
from typing import Literal

from agent_platform_lab.observability import CostTracker, LoopAlert, LoopDetector, TraceEvent, TraceStore
from agent_platform_lab.state import CheckpointStore, TaskState
from agent_platform_lab.tools import (
    DraftReplyInput,
    ReadTicketInput,
    ReplyDraft,
    Ticket,
    ToolCall,
    ToolRegistry,
)


@dataclass(frozen=True)
class WorkflowResult:
    status: Literal["completed", "blocked"]
    ticket: Ticket | None = None
    draft: ReplyDraft | None = None
    reason: str | None = None
    task_state: TaskState | None = None
    trace_events: tuple[TraceEvent, ...] = ()
    total_cost: float = 0.0
    loop_alert: LoopAlert | None = None


class SupportTicketWorkflow:
    def __init__(
        self,
        tools: ToolRegistry,
        checkpoint_store: CheckpointStore | None = None,
        trace_store: TraceStore | None = None,
        cost_tracker: CostTracker | None = None,
        loop_detector: LoopDetector | None = None,
    ) -> None:
        self._tools = tools
        self._checkpoint_store = checkpoint_store
        self._trace_store = trace_store or TraceStore()
        self._cost_tracker = cost_tracker or CostTracker()
        self._loop_detector = loop_detector or LoopDetector(threshold=2)

    def _checkpoint(self, task: TaskState) -> None:
        if self._checkpoint_store is not None:
            self._checkpoint_store.save(task)

    def _record_trace(
        self,
        task: TaskState,
        *,
        tool_name: str,
        status: str,
        message: str,
        payload: dict[str, object] | None = None,
        cost: float | None = None,
    ) -> TraceEvent:
        event = self._trace_store.record(
            task_id=task.task_id,
            tool_name=tool_name,
            status=status,
            message=message,
            payload=payload or {},
        )
        task.trace_events.append(event.event_id)
        if cost is not None:
            task.total_cost += cost
            self._cost_tracker.record(
                task_id=task.task_id,
                tool_name=tool_name,
                amount=cost,
                description=message,
            )
        loop_alert = self._loop_detector.check_task(task.task_id, self._trace_store)
        task.loop_detected = loop_alert is not None
        return event

    def run(self, ticket_id: str, task_state: TaskState | None = None) -> WorkflowResult:
        task = task_state or TaskState(
            task_id=f"ticket:{ticket_id}",
            description=f"Process ticket {ticket_id}",
        )
        task.transition("running", current_tool="read_ticket", description=f"Reading ticket {ticket_id}")
        self._checkpoint(task)

        ticket_result = self._tools.invoke(
            ToolCall("read_ticket", ReadTicketInput(ticket_id))
        )
        self._record_trace(
            task,
            tool_name="read_ticket",
            status="started" if ticket_result.decision.status == "allow" else "denied",
            message=(
                f"Read ticket {ticket_id}"
                if ticket_result.decision.status == "allow"
                else ticket_result.decision.reason
            ),
            payload={
                "ticket_id": ticket_id,
                "status": ticket_result.decision.status,
                "credential_id": ticket_result.credential_id,
            },
            cost=ticket_result.cost,
        )
        if ticket_result.decision.status == "approval_required":
            task.transition(
                "waiting_for_approval",
                current_tool="read_ticket",
                description=f"Approval required before reading ticket {ticket_id}",
                payload={"ticket_id": ticket_id},
                total_cost=task.total_cost,
                loop_detected=task.loop_detected,
            )
            self._checkpoint(task)
            loop_alert = self._loop_detector.check_task(task.task_id, self._trace_store)
            return WorkflowResult(
                "blocked",
                reason=ticket_result.decision.reason,
                task_state=task,
                trace_events=tuple(self._trace_store.events_for_task(task.task_id)),
                total_cost=task.total_cost,
                loop_alert=loop_alert,
            )
        if ticket_result.decision.status != "allow":
            task.transition("blocked", current_tool="read_ticket", description=ticket_result.decision.reason)
            self._checkpoint(task)
            loop_alert = self._loop_detector.check_task(task.task_id, self._trace_store)
            return WorkflowResult(
                "blocked",
                reason=ticket_result.decision.reason,
                task_state=task,
                trace_events=tuple(self._trace_store.events_for_task(task.task_id)),
                total_cost=task.total_cost,
                loop_alert=loop_alert,
            )
        if not isinstance(ticket_result.output, Ticket):
            raise TypeError("The read_ticket tool did not return a Ticket.")

        task.transition(
            "running",
            current_tool="draft_reply",
            description=f"Drafting reply for ticket {ticket_id}",
            payload={"ticket_id": ticket_id, "subject": ticket_result.output.subject},
            total_cost=task.total_cost,
            loop_detected=task.loop_detected,
        )
        self._checkpoint(task)

        draft_result = self._tools.invoke(
            ToolCall("draft_reply", DraftReplyInput(ticket_result.output))
        )
        self._record_trace(
            task,
            tool_name="draft_reply",
            status="started" if draft_result.decision.status == "allow" else "denied",
            message=(
                f"Draft reply for {ticket_id}"
                if draft_result.decision.status == "allow"
                else draft_result.decision.reason
            ),
            payload={
                "ticket_id": ticket_id,
                "status": draft_result.decision.status,
                "credential_id": draft_result.credential_id,
            },
            cost=draft_result.cost,
        )
        if draft_result.decision.status == "approval_required":
            task.transition(
                "waiting_for_approval",
                current_tool="draft_reply",
                description=f"Approval required before drafting a reply for ticket {ticket_id}",
                payload={"ticket_id": ticket_id, "subject": ticket_result.output.subject},
                total_cost=task.total_cost,
                loop_detected=task.loop_detected,
            )
            self._checkpoint(task)
            loop_alert = self._loop_detector.check_task(task.task_id, self._trace_store)
            return WorkflowResult(
                "blocked",
                ticket=ticket_result.output,
                reason=draft_result.decision.reason,
                task_state=task,
                trace_events=tuple(self._trace_store.events_for_task(task.task_id)),
                total_cost=task.total_cost,
                loop_alert=loop_alert,
            )
        if draft_result.decision.status != "allow":
            task.transition("blocked", current_tool="draft_reply", description=draft_result.decision.reason)
            self._checkpoint(task)
            loop_alert = self._loop_detector.check_task(task.task_id, self._trace_store)
            return WorkflowResult(
                "blocked",
                ticket=ticket_result.output,
                reason=draft_result.decision.reason,
                task_state=task,
                trace_events=tuple(self._trace_store.events_for_task(task.task_id)),
                total_cost=task.total_cost,
                loop_alert=loop_alert,
            )
        if not isinstance(draft_result.output, ReplyDraft):
            raise TypeError("The draft_reply tool did not return a ReplyDraft.")

        task.transition(
            "completed",
            current_tool="draft_reply",
            description=f"Completed support reply for ticket {ticket_id}",
            payload={"ticket_id": ticket_id, "reply_body": draft_result.output.body},
            total_cost=task.total_cost,
            loop_detected=task.loop_detected,
        )
        self._checkpoint(task)
        loop_alert = self._loop_detector.check_task(task.task_id, self._trace_store)

        return WorkflowResult(
            "completed",
            ticket=ticket_result.output,
            draft=draft_result.output,
            task_state=task,
            trace_events=tuple(self._trace_store.events_for_task(task.task_id)),
            total_cost=task.total_cost,
            loop_alert=loop_alert,
        )