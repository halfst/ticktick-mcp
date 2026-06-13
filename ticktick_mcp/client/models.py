"""Typed result models the client returns (DESIGN.md §1, §4).

These parse raw v2 JSON (camelCase, with all the wire fields) into clean,
serializable objects the server layer can hand to an MCP host without ever seeing
a raw payload. The date contract is applied here via :mod:`.dates`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from .dates import decode_due

__all__ = ["Task", "Project", "Tag", "Column", "Member", "TaskKind"]

# v2 task `kind` values seen on the wire: "TEXT" (normal), "CHECKLIST", "NOTE".
TaskKind = str


class Task(BaseModel):
    """A TickTick task (or note, when ``kind == "NOTE"``)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    project_id: str | None = None
    title: str = ""
    content: str | None = None
    kind: TaskKind = "TEXT"
    priority: int = 0
    status: int = 0  # 0 = open, 2 = completed (v2 convention)
    is_all_day: bool = False
    # ``date`` when all-day, aware ``datetime`` when timed, ``None`` when undated.
    due: date | datetime | None = None
    timezone: str | None = None
    tags: list[str] = []
    column_id: str | None = None
    assignee: int | None = None
    etag: str | None = None

    @property
    def is_note(self) -> bool:
        return self.kind == "NOTE"

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "Task":
        is_all_day = bool(raw.get("isAllDay"))
        tz = raw.get("timeZone")
        return cls(
            id=raw["id"],
            project_id=raw.get("projectId"),
            title=raw.get("title") or "",
            content=raw.get("content"),
            kind=raw.get("kind") or "TEXT",
            priority=raw.get("priority") or 0,
            status=raw.get("status") or 0,
            is_all_day=is_all_day,
            due=decode_due(raw.get("dueDate"), is_all_day, tz),
            timezone=tz,
            tags=list(raw.get("tags") or []),
            column_id=raw.get("columnId"),
            assignee=raw.get("assignee") or None,
            etag=raw.get("etag"),
        )


class Project(BaseModel):
    """A TickTick project (list)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str = ""
    color: str | None = None
    group_id: str | None = None
    closed: bool = False
    kind: str | None = None
    etag: str | None = None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "Project":
        return cls(
            id=raw["id"],
            name=raw.get("name") or "",
            color=raw.get("color"),
            group_id=raw.get("groupId"),
            closed=bool(raw.get("closed")),
            kind=raw.get("kind"),
            etag=raw.get("etag"),
        )


class Tag(BaseModel):
    """A TickTick tag. Identified by its lowercased ``name``; ``label`` is display."""

    model_config = ConfigDict(extra="ignore")

    name: str
    label: str = ""
    color: str | None = None
    raw_name: str | None = None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "Tag":
        return cls(
            name=raw["name"],
            label=raw.get("label") or raw.get("rawName") or raw["name"],
            color=raw.get("color"),
            raw_name=raw.get("rawName"),
        )


class Column(BaseModel):
    """A kanban column (swimlane) within a project."""

    model_config = ConfigDict(extra="ignore")

    id: str
    project_id: str | None = None
    name: str = ""
    sort_order: int | None = None
    etag: str | None = None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "Column":
        return cls(
            id=raw["id"],
            project_id=raw.get("projectId"),
            name=raw.get("name") or "",
            sort_order=raw.get("sortOrder"),
            etag=raw.get("etag"),
        )


class Member(BaseModel):
    """A member of a shared project (for resolving a person to an assignee id)."""

    model_config = ConfigDict(extra="ignore")

    user_id: int
    display_name: str = ""
    username: str | None = None
    is_owner: bool = False
    permission: str | None = None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "Member":
        return cls(
            user_id=raw["userId"],
            display_name=raw.get("displayName") or "",
            username=raw.get("username"),
            is_owner=bool(raw.get("isOwner")),
            permission=raw.get("permission"),
        )
