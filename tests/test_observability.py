import unittest

from agent_platform_lab.observability import CostTracker, LoopDetector, TraceStore
from agent_platform_lab.policy import ActionPolicy
from agent_platform_lab.tools import create_mock_tool_registry
from agent_platform_lab.workflow import SupportTicketWorkflow


class ObservabilityTests(unittest.TestCase):
    def test_trace_store_tracks_tool_calls(self):
        store = TraceStore()
        event = store.record(task_id="task-1", tool_name="read_ticket", status="started", message="Reading ticket")

        self.assertEqual(event.task_id, "task-1")
        self.assertEqual(store.events_for_task("task-1")[0].tool_name, "read_ticket")

    def test_cost_tracker_totals_task_cost(self):
        tracker = CostTracker()
        tracker.record(task_id="task-1", tool_name="read_ticket", amount=0.12)
        tracker.record(task_id="task-1", tool_name="draft_reply", amount=0.35)

        self.assertEqual(tracker.total_for_task("task-1"), 0.47)

    def test_loop_detector_flags_repeated_tool_usage(self):
        trace_store = TraceStore()
        for _ in range(3):
            trace_store.record(task_id="task-1", tool_name="draft_reply", status="started", message="Drafting")

        detector = LoopDetector(threshold=2)
        alert = detector.check_task("task-1", trace_store)

        self.assertIsNotNone(alert)
        self.assertEqual(alert.tool_name, "draft_reply")
        self.assertEqual(alert.occurrences, 3)

    def test_workflow_records_cost_and_trace(self):
        policy = ActionPolicy(allowed_actions=frozenset({"read_ticket", "draft_reply"}))
        tools = create_mock_tool_registry(policy)
        trace_store = TraceStore()
        cost_tracker = CostTracker()
        workflow = SupportTicketWorkflow(
            tools,
            trace_store=trace_store,
            cost_tracker=cost_tracker,
            loop_detector=LoopDetector(threshold=3),
        )

        result = workflow.run("T-1001")

        self.assertEqual(result.status, "completed")
        self.assertGreater(result.total_cost, 0.0)
        self.assertTrue(len(result.trace_events) >= 2)
        self.assertEqual(cost_tracker.total_for_task("ticket:T-1001"), result.total_cost)


if __name__ == "__main__":
    unittest.main()
