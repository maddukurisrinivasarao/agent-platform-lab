"""Small allow-list policy boundary for proposed agent actions."""

from dataclasses import dataclass
from typing import Literal

DecisionStatus = Literal["allow", "approval_required", "deny"]


@dataclass(frozen=True)
class ActionRequest:
    name: str


@dataclass(frozen=True)
class PolicyDecision:
    status: DecisionStatus
    reason: str


@dataclass(frozen=True)
class ActionPolicy:
    allowed_actions: frozenset[str]
    approval_required: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.approval_required.issubset(self.allowed_actions):
            raise ValueError("Actions requiring approval must also be allow-listed.")

    def evaluate(self, action: ActionRequest) -> PolicyDecision:
        if action.name not in self.allowed_actions:
            return PolicyDecision("deny", f"Action '{action.name}' is not allow-listed.")
        if action.name in self.approval_required:
            return PolicyDecision("approval_required", f"Action '{action.name}' requires approval.")
        return PolicyDecision("allow", f"Action '{action.name}' is allow-listed.")
