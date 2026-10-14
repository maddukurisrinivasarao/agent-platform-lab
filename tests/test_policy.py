import unittest

from agent_platform_lab.policy import ActionPolicy, ActionRequest, PolicyDecision


class ActionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = ActionPolicy(
            allowed_actions=frozenset({"read_ticket", "send_reply"}),
            approval_required=frozenset({"send_reply"}),
        )

    def test_allows_allow_listed_action(self):
        decision = self.policy.evaluate(ActionRequest("read_ticket"))
        self.assertEqual(decision, PolicyDecision("allow", "Action 'read_ticket' is allow-listed."))

    def test_requires_approval_for_sensitive_action(self):
        decision = self.policy.evaluate(ActionRequest("send_reply"))
        self.assertEqual(decision.status, "approval_required")

    def test_denies_action_outside_allow_list(self):
        decision = self.policy.evaluate(ActionRequest("delete_account"))
        self.assertEqual(decision.status, "deny")

    def test_rejects_approval_rule_for_non_allow_listed_action(self):
        with self.assertRaises(ValueError):
            ActionPolicy(
                allowed_actions=frozenset({"read_ticket"}),
                approval_required=frozenset({"send_reply"}),
            )


if __name__ == "__main__":
    unittest.main()
