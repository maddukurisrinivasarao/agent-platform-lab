"""A deterministic support-ticket workflow using policy-checked mock tools."""

from dataclasses import dataclass
from typing import Literal

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


class SupportTicketWorkflow:
    def __init__(self, tools: ToolRegistry) -> None:
        self._tools = tools

    def run(self, ticket_id: str) -> WorkflowResult:
        ticket_result = self._tools.invoke(
            ToolCall("read_ticket", ReadTicketInput(ticket_id))
        )
        if ticket_result.decision.status != "allow":
            return WorkflowResult("blocked", reason=ticket_result.decision.reason)
        if not isinstance(ticket_result.output, Ticket):
            raise TypeError("The read_ticket tool did not return a Ticket.")

        draft_result = self._tools.invoke(
            ToolCall("draft_reply", DraftReplyInput(ticket_result.output))
        )
        if draft_result.decision.status != "allow":
            return WorkflowResult(
                "blocked",
                ticket=ticket_result.output,
                reason=draft_result.decision.reason,
            )
        if not isinstance(draft_result.output, ReplyDraft):
            raise TypeError("The draft_reply tool did not return a ReplyDraft.")

        return WorkflowResult(
            "completed",
            ticket=ticket_result.output,
            draft=draft_result.output,
        )