import unittest

from agent_platform_lab.policy import ActionPolicy
from agent_platform_lab.tools import (
    ReadTicketInput,
    ToolCall,
    create_mock_tool_registry,
)
from agent_platform_lab.workflow import SupportTicketWorkflow


class SupportTicketWorkflowTests(unittest.TestCase):
    def make_policy(self, allowed_actions):
        return ActionPolicy(allowed_actions=frozenset(allowed_actions))

    def test_reads_mock_ticket_and_drafts_reply(self):
        tools = create_mock_tool_registry(
            self.make_policy({"read_ticket", "draft_reply"})
        )

        result = SupportTicketWorkflow(tools).run("T-1001")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.ticket.ticket_id, "T-1001")
        self.assertEqual(result.draft.ticket_id, "T-1001")
        self.assertIn("Unable to access my account", result.draft.body)

    def test_policy_block_prevents_draft_tool_execution(self):
        tools = create_mock_tool_registry(self.make_policy({"read_ticket"}))

        result = SupportTicketWorkflow(tools).run("T-1001")

        self.assertEqual(result.status, "blocked")
        self.assertIsNotNone(result.ticket)
        self.assertIsNone(result.draft)
        self.assertIn("draft_reply", result.reason)

    def test_tool_rejects_wrong_input_type(self):
        tools = create_mock_tool_registry(self.make_policy({"read_ticket"}))

        with self.assertRaises(TypeError):
            tools.invoke(ToolCall("read_ticket", "T-1001"))

    def test_policy_denies_unlisted_tool_before_dispatch(self):
        tools = create_mock_tool_registry(self.make_policy({"read_ticket"}))

        result = tools.invoke(ToolCall("delete_account", ReadTicketInput("T-1001")))

        self.assertEqual(result.decision.status, "deny")
        self.assertIsNone(result.output)


if __name__ == "__main__":
    unittest.main()