"""Slice 3 tool-layer tests.

Handler tests use a fake client (no FastMCP, no network) and focus on the two
things the tool layer owns: shaping the date argument into the all-day/timed
contract, and turning errors into structured objects. A separate test boots the
real FastMCP app in memory and confirms the reference tools are registered.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime

from ticktick_mcp.client import APIError, AuthError
from ticktick_mcp.client.models import Project, Task
from ticktick_mcp.server import handlers


class FakeClient:
    """Records calls; returns typed models reflecting the all-day routing."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def create_task(self, title, *, project_id=None, content=None, due=None, priority=0, timezone=None):
        self.calls.append(("create_task", {"title": title, "due": due, "timezone": timezone}))
        is_all_day = isinstance(due, date) and not isinstance(due, datetime)
        return Task(
            id="t1", title=title, project_id=project_id or "inbox", content=content,
            due=due, is_all_day=is_all_day, priority=priority, timezone=timezone,
        )

    def create_note(self, title, content, *, project_id=None):
        self.calls.append(("create_note", {"title": title}))
        return Task(id="n1", title=title, content=content, kind="NOTE", project_id=project_id or "inbox")

    def create_project(self, name, *, color=None):
        self.calls.append(("create_project", {"name": name, "color": color}))
        return Project(id="p1", name=name, color=color)

    def list_tasks(self, *, project_id=None, due_today=False, overdue=False, include_completed=False):
        self.calls.append(("list_tasks", {"project_id": project_id, "due_today": due_today}))
        return [Task(id="t1", title="A", due=date(2026, 9, 15), is_all_day=True)]


class RaisingClient:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def create_task(self, *a, **k):
        raise self._exc


# -- date argument routing (the all-day contract surface) --------------------

def test_bare_date_due_routes_to_all_day() -> None:
    fc = FakeClient()
    result = handlers.create_task(fc, title="Pay rent", due="2026-09-15")
    # client received a `date`, not a datetime
    assert fc.calls[-1][1]["due"] == date(2026, 9, 15)
    assert result["is_all_day"] is True
    assert result["due"] == "2026-09-15"  # date-only out, never midnight


def test_datetime_due_routes_to_timed() -> None:
    fc = FakeClient()
    result = handlers.create_task(fc, title="Standup", due="2026-09-15T14:30")
    assert fc.calls[-1][1]["due"] == datetime(2026, 9, 15, 14, 30)
    assert result["is_all_day"] is False
    assert result["due"].startswith("2026-09-15T14:30")


def test_no_due_passes_none() -> None:
    fc = FakeClient()
    handlers.create_task(fc, title="Someday")
    assert fc.calls[-1][1]["due"] is None


def test_invalid_due_returns_structured_input_error() -> None:
    fc = FakeClient()
    result = handlers.create_task(fc, title="x", due="next tuesday")
    assert result["error"]["kind"] == "input"
    assert "Invalid due date" in result["error"]["message"]
    assert fc.calls == []  # never reached the client


# -- error mapping -----------------------------------------------------------

def test_auth_error_maps_to_auth_kind() -> None:
    result = handlers.create_task(RaisingClient(AuthError("session expired")), title="x")
    assert result["error"] == {"kind": "auth", "message": "session expired"}


def test_api_error_maps_to_api_kind() -> None:
    result = handlers.create_task(RaisingClient(APIError("nope")), title="x")
    assert result["error"]["kind"] == "api"


def test_unexpected_error_is_generic_internal() -> None:
    result = handlers.create_task(RaisingClient(RuntimeError("secret stack detail")), title="x")
    assert result["error"]["kind"] == "internal"
    assert "secret" not in result["error"]["message"]  # internals not leaked


# -- other reference tools ---------------------------------------------------

def test_create_note_returns_note_kind() -> None:
    result = handlers.create_note(FakeClient(), title="Recipe", content="# Pasta")
    assert result["kind"] == "NOTE"


def test_create_project_returns_project() -> None:
    result = handlers.create_project(FakeClient(), name="Work", color="#4CA1FF")
    assert result["name"] == "Work" and result["color"] == "#4CA1FF"


def test_list_tasks_wraps_in_tasks_key() -> None:
    result = handlers.list_tasks(FakeClient())
    assert [t["id"] for t in result["tasks"]] == ["t1"]


# -- FastMCP app registration (in-memory, no creds needed to list) -----------

def test_app_registers_reference_tools() -> None:
    from fastmcp import Client

    from ticktick_mcp.server.app import mcp

    async def go() -> set[str]:
        async with Client(mcp) as client:
            return {tool.name for tool in await client.list_tools()}

    names = asyncio.run(go())
    assert {"create_task", "create_project", "create_note", "list_tasks"} <= names
