"""Load synthetic support tickets from an XML file."""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from pathlib import Path

from agent_platform_lab.tools import Ticket


def load_tickets_xml(path: str | Path) -> dict[str, Ticket]:
    """Read <tickets><ticket id="..."><subject/><body/></ticket></tickets> into a dict keyed by ID."""
    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError as error:
        raise ValueError(f"Ticket file '{path}' is not valid XML: {error}") from error
    if root.tag != "tickets":
        raise ValueError(f"Ticket file '{path}' must have a <tickets> root element.")

    tickets: dict[str, Ticket] = {}
    for element in root.findall("ticket"):
        ticket_id = (element.get("id") or "").strip()
        subject = (element.findtext("subject") or "").strip()
        body = (element.findtext("body") or "").strip()
        if not ticket_id or not subject or not body:
            raise ValueError(f"Ticket {ticket_id or '<no id>'} in '{path}' needs an id, subject, and body.")
        if ticket_id in tickets:
            raise ValueError(f"Duplicate ticket id {ticket_id} in '{path}'.")
        tickets[ticket_id] = Ticket(ticket_id=ticket_id, subject=subject, body=body)
    return tickets
