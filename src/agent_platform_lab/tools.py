"""Typed tool definitions and policy-enforced tool dispatch."""

from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar

from agent_platform_lab.policy import ActionPolicy, ActionRequest, PolicyDecision

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


@dataclass(frozen=True)
class Ticket:
    ticket_id: str
    subject: str
    body: str


@dataclass(frozen=True)
class ReadTicketInput:
    ticket_id: str


@dataclass(frozen=True)
class DraftReplyInput:
    ticket: Ticket


@dataclass(frozen=True)
class ReplyDraft:
    ticket_id: str
    body: str


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: object


@dataclass(frozen=True)
class ToolResult:
    decision: PolicyDecision
    output: object | None = None
    cost: float = 0.0


@dataclass(frozen=True)
class Tool(Generic[InputT, OutputT]):
    name: str
    input_type: type[InputT]
    output_type: type[OutputT]
    handler: Callable[[InputT], OutputT]

    def execute(self, arguments: object) -> OutputT:
        if not isinstance(arguments, self.input_type):
            raise TypeError(
                f"Tool '{self.name}' expects {self.input_type.__name__}, "
                f"got {type(arguments).__name__}."
            )
        output = self.handler(arguments)
        if not isinstance(output, self.output_type):
            raise TypeError(
                f"Tool '{self.name}' returned {type(output).__name__}, "
                f"expected {self.output_type.__name__}."
            )
        return output


class ToolRegistry:
    def __init__(
        self,
        policy: ActionPolicy,
        tools: list[Tool[Any, Any]],
        costs: dict[str, float] | None = None,
    ) -> None:
        self._policy = policy
        self._costs = dict(costs or {})
        self._tools: dict[str, Tool[Any, Any]] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"Duplicate tool name: {tool.name}")
            self._tools[tool.name] = tool

    def invoke(self, call: ToolCall) -> ToolResult:
        decision = self._policy.evaluate(ActionRequest(call.name))
        if decision.status != "allow":
            return ToolResult(decision)

        tool = self._tools.get(call.name)
        if tool is None:
            raise LookupError(f"Policy allows '{call.name}', but no such tool is registered.")
        output = tool.execute(call.arguments)
        cost = self._costs.get(call.name, 0.0)
        return ToolResult(decision, output, cost)


def create_mock_tool_registry(policy: ActionPolicy) -> ToolRegistry:
    tickets = {
        "T-1001": Ticket(
            ticket_id="T-1001",
            subject="Unable to access my account",
            body="I reset my password but still cannot sign in.",
        )
    }

    def read_ticket(arguments: ReadTicketInput) -> Ticket:
        try:
            return tickets[arguments.ticket_id]
        except KeyError as error:
            raise KeyError(f"Unknown mock ticket: {arguments.ticket_id}") from error

    def draft_reply(arguments: DraftReplyInput) -> ReplyDraft:
        return ReplyDraft(
            ticket_id=arguments.ticket.ticket_id,
            body=(
                f"Thanks for contacting support about '{arguments.ticket.subject}'. "
                "We will review the sign-in issue and follow up."
            ),
        )

    return ToolRegistry(
        policy,
        [
            Tool("read_ticket", ReadTicketInput, Ticket, read_ticket),
            Tool("draft_reply", DraftReplyInput, ReplyDraft, draft_reply),
        ],
        costs={"read_ticket": 0.12, "draft_reply": 0.35},
    )