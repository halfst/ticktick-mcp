"""FastMCP server — the public tool interface (DESIGN.md §1, Slice 3).

Tools are thin: each delegates to a handler in :mod:`.handlers`, which calls one
typed client method. The :class:`TickTickClient` is built lazily on first tool
call so that merely *listing* tools (and importing this module) needs no
credentials.

Slice 3 Part A defines the tool contracts (see ``TOOLS.md``) and these reference
tools. Codex fills the remaining tools in Part B against the same pattern.
"""

from __future__ import annotations

import os
from typing import Any

from fastmcp import FastMCP

from ..client import TickTickClient
from ..config import load_config
from . import handlers
from .auth import build_auth

mcp: FastMCP = FastMCP(
    name="ticktick-mcp",
    instructions=(
        "Unofficial TickTick task manager. Create and read tasks, projects, and "
        "Markdown notes. For due dates: pass 'YYYY-MM-DD' for an all-day task, or "
        "'YYYY-MM-DDTHH:MM' for a task at a specific time. Tools return a JSON "
        "object; on failure they return {\"error\": {\"kind\", \"message\"}}."
    ),
)

_client: TickTickClient | None = None


def get_client() -> TickTickClient:
    """Lazily build and cache the shared client (needs credentials in the env)."""
    global _client
    if _client is None:
        _client = TickTickClient(load_config())
    return _client


@mcp.tool
def create_task(
    title: str,
    due: str | None = None,
    project_id: str | None = None,
    content: str | None = None,
    priority: int = 0,
    timezone: str | None = None,
    column_id: str | None = None,
    assignee: int | None = None,
) -> dict[str, Any]:
    """Create a task.

    Args:
        title: The task title.
        due: When the task is due. Pass a bare date 'YYYY-MM-DD' to make it an
            ALL-DAY task (it stays a date — it will not be shifted to a time).
            Pass 'YYYY-MM-DDTHH:MM' (optionally with seconds or a '+0000' offset)
            for a task due at a specific time. Omit for no due date.
        project_id: Target project id. Defaults to the inbox.
        content: Optional task body text.
        priority: 0 none, 1 low, 3 medium, 5 high.
        timezone: IANA zone (e.g. 'America/Chicago') for a TIMED due date; ignored
            for all-day. Defaults to the server's configured timezone.
        column_id: Place the task in this kanban column id (from list_columns).
            Omit to use the project default. Only meaningful in kanban projects.
        assignee: User id to assign the task to (from list_project_members). Omit
            to leave unassigned. Only meaningful in shared projects.

    Returns:
        The created task object, or an {"error": ...} object on failure. An all-day
        task comes back with "is_all_day": true and a date-only "due".
    """
    return handlers.create_task(
        get_client(),
        title=title,
        due=due,
        project_id=project_id,
        content=content,
        priority=priority,
        timezone=timezone,
        column_id=column_id,
        assignee=assignee,
    )


@mcp.tool
def create_note(
    title: str,
    content: str,
    project_id: str | None = None,
    column_id: str | None = None,
    assignee: int | None = None,
) -> dict[str, Any]:
    """Create a Markdown note (a note-kind item whose body is Markdown).

    Args:
        title: The note title.
        content: Markdown body — headings, lists, bold, etc. render in TickTick.
        project_id: Target project id. Defaults to the inbox.
        column_id: Place the task in this kanban column id (from list_columns).
            Omit to use the project default. Only meaningful in kanban projects.
        assignee: User id to assign the task to (from list_project_members). Omit
            to leave unassigned. Only meaningful in shared projects.

    Returns:
        The created note object (with "kind": "NOTE"), or an {"error": ...} object.
    """
    return handlers.create_note(
        get_client(),
        title=title,
        content=content,
        project_id=project_id,
        column_id=column_id,
        assignee=assignee,
    )


@mcp.tool
def create_project(name: str, color: str | None = None) -> dict[str, Any]:
    """Create a project (a list).

    Args:
        name: The project name.
        color: Optional hex color like '#4CA1FF'.

    Returns:
        The created project object, or an {"error": ...} object on failure.
    """
    return handlers.create_project(get_client(), name=name, color=color)


@mcp.tool
def list_tasks(
    project_id: str | None = None,
    due_today: bool = False,
    overdue: bool = False,
    include_completed: bool = False,
) -> dict[str, Any]:
    """List tasks (excludes notes).

    Args:
        project_id: Limit to one project id. Omit for all projects.
        due_today: Only tasks due today (server timezone).
        overdue: Only tasks whose due date is before today.
        include_completed: Also include completed tasks.

    Returns:
        {"tasks": [ ...task objects... ]}, or an {"error": ...} object on failure.
        All-day tasks have a date-only "due"; timed tasks have a datetime "due".
    """
    return handlers.list_tasks(
        get_client(),
        project_id=project_id,
        due_today=due_today,
        overdue=overdue,
        include_completed=include_completed,
    )


@mcp.tool
def get_task(task_id: str) -> dict[str, Any]:
    """Get one task by id.

    Args:
        task_id: The task id.

    Returns:
        The task object, or an {"error": ...} object on failure.
    """
    return handlers.get_task(get_client(), task_id=task_id)


@mcp.tool
def update_task(
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
    """Update a task.

    Args:
        task_id: The task id.
        title: New title; omit to keep the current title.
        content: New body text; omit to keep the current body.
        due: New due date. Use 'YYYY-MM-DD' for all-day, or 'YYYY-MM-DDTHH:MM'
            for timed. Omit to keep the current due date.
        clear_due: Remove the due date. Cannot be combined with due.
        priority: 0 none, 1 low, 3 medium, 5 high; omit to keep current priority.
        project_id: Move the task to this project id.
        tags: Replace the task's tag list with these tag names.
        timezone: IANA zone for a timed due date.
        column_id: Place the task in this kanban column id (from list_columns).
            Omit to use the project default. Only meaningful in kanban projects.
        assignee: User id to assign the task to (from list_project_members). Omit
            to leave unassigned. Only meaningful in shared projects.

    Returns:
        The updated task object, or an {"error": ...} object on failure.
    """
    return handlers.update_task(
        get_client(),
        task_id=task_id,
        title=title,
        content=content,
        due=due,
        clear_due=clear_due,
        priority=priority,
        project_id=project_id,
        tags=tags,
        timezone=timezone,
        column_id=column_id,
        assignee=assignee,
    )


@mcp.tool
def complete_task(task_id: str) -> dict[str, Any]:
    """Mark a task complete.

    Args:
        task_id: The task id.

    Returns:
        The completed task object, or an {"error": ...} object on failure.
    """
    return handlers.complete_task(get_client(), task_id=task_id)


@mcp.tool
def delete_task(task_id: str, project_id: str | None = None) -> dict[str, Any]:
    """Delete a task.

    Args:
        task_id: The task id.
        project_id: Project id override when needed for deletion.

    Returns:
        The deleted task object, or an {"error": ...} object on failure.
    """
    return handlers.delete_task(get_client(), task_id=task_id, project_id=project_id)


@mcp.tool
def get_project(project_id: str) -> dict[str, Any]:
    """Get one project by id.

    Args:
        project_id: The project id.

    Returns:
        The project object, or an {"error": ...} object on failure.
    """
    return handlers.get_project(get_client(), project_id=project_id)


@mcp.tool
def list_projects(include_closed: bool = False) -> dict[str, Any]:
    """List projects.

    Args:
        include_closed: Include closed/archived projects.

    Returns:
        {"projects": [ ...project objects... ]}, or an {"error": ...} object.
    """
    return handlers.list_projects(get_client(), include_closed=include_closed)


@mcp.tool
def list_columns(project_id: str) -> dict[str, Any]:
    """List a project's kanban columns (swimlanes).

    Args:
        project_id: The project id.

    Returns:
        {"columns": [{"id", "name", "sort_order", ...}]}, or an {"error": ...}
        object. Use a column "id" as the column_id argument on create/update to
        place or move an item (e.g. move a note to "Closed").
    """
    return handlers.list_columns(get_client(), project_id=project_id)


@mcp.tool
def list_project_members(project_id: str) -> dict[str, Any]:
    """List the members of a shared project (to resolve a person to an id).

    Args:
        project_id: The project id.

    Returns:
        {"members": [{"user_id", "display_name", "username", "is_owner",
        "permission"}]}, or an {"error": ...} object. Use a "user_id" as the
        assignee argument on create_task/update_task.
    """
    return handlers.list_project_members(get_client(), project_id=project_id)


@mcp.tool
def update_project(
    project_id: str,
    name: str | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    """Update a project.

    Args:
        project_id: The project id.
        name: New project name; omit to keep the current name.
        color: New hex color like '#4CA1FF'; omit to keep the current color.

    Returns:
        The updated project object, or an {"error": ...} object on failure.
    """
    return handlers.update_project(
        get_client(), project_id=project_id, name=name, color=color
    )


@mcp.tool
def delete_project(project_id: str) -> dict[str, Any]:
    """Delete a project.

    Args:
        project_id: The project id.

    Returns:
        The deleted project object, or an {"error": ...} object on failure.
    """
    return handlers.delete_project(get_client(), project_id=project_id)


@mcp.tool
def create_tag(label: str, color: str | None = None) -> dict[str, Any]:
    """Create a tag.

    Args:
        label: Display label, e.g. 'Deep Work'.
        color: Optional hex color.

    Returns:
        The created tag object, or an {"error": ...} object on failure.
    """
    return handlers.create_tag(get_client(), label=label, color=color)


@mcp.tool
def list_tags() -> dict[str, Any]:
    """List tags.

    Returns:
        {"tags": [ ...tag objects... ]}, or an {"error": ...} object on failure.
    """
    return handlers.list_tags(get_client())


@mcp.tool
def rename_tag(
    name: str,
    new_label: str,
    color: str | None = None,
) -> dict[str, Any]:
    """Rename a tag.

    Args:
        name: Current tag name.
        new_label: New display label.
        color: Optional new hex color.

    Returns:
        The renamed tag object, or an {"error": ...} object on failure.
    """
    return handlers.rename_tag(
        get_client(), name=name, new_label=new_label, color=color
    )


@mcp.tool
def delete_tag(name: str) -> dict[str, Any]:
    """Delete a tag.

    Args:
        name: Tag name.

    Returns:
        The deleted tag object, or an {"error": ...} object on failure.
    """
    return handlers.delete_tag(get_client(), name=name)


@mcp.tool
def add_tag_to_task(task_id: str, tag_name: str) -> dict[str, Any]:
    """Add a tag to a task.

    Args:
        task_id: The task id.
        tag_name: Tag name to add.

    Returns:
        The updated task object, or an {"error": ...} object on failure.
    """
    return handlers.add_tag_to_task(get_client(), task_id=task_id, tag_name=tag_name)


@mcp.tool
def remove_tag_from_task(task_id: str, tag_name: str) -> dict[str, Any]:
    """Remove a tag from a task.

    Args:
        task_id: The task id.
        tag_name: Tag name to remove.

    Returns:
        The updated task object, or an {"error": ...} object on failure.
    """
    return handlers.remove_tag_from_task(
        get_client(), task_id=task_id, tag_name=tag_name
    )


@mcp.tool
def get_note(note_id: str) -> dict[str, Any]:
    """Get one Markdown note by id.

    Args:
        note_id: The note id.

    Returns:
        The note object, or an {"error": ...} object on failure.
    """
    return handlers.get_note(get_client(), note_id=note_id)


@mcp.tool
def list_notes(
    project_id: str | None = None,
    include_completed: bool = False,
) -> dict[str, Any]:
    """List Markdown notes.

    Args:
        project_id: Limit to one project id. Omit for all projects.
        include_completed: Also include completed notes.

    Returns:
        {"notes": [ ...note objects... ]}, or an {"error": ...} object on failure.
    """
    return handlers.list_notes(
        get_client(), project_id=project_id, include_completed=include_completed
    )


@mcp.tool
def update_note(
    note_id: str,
    title: str | None = None,
    content: str | None = None,
    project_id: str | None = None,
    column_id: str | None = None,
    assignee: int | None = None,
) -> dict[str, Any]:
    """Update a Markdown note.

    Args:
        note_id: The note id.
        title: New note title; omit to keep the current title.
        content: New Markdown body; omit to keep the current body.
        project_id: Move the note to this project id.
        column_id: Place the task in this kanban column id (from list_columns).
            Omit to use the project default. Only meaningful in kanban projects.
        assignee: User id to assign the task to (from list_project_members). Omit
            to leave unassigned. Only meaningful in shared projects.

    Returns:
        The updated note object, or an {"error": ...} object on failure.
    """
    return handlers.update_note(
        get_client(),
        note_id=note_id,
        title=title,
        content=content,
        project_id=project_id,
        column_id=column_id,
        assignee=assignee,
    )


@mcp.tool
def delete_note(note_id: str) -> dict[str, Any]:
    """Delete a Markdown note.

    Args:
        note_id: The note id.

    Returns:
        The deleted note object, or an {"error": ...} object on failure.
    """
    return handlers.delete_note(get_client(), note_id=note_id)


def main() -> None:
    """Console-script entrypoint: run the MCP server.

    Transport is chosen by environment so the same image works two ways:

    - ``TICKTICK_MCP_TRANSPORT=stdio`` (default) — for an MCP host that spawns the
      process and talks over stdin/stdout (typical local CLI integration).
    - ``TICKTICK_MCP_TRANSPORT=http`` — a long-running HTTP server (used by the
      Docker Compose service), bound to ``TICKTICK_MCP_HOST`` (default
      ``0.0.0.0``) and ``TICKTICK_MCP_PORT`` (default ``8000``).

    Caller authentication is selected by ``TICKTICK_MCP_AUTH`` (see
    :mod:`ticktick_mcp.server.auth`); http refuses to start without an explicit
    mode.
    """
    transport = (os.environ.get("TICKTICK_MCP_TRANSPORT") or "stdio").strip().lower()
    normalized = "http" if transport in ("http", "streamable-http") else "stdio"
    mcp.auth = build_auth(normalized, os.environ)
    if normalized == "http":
        host = (os.environ.get("TICKTICK_MCP_HOST") or "0.0.0.0").strip()
        port = int((os.environ.get("TICKTICK_MCP_PORT") or "8000").strip())
        mcp.run(transport="http", host=host, port=port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
