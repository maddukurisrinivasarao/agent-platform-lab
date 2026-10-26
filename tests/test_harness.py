import unittest

from agent_platform_lab.credentials import CredentialBroker
from agent_platform_lab.harness import PlannerHarness, ScriptedHarness
from agent_platform_lab.policy import ActionPolicy
from agent_platform_lab.tools import ReadTicketInput, ToolCall, create_mock_tool_registry
from agent_platform_lab.workflow import SupportTicketWorkflow


def make_tools(approval_required=frozenset()):
    policy = ActionPolicy(
        allowed_actions=frozenset({"read_ticket", "draft_reply"}),
        approval_required=frozenset(approval_required),
    )
    return create_mock_tool_registry(policy, credential_broker=CredentialBroker())


class HarnessTests(unittest.TestCase):
    def test_both_harnesses_complete_with_same_reply_and_cost(self):
        scripted = ScriptedHarness(SupportTicketWorkflow(make_tools())).run("T-1001")
        planned = PlannerHarness(make_tools()).run("T-1001")

        for result in (scripted, planned):
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.task_state.status, "completed")
            self.assertAlmostEqual(result.total_cost, 0.47)
        self.assertEqual(scripted.draft, planned.draft)

    def test_planner_harness_waits_for_approval(self):
        result = PlannerHarness(make_tools({"draft_reply"})).run("T-1001")

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.task_state.status, "waiting_for_approval")
        self.assertIsNone(result.draft)

    def test_planner_harness_stops_repeating_planner(self):
        def stuck_planner(ticket_id, history):
            return ToolCall("read_ticket", ReadTicketInput(ticket_id))

        result = PlannerHarness(make_tools(), stuck_planner).run("T-1001")

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.task_state.status, "failed")
        self.assertTrue(result.task_state.loop_detected)
        self.assertIn("Loop detected", result.reason)
        self.assertEqual(len(result.trace_events), 3)

    def test_trace_records_credential_id_but_not_token(self):
        result = PlannerHarness(make_tools()).run("T-1001")

        for event in result.trace_events:
            self.assertTrue(event.payload["credential_id"].startswith("cred-"))
            self.assertNotIn("mock-", str(event.payload))


if __name__ == "__main__":
    unittest.main()
