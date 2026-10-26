import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest import mock

from agent_platform_lab.evaluation import (
    HARNESSES,
    EvaluationSuite,
    evaluate_scenarios,
    load_scenarios,
    main,
)


class EvaluationTests(unittest.TestCase):
    def write_suite(self, data):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / "suite.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def failing_suite(self):
        suite = load_scenarios()
        broken = replace(suite.scenarios[0], expected_workflow_status="blocked")
        return EvaluationSuite(suite.version, (broken,))

    def test_versioned_suite_passes_on_every_harness(self):
        report = evaluate_scenarios()

        self.assertEqual(report.scenario_version, "1.0")
        self.assertEqual(report.metrics.total, 2 * len(HARNESSES))
        self.assertEqual(report.metrics.failed, 0)
        self.assertEqual(report.metrics.pass_rate, 1.0)
        self.assertEqual({result.harness for result in report.results}, set(HARNESSES))

    def test_wrong_expectation_is_reported_as_failure(self):
        report = evaluate_scenarios(self.failing_suite())

        self.assertEqual(report.metrics.passed, 0)
        self.assertEqual(report.metrics.pass_rate, 0.0)
        for result in report.results:
            self.assertFalse(result.passed)
            self.assertIn("workflow status: expected blocked, got completed", result.failed_checks)

    def test_reply_and_reason_text_are_checked(self):
        suite = load_scenarios()
        completes, waits = suite.scenarios
        broken = EvaluationSuite(
            suite.version,
            (
                replace(completes, expected_reply_contains="refund issued"),
                replace(waits, expected_reason_contains="is not allow-listed"),
            ),
        )

        checks = [check for result in evaluate_scenarios(broken).results for check in result.failed_checks]

        self.assertIn("reply does not contain 'refund issued'", checks)
        self.assertIn("reason does not contain 'is not allow-listed'", checks)

    def test_malformed_suites_are_rejected(self):
        for data in ([], {"version": "1.0"}, {"version": "1.0", "scenarios": []}, {"scenarios": [{}]}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                load_scenarios(self.write_suite(data))

    def test_scenario_missing_fields_names_them(self):
        path = self.write_suite({"version": "1.0", "scenarios": [{"id": "incomplete", "ticket_id": "T-1001"}]})

        with self.assertRaisesRegex(ValueError, "'incomplete' is missing required fields: allowed_actions"):
            load_scenarios(path)

    def test_main_exit_codes(self):
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(), 0)
        self.assertIn("pass rate 100%", output.getvalue())

        with mock.patch("agent_platform_lab.evaluation.load_scenarios", return_value=self.failing_suite()):
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(), 1)
        self.assertIn("FAIL ticket-reply-completes", output.getvalue())


if __name__ == "__main__":
    unittest.main()
