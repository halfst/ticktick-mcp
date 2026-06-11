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
from ..client.models import Project, Tag, Task

__all__ = [
    "create_task",
    "create_note",
    "create_project",
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
) -> dict[str, Any]:
    task = client.create_task(
        title,
        project_id=project_id,
        content=content,
        due=parse_due(due),
        priority=priority,
        timezone=timezone,
    )
    return _task_dict(task)


@_safe
def create_note(
    client: TickTickClient,
    *,
    title: str,
    content: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    return _task_dict(client.create_note(title, content, project_id=project_id))


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
    tasks = client.list_tasks(
        project_id=project_id,
        due_today=due_today,
        overdue=overdue,
        include_completed=include_completed,
    )
    return {"tasks": [_task_dict(t) for t in tasks]}
