import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from agent_platform_lab.state import TaskState
from agent_platform_lab.worker import Worker, WorkerConfig, main


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.env = {"AGENT_STATE_DIR": self._tmpdir.name}

    def run_main(self, *argv, **env):
        output = io.StringIO()
        with mock.patch.dict(os.environ, {**self.env, **env}, clear=True), redirect_stdout(output):
            code = main(list(argv))
        return code, [json.loads(line) for line in output.getvalue().splitlines()]

    def test_config_reads_environment(self):
        config = WorkerConfig.from_env(
            {"AGENT_HARNESS": "scripted", "AGENT_APPROVAL_REQUIRED": "draft_reply", "AGENT_STATE_DIR": "/data"}
        )

        self.assertEqual(config.harness, "scripted")
        self.assertEqual(config.approval_required, frozenset({"draft_reply"}))
        self.assertEqual(config.state_dir, Path("/data"))

    def test_config_rejects_unknown_harness(self):
        with self.assertRaises(ValueError):
            WorkerConfig.from_env({"AGENT_HARNESS": "unknown"})

    def test_run_processes_ticket_and_checkpoints_result(self):
        code, lines = self.run_main("run", "T-1001")

        self.assertEqual(code, 0)
        self.assertEqual(lines[0]["task_status"], "completed")
        self.assertAlmostEqual(lines[0]["total_cost"], 0.47)
        stored = Worker(WorkerConfig.from_env(self.env)).checkpoints.load("ticket:T-1001")
        self.assertEqual(stored.status, "completed")

    def test_recover_reruns_interrupted_task_only(self):
        worker = Worker(WorkerConfig.from_env(self.env))
        worker.checkpoints.save(TaskState(task_id="ticket:T-1001", status="running", current_tool="draft_reply"))
        worker.checkpoints.save(TaskState(task_id="ticket:T-2002", status="waiting_for_approval"))

        code, lines = self.run_main("recover")

        self.assertEqual(code, 0)
        self.assertEqual(lines[0], {"event": "recovery_started", "interrupted": 1})
        self.assertEqual(lines[1]["task_id"], "ticket:T-1001")
        self.assertEqual(lines[1]["task_status"], "completed")
        self.assertEqual(worker.checkpoints.load("ticket:T-2002").status, "waiting_for_approval")

    def test_blocked_task_exits_non_zero(self):
        code, lines = self.run_main("run", "T-1001", AGENT_ALLOWED_ACTIONS="read_ticket")

        self.assertEqual(code, 1)
        self.assertEqual(lines[0]["task_status"], "blocked")

    def test_crashing_ticket_is_marked_failed_and_not_recovered(self):
        code, lines = self.run_main("run", "T-9999", "T-1001")

        self.assertEqual(code, 1)
        self.assertEqual(lines[0]["task_status"], "failed")
        self.assertIn("T-9999", lines[0]["reason"])
        self.assertEqual(lines[1]["task_status"], "completed")
        self.assertEqual(Worker(WorkerConfig.from_env(self.env)).interrupted_tasks(), ())

    def test_bad_configuration_is_logged_as_json(self):
        code, lines = self.run_main("status", AGENT_HARNESS="unknown")

        self.assertEqual(code, 2)
        self.assertEqual(lines[0]["event"], "worker_error")
        self.assertIn("AGENT_HARNESS", lines[0]["message"])


if __name__ == "__main__":
    unittest.main()
