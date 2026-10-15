"""A deterministic support-ticket workflow using policy-checked mock tools."""

from dataclasses import dataclass
from typing import Literal

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


class SupportTicketWorkflow:
    def __init__(self, tools: ToolRegistry, checkpoint_store: CheckpointStore | None = None) -> None:
        self._tools = tools
        self._checkpoint_store = checkpoint_store

    def _checkpoint(self, task: TaskState) -> None:
        if self._checkpoint_store is not None:
            self._checkpoint_store.save(task)

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
        if ticket_result.decision.status == "approval_required":
            task.transition(
                "waiting_for_approval",
                current_tool="read_ticket",
                description=f"Approval required before reading ticket {ticket_id}",
                payload={"ticket_id": ticket_id},
            )
            self._checkpoint(task)
            return WorkflowResult("blocked", reason=ticket_result.decision.reason, task_state=task)
        if ticket_result.decision.status != "allow":
            task.transition("blocked", current_tool="read_ticket", description=ticket_result.decision.reason)
            self._checkpoint(task)
            return WorkflowResult("blocked", reason=ticket_result.decision.reason, task_state=task)
        if not isinstance(ticket_result.output, Ticket):
            raise TypeError("The read_ticket tool did not return a Ticket.")

        task.transition(
            "running",
            current_tool="draft_reply",
            description=f"Drafting reply for ticket {ticket_id}",
            payload={"ticket_id": ticket_id, "subject": ticket_result.output.subject},
        )
        self._checkpoint(task)

        draft_result = self._tools.invoke(
            ToolCall("draft_reply", DraftReplyInput(ticket_result.output))
        )
        if draft_result.decision.status == "approval_required":
            task.transition(
                "waiting_for_approval",
                current_tool="draft_reply",
                description=f"Approval required before drafting a reply for ticket {ticket_id}",
                payload={"ticket_id": ticket_id, "subject": ticket_result.output.subject},
            )
            self._checkpoint(task)
            return WorkflowResult(
                "blocked",
                ticket=ticket_result.output,
                reason=draft_result.decision.reason,
                task_state=task,
            )
        if draft_result.decision.status != "allow":
            task.transition("blocked", current_tool="draft_reply", description=draft_result.decision.reason)
            self._checkpoint(task)
            return WorkflowResult(
                "blocked",
                ticket=ticket_result.output,
                reason=draft_result.decision.reason,
                task_state=task,
            )
        if not isinstance(draft_result.output, ReplyDraft):
            raise TypeError("The draft_reply tool did not return a ReplyDraft.")

        task.transition(
            "completed",
            current_tool="draft_reply",
            description=f"Completed support reply for ticket {ticket_id}",
            payload={"ticket_id": ticket_id, "reply_body": draft_result.output.body},
        )
        self._checkpoint(task)

        return WorkflowResult(
            "completed",
            ticket=ticket_result.output,
            draft=draft_result.output,
            task_state=task,
        )