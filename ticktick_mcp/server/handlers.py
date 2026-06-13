"""Tool handlers — pure functions the FastMCP layer wraps (DESIGN.md §1).

Each handler takes a :class:`TickTickClient`, shapes inputs, calls one client
method, and returns a JSON-serializable ``dict``. Handlers never touch a raw
endpoint or payload — that all lives in ``client/``.

Errors (DESIGN.md §4): every handler is wrapped so a failure returns a structured
``{"error": {"kind", "message"}}`` object instead of raising — a stable, model-
readable shape. ``kind`` is one of ``input`` (bad arguments), ``auth``, ``api``,
``payload``, or ``internal`` (unexpected; details are not leaked).
"""

from __future__ import annotations

from datetime import date, datetime
from functools import wraps
from typing import Any, Callable

from ..client import APIError, AuthError, PayloadError, TickTickClient, TickTickError
from ..client.models import Column, Member, Project, Tag, Task

__all__ = [
    "create_task",
    "get_task",
    "update_task",
    "complete_task",
    "delete_task",
    "create_note",
    "get_note",
    "list_notes",
    "update_note",
    "delete_note",
    "create_project",
    "get_project",
    "list_projects",
    "list_columns",
    "list_project_members",
    "update_project",
    "delete_project",
    "create_tag",
    "list_tags",
    "rename_tag",
    "delete_tag",
    "add_tag_to_task",
    "remove_tag_from_task",
    "list_tasks",
    "ToolInputError",
]


class ToolInputError(ValueError):
    """Raised when tool arguments are malformed (surfaced as ``kind: "input"``)."""


def _error(kind: str, message: str) -> dict[str, Any]:
    return {"error": {"kind": kind, "message": message}}


def _error_kind(exc: TickTickError) -> str:
    if isinstance(exc, AuthError):
        return "auth"
    if isinstance(exc, PayloadError):
        return "payload"
    if isinstance(exc, APIError):
        return "api"
    return "api"


def _safe(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Wrap a handler so all failures become structured error objects."""

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return fn(*args, **kwargs)
        except ToolInputError as exc:
            return _error("input", str(exc))
        except TickTickError as exc:
            return _error(_error_kind(exc), str(exc))
        except Exception:  # noqa: BLE001 - boundary: never leak internals
            return _error("internal", "An internal error occurred.")

    return wrapper


def parse_due(due: str | None) -> date | datetime | None:
    """Parse a due-date argument into a ``date`` (all-day) or ``datetime`` (timed).

    The date-vs-datetime distinction IS the all-day contract surface (DESIGN.md §3):

    - ``"2026-09-15"``            → a ``date`` → an **all-day** task.
    - ``"2026-09-15T14:30"`` (or with seconds / a ``+0000`` offset) → a ``datetime``
      → a **timed** task.

    Returns ``None`` for an empty/omitted value.
    """
    if due is None:
        return None
    text = due.strip()
    if not text:
        return None
    has_time = "T" in text or (" " in text and ":" in text)
    try:
        return datetime.fromisoformat(text) if has_time else date.fromisoformat(text)
    except ValueError as exc:
        raise ToolInputError(
            f"Invalid due date {due!r}. Use 'YYYY-MM-DD' for an all-day task, or "
            "'YYYY-MM-DDTHH:MM' (optionally with seconds or a timezone offset) for a "
            "timed task."
        ) from exc


def _task_dict(task: Task) -> dict[str, Any]:
    return task.model_dump(mode="json")


def _project_dict(project: Project) -> dict[str, Any]:
    return project.model_dump(mode="json")


def _tag_dict(tag: Tag) -> dict[str, Any]:
    return tag.model_dump(mode="json")


def _column_dict(column: Column) -> dict[str, Any]:
    return column.model_dump(mode="json")


def _member_dict(member: Member) -> dict[str, Any]:
    return member.model_dump(mode="json")


@_safe
def create_task(
    client: TickTickClient,
    *,
    title: str,
    due: str | None = None,
    project_id: str | None = None,
    content: str | None = None,
    priority: int = 0,
    timezone: str | None = None,
    column_id: str | None = None,
    assignee: int | None = None,
) -> dict[str, Any]:
    task = client.create_task(
        title,
        project_id=project_id,
        content=content,
        due=parse_due(due),
        priority=priority,
        timezone=timezone,
        column_id=column_id,
        assignee=assignee,
    )
    return _task_dict(task)


@_safe
def create_note(
    client: TickTickClient,
    *,
    title: str,
    content: str,
    project_id: str | None = None,
    column_id: str | None = None,
    assignee: int | None = None,
) -> dict[str, Any]:
    return _task_dict(client.create_note(title, content, project_id=project_id,
                                         column_id=column_id, assignee=assignee))


@_safe
def create_project(
    client: TickTickClient, *, name: str, color: str | None = None
) -> dict[str, Any]:
    return _project_dict(client.create_project(name, color=color))


@_safe
def list_tasks(
    client: TickTickClient,
    *,
    project_id: str | None = None,
    due_today: bool = False,
    overdue: bool = False,
    include_completed: bool = False,
) -> dict[str, Any]:
    if due_today and overdue:
        raise ToolInputError("Use either 'due_today' or 'overdue', not both.")
    tasks = client.list_tasks(
        project_id=project_id,
        due_today=due_today,
        overdue=overdue,
        include_completed=include_completed,
    )
    return {"tasks": [_task_dict(t) for t in tasks]}


@_safe
def get_task(client: TickTickClient, *, task_id: str) -> dict[str, Any]:
    return _task_dict(client.get_task(task_id))


@_safe
def update_task(
    client: TickTickClient,
    *,
    task_id: str,
    title: str | None = None,
    content: str | None = None,
    due: str | None = None,
    clear_due: bool = False,
    priority: int | None = None,
    project_id: str | None = None,
    tags: list[str] | None = None,
    timezone: str | None = None,
    column_id: str | None = None,
    assignee: int | None = None,
) -> dict[str, Any]:
    parsed_due = parse_due(due)
    if parsed_due is not None and clear_due:
        raise ToolInputError("Provide either 'due' or 'clear_due', not both.")
    task = client.update_task(
        task_id,
        title=title,
        content=content,
        due=parsed_due,
        clear_due=clear_due,
        priority=priority,
        project_id=project_id,
        tags=tags,
        timezone=timezone,
        column_id=column_id,
        assignee=assignee,
    )
    return _task_dict(task)


@_safe
def complete_task(client: TickTickClient, *, task_id: str) -> dict[str, Any]:
    return _task_dict(client.complete_task(task_id))


@_safe
def delete_task(
    client: TickTickClient, *, task_id: str, project_id: str | None = None
) -> dict[str, Any]:
    return _task_dict(client.delete_task(task_id, project_id=project_id))


@_safe
def get_project(client: TickTickClient, *, project_id: str) -> dict[str, Any]:
    return _project_dict(client.get_project(project_id))


@_safe
def list_projects(
    client: TickTickClient, *, include_closed: bool = False
) -> dict[str, Any]:
    projects = client.list_projects(include_closed=include_closed)
    return {"projects": [_project_dict(p) for p in projects]}


@_safe
def list_columns(client: TickTickClient, *, project_id: str) -> dict[str, Any]:
    cols = client.list_columns(project_id)
    return {"columns": [_column_dict(c) for c in cols]}


@_safe
def list_project_members(client: TickTickClient, *, project_id: str) -> dict[str, Any]:
    members = client.list_project_members(project_id)
    return {"members": [_member_dict(m) for m in members]}


@_safe
def update_project(
    client: TickTickClient,
    *,
    project_id: str,
    name: str | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    return _project_dict(client.update_project(project_id, name=name, color=color))


@_safe
def delete_project(client: TickTickClient, *, project_id: str) -> dict[str, Any]:
    return _project_dict(client.delete_project(project_id))


@_safe
def create_tag(
    client: TickTickClient, *, label: str, color: str | None = None
) -> dict[str, Any]:
    return _tag_dict(client.create_tag(label, color=color))


@_safe
def list_tags(client: TickTickClient) -> dict[str, Any]:
    return {"tags": [_tag_dict(t) for t in client.list_tags()]}


@_safe
def rename_tag(
    client: TickTickClient,
    *,
    name: str,
    new_label: str,
    color: str | None = None,
) -> dict[str, Any]:
    return _tag_dict(client.rename_tag(name, new_label, color=color))


@_safe
def delete_tag(client: TickTickClient, *, name: str) -> dict[str, Any]:
    return _tag_dict(client.delete_tag(name))


@_safe
def add_tag_to_task(
    client: TickTickClient, *, task_id: str, tag_name: str
) -> dict[str, Any]:
    return _task_dict(client.add_tag_to_task(task_id, tag_name))


@_safe
def remove_tag_from_task(
    client: TickTickClient, *, task_id: str, tag_name: str
) -> dict[str, Any]:
    return _task_dict(client.remove_tag_from_task(task_id, tag_name))


@_safe
def get_note(client: TickTickClient, *, note_id: str) -> dict[str, Any]:
    return _task_dict(client.get_note(note_id))


@_safe
def list_notes(
    client: TickTickClient,
    *,
    project_id: str | None = None,
    include_completed: bool = False,
) -> dict[str, Any]:
    notes = client.list_notes(
        project_id=project_id,
        include_completed=include_completed,
    )
    return {"notes": [_task_dict(n) for n in notes]}


@_safe
def update_note(
    client: TickTickClient,
    *,
    note_id: str,
    title: str | None = None,
    content: str | None = None,
    project_id: str | None = None,
    column_id: str | None = None,
    assignee: int | None = None,
) -> dict[str, Any]:
    note = client.update_note(
        note_id,
        title=title,
        content=content,
        project_id=project_id,
        column_id=column_id,
        assignee=assignee,
    )
    return _task_dict(note)


@_safe
def delete_note(client: TickTickClient, *, note_id: str) -> dict[str, Any]:
    return _task_dict(client.delete_note(note_id))
