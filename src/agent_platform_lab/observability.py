"""Lightweight observability primitives for workflow traces, costs, and loop detection."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable


@dataclass(frozen=True)
class TraceEvent:
    event_id: str
    task_id: str
    tool_name: str
    status: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class CostEntry:
    task_id: str
    tool_name: str
    amount: float
    currency: str = "USD"
    description: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class LoopAlert:
    tool_name: str
    occurrences: int
    threshold: int


class TraceStore:
    def __init__(self) -> None:
        self._events: list[TraceEvent] = []

    def record(
        self,
        *,
        task_id: str,
        tool_name: str,
        status: str,
        message: str,
        payload: dict[str, Any] | None = None,
        event_id: str | None = None,
    ) -> TraceEvent:
        event = TraceEvent(
            event_id=event_id or f"{task_id}:{tool_name}:{len(self._events) + 1}",
            task_id=task_id,
            tool_name=tool_name,
            status=status,
            message=message,
            payload=payload or {},
        )
        self._events.append(event)
        return event

    def events_for_task(self, task_id: str) -> tuple[TraceEvent, ...]:
        return tuple(event for event in self._events if event.task_id == task_id)

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        return tuple(self._events)

    def __iter__(self):
        return iter(self._events)


class CostTracker:
    def __init__(self) -> None:
        self._entries: list[CostEntry] = []

    def record(
        self,
        *,
        task_id: str,
        tool_name: str,
        amount: float,
        currency: str = "USD",
        description: str = "",
    ) -> CostEntry:
        entry = CostEntry(
            task_id=task_id,
            tool_name=tool_name,
            amount=float(amount),
            currency=currency,
            description=description,
        )
        self._entries.append(entry)
        return entry

    def total_for_task(self, task_id: str) -> float:
        return sum(entry.amount for entry in self._entries if entry.task_id == task_id)

    @property
    def entries(self) -> tuple[CostEntry, ...]:
        return tuple(self._entries)

    @property
    def total(self) -> float:
        return sum(entry.amount for entry in self._entries)


class LoopDetector:
    def __init__(self, threshold: int = 3) -> None:
        self.threshold = threshold

    def detect(self, events: Iterable[TraceEvent]) -> LoopAlert | None:
        counts = Counter(event.tool_name for event in events)
        repeated = max(counts.items(), key=lambda item: item[1], default=(None, 0))
        if repeated[0] is None or repeated[1] < self.threshold:
            return None
        return LoopAlert(tool_name=repeated[0], occurrences=repeated[1], threshold=self.threshold)

    def check_task(self, task_id: str, trace_store: TraceStore) -> LoopAlert | None:
        return self.detect(trace_store.events_for_task(task_id))
