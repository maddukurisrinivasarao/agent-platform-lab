"""Run versioned regression scenarios against the support-ticket workflow."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from agent_platform_lab.credentials import CredentialBroker
from agent_platform_lab.harness import HarnessAdapter, PlannerHarness, ScriptedHarness
from agent_platform_lab.policy import ActionPolicy
from agent_platform_lab.tools import ToolRegistry, create_mock_tool_registry
from agent_platform_lab.workflow import SupportTicketWorkflow

WorkflowStatus = Literal["completed", "blocked"]

# Every scenario runs once per harness so both agent loops are held to the same expectations.
HARNESSES: dict[str, Callable[[ToolRegistry], HarnessAdapter]] = {
    "scripted": lambda tools: ScriptedHarness(SupportTicketWorkflow(tools)),
    "planner": PlannerHarness,
}


_REQUIRED_SCENARIO_KEYS = (
    "id",
    "ticket_id",
    "allowed_actions",
    "expected_workflow_status",
    "expected_task_status",
)


@dataclass(frozen=True)
class EvaluationScenario:
    scenario_id: str
    ticket_id: str
    allowed_actions: tuple[str, ...]
    approval_required: tuple[str, ...]
    expected_workflow_status: WorkflowStatus
    expected_task_status: str
    expected_reply_contains: str | None = None
    expected_reason_contains: str | None = None


@dataclass(frozen=True)
class EvaluationSuite:
    version: str
    scenarios: tuple[EvaluationScenario, ...]


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    harness: str
    passed: bool
    expected_workflow_status: str
    actual_workflow_status: str
    expected_task_status: str
    actual_task_status: str
    failed_checks: tuple[str, ...]


@dataclass(frozen=True)
class EvaluationMetrics:
    total: int
    passed: int
    failed: int
    completed: int
    blocked: int
    waiting_for_approval: int
    pass_rate: float


@dataclass(frozen=True)
class EvaluationReport:
    scenario_version: str
    results: tuple[ScenarioResult, ...]
    metrics: EvaluationMetrics


def _read_scenario(value: dict[str, Any]) -> EvaluationScenario:
    missing = [key for key in _REQUIRED_SCENARIO_KEYS if key not in value]
    if missing:
        raise ValueError(
            f"Scenario {value.get('id', '<no id>')!r} is missing required fields: {', '.join(missing)}."
        )
    return EvaluationScenario(
        scenario_id=value["id"],
        ticket_id=value["ticket_id"],
        allowed_actions=tuple(value["allowed_actions"]),
        approval_required=tuple(value.get("approval_required", [])),
        expected_workflow_status=value["expected_workflow_status"],
        expected_task_status=value["expected_task_status"],
        expected_reply_contains=value.get("expected_reply_contains"),
        expected_reason_contains=value.get("expected_reason_contains"),
    )


def load_scenarios(path: str | Path | None = None) -> EvaluationSuite:
    """Load an evaluation suite from JSON; defaults to the repository's v1 suite."""
    scenario_path = (
        Path(path)
        if path is not None
        else Path(__file__).resolve().parents[2] / "evals" / "scenarios" / "v1.json"
    )
    data = json.loads(scenario_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("scenarios"), list):
        raise ValueError(f"Evaluation suite at '{scenario_path}' is malformed.")
    if not data.get("version") or not data["scenarios"]:
        raise ValueError(f"Evaluation suite at '{scenario_path}' needs a version and scenarios.")
    return EvaluationSuite(
        version=data["version"],
        scenarios=tuple(_read_scenario(scenario) for scenario in data["scenarios"]),
    )


def _evaluate_scenario(scenario: EvaluationScenario, harness: str) -> ScenarioResult:
    policy = ActionPolicy(
        allowed_actions=frozenset(scenario.allowed_actions),
        approval_required=frozenset(scenario.approval_required),
    )
    tools = create_mock_tool_registry(policy, credential_broker=CredentialBroker(ttl_seconds=30))
    result = HARNESSES[harness](tools).run(scenario.ticket_id)
    task_status = result.task_state.status if result.task_state is not None else "missing"
    failed_checks: list[str] = []

    if result.status != scenario.expected_workflow_status:
        failed_checks.append(
            f"workflow status: expected {scenario.expected_workflow_status}, got {result.status}"
        )
    if task_status != scenario.expected_task_status:
        failed_checks.append(
            f"task status: expected {scenario.expected_task_status}, got {task_status}"
        )
    if scenario.expected_reply_contains is not None:
        reply_body = result.draft.body if result.draft is not None else ""
        if scenario.expected_reply_contains not in reply_body:
            failed_checks.append(
                f"reply does not contain {scenario.expected_reply_contains!r}"
            )
    if scenario.expected_reason_contains is not None:
        reason = result.reason or ""
        if scenario.expected_reason_contains not in reason:
            failed_checks.append(
                f"reason does not contain {scenario.expected_reason_contains!r}"
            )

    return ScenarioResult(
        scenario_id=scenario.scenario_id,
        harness=harness,
        passed=not failed_checks,
        expected_workflow_status=scenario.expected_workflow_status,
        actual_workflow_status=result.status,
        expected_task_status=scenario.expected_task_status,
        actual_task_status=task_status,
        failed_checks=tuple(failed_checks),
    )


def evaluate_scenarios(suite: EvaluationSuite | None = None) -> EvaluationReport:
    """Run every scenario and calculate regression metrics from actual outcomes."""
    suite = suite or load_scenarios()
    results = tuple(
        _evaluate_scenario(scenario, harness)
        for scenario in suite.scenarios
        for harness in HARNESSES
    )
    total = len(results)
    passed = sum(result.passed for result in results)
    completed = sum(result.actual_workflow_status == "completed" for result in results)
    blocked = sum(result.actual_workflow_status == "blocked" for result in results)
    waiting_for_approval = sum(
        result.actual_task_status == "waiting_for_approval" for result in results
    )
    metrics = EvaluationMetrics(
        total=total,
        passed=passed,
        failed=total - passed,
        completed=completed,
        blocked=blocked,
        waiting_for_approval=waiting_for_approval,
        pass_rate=passed / total if total else 0.0,
    )
    return EvaluationReport(suite.version, results, metrics)


def main() -> int:
    report = evaluate_scenarios()
    for result in report.results:
        outcome = "PASS" if result.passed else "FAIL"
        print(f"{outcome} {result.scenario_id} [{result.harness}]")
        for check in result.failed_checks:
            print(f"  {check}")

    metrics = report.metrics
    print(
        f"Suite v{report.scenario_version}: {metrics.passed}/{metrics.total} passed; "
        f"pass rate {metrics.pass_rate:.0%}; completed={metrics.completed}, "
        f"blocked={metrics.blocked}, waiting_for_approval={metrics.waiting_for_approval}"
    )
    return 0 if metrics.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())