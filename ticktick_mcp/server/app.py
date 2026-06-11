"""FastMCP server — the public tool interface (DESIGN.md §1, Slice 3).

Tools are thin: each delegates to a handler in :mod:`.handlers`, which calls one
typed client method. The :class:`TickTickClient` is built lazily on first tool
call so that merely *listing* tools (and importing this module) needs no
credentials.

Slice 3 Part A defines the tool contracts (see ``TOOLS.md``) and these reference
tools. Codex fills the remaining tools in Part B against the same pattern.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from ..client import TickTickClient
from ..config import load_config
from . import handlers

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
    )


@mcp.tool
def create_note(
    title: str, content: str, project_id: str | None = None
) -> dict[str, Any]:
    """Create a Markdown note (a note-kind item whose body is Markdown).

    Args:
        title: The note title.
        content: Markdown body — headings, lists, bold, etc. render in TickTick.
        project_id: Target project id. Defaults to the inbox.

    Returns:
        The created note object (with "kind": "NOTE"), or an {"error": ...} object.
    """
    return handlers.create_note(
        get_client(), title=title, content=content, project_id=project_id
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


def main() -> None:
    """Console-script entrypoint: run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
