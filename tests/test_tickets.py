import tempfile
import unittest
from pathlib import Path

from agent_platform_lab.tickets import load_tickets_xml

TICKETS_FILE = Path(__file__).resolve().parents[1] / "data" / "tickets.xml"


class TicketXmlTests(unittest.TestCase):
    def write_xml(self, text):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / "tickets.xml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_loads_repository_tickets(self):
        tickets = load_tickets_xml(TICKETS_FILE)

        self.assertEqual(sorted(tickets), ["T-1001", "T-1002", "T-1003", "T-1004", "T-1005"])
        self.assertEqual(tickets["T-1001"].subject, "Unable to access my account")
        self.assertEqual(tickets["T-1001"].body, "I reset my password but still cannot sign in.")

    def test_loads_large_generated_file(self):
        tickets = load_tickets_xml(TICKETS_FILE.with_name("tickets_large.xml"))

        self.assertGreaterEqual(len(tickets), 100)
        self.assertIn("T-2001", tickets)

    def test_rejects_bad_files(self):
        cases = {
            "not XML": "<tickets><ticket>",
            "wrong root": "<orders/>",
            "missing body": '<tickets><ticket id="T-1"><subject>Hi</subject></ticket></tickets>',
            "missing id": "<tickets><ticket><subject>Hi</subject><body>Text</body></ticket></tickets>",
            "duplicate id": (
                '<tickets><ticket id="T-1"><subject>A</subject><body>B</body></ticket>'
                '<ticket id="T-1"><subject>C</subject><body>D</body></ticket></tickets>'
            ),
        }
        for name, text in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                load_tickets_xml(self.write_xml(text))


if __name__ == "__main__":
    unittest.main()
