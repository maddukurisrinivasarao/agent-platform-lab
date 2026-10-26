import unittest
from datetime import datetime, timedelta, timezone

from agent_platform_lab.credentials import CredentialBroker, CredentialError
from agent_platform_lab.policy import ActionPolicy
from agent_platform_lab.tools import ReadTicketInput, ToolCall, create_mock_tool_registry


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


class CredentialBrokerTests(unittest.TestCase):
    def test_issued_credential_validates_for_its_scope(self):
        broker = CredentialBroker(ttl_seconds=30)
        credential = broker.issue("read_ticket")

        self.assertEqual(broker.validate(credential.token, "read_ticket"), credential)
        self.assertTrue(credential.token.startswith("mock-"))
        self.assertNotIn(credential.token, repr(credential))

    def test_rejects_wrong_scope(self):
        broker = CredentialBroker()
        credential = broker.issue("read_ticket")

        with self.assertRaisesRegex(CredentialError, "scoped to 'read_ticket'"):
            broker.validate(credential.token, "draft_reply")

    def test_rejects_expired_credential(self):
        clock = FakeClock()
        broker = CredentialBroker(ttl_seconds=30, clock=clock)
        credential = broker.issue("read_ticket")

        clock.now += timedelta(seconds=31)

        with self.assertRaisesRegex(CredentialError, "expired"):
            broker.validate(credential.token, "read_ticket")
        self.assertEqual(broker.active_count, 0)

    def test_rejects_revoked_credential(self):
        broker = CredentialBroker()
        credential = broker.issue("read_ticket")
        broker.revoke(credential.credential_id)

        with self.assertRaisesRegex(CredentialError, "unknown or revoked"):
            broker.validate(credential.token, "read_ticket")


class RegistryCredentialTests(unittest.TestCase):
    def make_tools(self, broker):
        policy = ActionPolicy(allowed_actions=frozenset({"read_ticket"}))
        return create_mock_tool_registry(policy, credential_broker=broker)

    def test_allowed_call_uses_single_use_credential(self):
        broker = CredentialBroker()

        result = self.make_tools(broker).invoke(ToolCall("read_ticket", ReadTicketInput("T-1001")))

        self.assertEqual(result.decision.status, "allow")
        self.assertTrue(result.credential_id.startswith("cred-"))
        self.assertEqual(broker.active_count, 0)

    def test_expired_credential_blocks_tool_execution(self):
        broker = CredentialBroker(ttl_seconds=0)

        result = self.make_tools(broker).invoke(ToolCall("read_ticket", ReadTicketInput("T-1001")))

        self.assertEqual(result.decision.status, "deny")
        self.assertIn("expired", result.decision.reason)
        self.assertIsNone(result.output)

    def test_denied_call_never_gets_a_credential(self):
        broker = CredentialBroker()

        result = self.make_tools(broker).invoke(ToolCall("draft_reply", ReadTicketInput("T-1001")))

        self.assertEqual(result.decision.status, "deny")
        self.assertIsNone(result.credential_id)


if __name__ == "__main__":
    unittest.main()
