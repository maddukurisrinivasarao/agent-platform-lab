import os
import tempfile
import unittest

from agent_platform_lab.policy import ActionPolicy
from agent_platform_lab.state import CheckpointStore, TaskState
from agent_platform_lab.tools import create_mock_tool_registry
from agent_platform_lab.workflow import SupportTicketWorkflow


class TaskStateTests(unittest.TestCase):
    def test_waits_for_approval_when_tool_requires_it(self):
        policy = ActionPolicy(
            allowed_actions=frozenset({"read_ticket", "draft_reply"}),
            approval_required=frozenset({"draft_reply"}),
        )
        tools = create_mock_tool_registry(policy)
        workflow = SupportTicketWorkflow(tools)

        result = workflow.run("T-1001")

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.task_state.status, "waiting_for_approval")
        self.assertIn("draft_reply", result.reason)

    def test_checkpoint_store_persists_task_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(os.path.join(tmpdir, "state.json"))
            task = TaskState(task_id="task-1", status="running", current_tool="read_ticket")

            store.save(task)
            loaded = store.load("task-1")

            self.assertEqual(loaded.task_id, "task-1")
            self.assertEqual(loaded.status, "running")
            self.assertEqual(loaded.current_tool, "read_ticket")


if __name__ == "__main__":
    unittest.main()
