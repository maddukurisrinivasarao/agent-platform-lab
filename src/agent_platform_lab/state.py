"""Task state and checkpoint helpers for workflow approval tracking."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

TaskStatus = Literal[
    "created",
    "running",
    "waiting_for_approval",
    "approved",
    "completed",
    "blocked",
    "failed",
    "rejected",
]


@dataclass
class TaskState:
    task_id: str
    status: TaskStatus = "created"
    description: str = ""
    current_tool: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    approvals: list[str] = field(default_factory=list)
    total_cost: float = 0.0
    loop_detected: bool = False
    trace_events: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def transition(
        self,
        new_status: TaskStatus,
        *,
        description: str | None = None,
        current_tool: str | None = None,
        payload: dict[str, Any] | None = None,
        total_cost: float | None = None,
        loop_detected: bool | None = None,
    ) -> "TaskState":
        self.status = new_status
        if description is not None:
            self.description = description
        if current_tool is not None:
            self.current_tool = current_tool
        if payload is not None:
            self.payload = payload
        if total_cost is not None:
            self.total_cost = total_cost
        if loop_detected is not None:
            self.loop_detected = loop_detected
        self.updated_at = datetime.now(timezone.utc).isoformat()
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "description": self.description,
            "current_tool": self.current_tool,
            "payload": self.payload,
            "approvals": self.approvals,
            "total_cost": self.total_cost,
            "loop_detected": self.loop_detected,
            "trace_events": self.trace_events,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "TaskState":
        return cls(
            task_id=values["task_id"],
            status=values.get("status", "created"),
            description=values.get("description", ""),
            current_tool=values.get("current_tool"),
            payload=values.get("payload", {}),
            approvals=values.get("approvals", []),
            total_cost=float(values.get("total_cost", 0.0) or 0.0),
            loop_detected=bool(values.get("loop_detected", False)),
            trace_events=list(values.get("trace_events", [])),
            created_at=values.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=values.get("updated_at", datetime.now(timezone.utc).isoformat()),
        )


class CheckpointStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read_store(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as handle:
            raw = handle.read().strip()
            if not raw:
                return {}
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError(f"Checkpoint store at '{self.path}' is malformed.")
            return data

    def _write_store(self, store: dict[str, dict[str, Any]]) -> None:
        # Write to a temp file and rename so a crash mid-write never leaves a truncated store.
        fd, temp_path = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(store, handle, indent=2, sort_keys=True)
            os.replace(temp_path, self.path)
        except BaseException:
            Path(temp_path).unlink(missing_ok=True)
            raise

    def save(self, task: TaskState) -> TaskState:
        store = self._read_store()
        store[task.task_id] = task.to_dict()
        self._write_store(store)
        return task

    def load(self, task_id: str) -> TaskState | None:
        store = self._read_store()
        value = store.get(task_id)
        if value is None:
            return None
        return TaskState.from_dict(value)

    def all(self) -> tuple[TaskState, ...]:
        return tuple(TaskState.from_dict(value) for value in self._read_store().values())

    def delete(self, task_id: str) -> None:
        store = self._read_store()
        store.pop(task_id, None)
        self._write_store(store)
