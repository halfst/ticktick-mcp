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
from ticktick_mcp.client.models import Project, Tag, Task
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

    def get_task(self, task_id):
        self.calls.append(("get_task", {"task_id": task_id}))
        return Task(id=task_id, title="A")

    def update_task(
        self,
        task_id,
        *,
        title=None,
        content=None,
        due=None,
        clear_due=False,
        priority=None,
        project_id=None,
        tags=None,
        timezone=None,
    ):
        self.calls.append(
            (
                "update_task",
                {
                    "task_id": task_id,
                    "due": due,
                    "clear_due": clear_due,
                    "tags": tags,
                    "timezone": timezone,
                },
            )
        )
        is_all_day = isinstance(due, date) and not isinstance(due, datetime)
        return Task(
            id=task_id,
            title=title or "A",
            content=content,
            due=due,
            is_all_day=is_all_day,
            priority=priority or 0,
            project_id=project_id or "inbox",
            tags=tags or [],
        )

    def complete_task(self, task_id):
        self.calls.append(("complete_task", {"task_id": task_id}))
        return Task(id=task_id, title="A", status=2)

    def delete_task(self, task_id, *, project_id=None):
        self.calls.append(("delete_task", {"task_id": task_id, "project_id": project_id}))
        return Task(id=task_id, title="A", project_id=project_id or "inbox")

    def create_note(self, title, content, *, project_id=None):
        self.calls.append(("create_note", {"title": title}))
        return Task(id="n1", title=title, content=content, kind="NOTE", project_id=project_id or "inbox")

    def get_note(self, note_id):
        self.calls.append(("get_note", {"note_id": note_id}))
        return Task(id=note_id, title="Note", content="# Body", kind="NOTE")

    def list_notes(self, *, project_id=None, include_completed=False):
        self.calls.append(("list_notes", {"project_id": project_id, "include_completed": include_completed}))
        return [Task(id="n1", title="Note", content="# Body", kind="NOTE", project_id=project_id or "inbox")]

    def update_note(self, note_id, *, title=None, content=None, project_id=None):
        self.calls.append(("update_note", {"note_id": note_id, "title": title, "content": content}))
        return Task(id=note_id, title=title or "Note", content=content, kind="NOTE", project_id=project_id or "inbox")

    def delete_note(self, note_id):
        self.calls.append(("delete_note", {"note_id": note_id}))
        return Task(id=note_id, title="Note", kind="NOTE")

    def create_project(self, name, *, color=None):
        self.calls.append(("create_project", {"name": name, "color": color}))
        return Project(id="p1", name=name, color=color)

    def get_project(self, project_id):
        self.calls.append(("get_project", {"project_id": project_id}))
        return Project(id=project_id, name="Work")

    def list_projects(self, *, include_closed=False):
        self.calls.append(("list_projects", {"include_closed": include_closed}))
        return [Project(id="p1", name="Work")]

    def update_project(self, project_id, *, name=None, color=None):
        self.calls.append(("update_project", {"project_id": project_id, "name": name, "color": color}))
        return Project(id=project_id, name=name or "Work", color=color)

    def delete_project(self, project_id):
        self.calls.append(("delete_project", {"project_id": project_id}))
        return Project(id=project_id, name="Work")

    def create_tag(self, label, *, color=None):
        self.calls.append(("create_tag", {"label": label, "color": color}))
        return Tag(name=label.lower(), label=label, color=color)

    def list_tags(self):
        self.calls.append(("list_tags", {}))
        return [Tag(name="deep work", label="Deep Work")]

    def rename_tag(self, name, new_label, *, color=None):
        self.calls.append(("rename_tag", {"name": name, "new_label": new_label, "color": color}))
        return Tag(name=name.lower(), label=new_label, color=color)

    def delete_tag(self, name):
        self.calls.append(("delete_tag", {"name": name}))
        return Tag(name=name.lower(), label=name)

    def add_tag_to_task(self, task_id, tag_name):
        self.calls.append(("add_tag_to_task", {"task_id": task_id, "tag_name": tag_name}))
        return Task(id=task_id, title="A", tags=[tag_name.lower()])

    def remove_tag_from_task(self, task_id, tag_name):
        self.calls.append(("remove_tag_from_task", {"task_id": task_id, "tag_name": tag_name}))
        return Task(id=task_id, title="A", tags=[])

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


def test_task_part_b_handlers() -> None:
    fc = FakeClient()

    assert handlers.get_task(fc, task_id="t1")["id"] == "t1"

    updated = handlers.update_task(
        fc,
        task_id="t1",
        title="Updated",
        due="2026-09-16",
        clear_due=False,
        priority=3,
        tags=["Deep Work"],
    )
    assert fc.calls[-1][0] == "update_task"
    assert fc.calls[-1][1]["due"] == date(2026, 9, 16)
    assert updated["is_all_day"] is True
    assert updated["due"] == "2026-09-16"
    assert updated["tags"] == ["Deep Work"]

    completed = handlers.complete_task(fc, task_id="t1")
    assert completed["status"] == 2

    deleted = handlers.delete_task(fc, task_id="t1", project_id="p1")
    assert deleted["project_id"] == "p1"


def test_update_task_invalid_due_does_not_call_client() -> None:
    fc = FakeClient()
    result = handlers.update_task(fc, task_id="t1", due="tomorrow")
    assert result["error"]["kind"] == "input"
    assert fc.calls == []


def test_project_part_b_handlers() -> None:
    fc = FakeClient()

    assert handlers.get_project(fc, project_id="p1")["name"] == "Work"
    assert [p["id"] for p in handlers.list_projects(fc)["projects"]] == ["p1"]
    updated = handlers.update_project(
        fc, project_id="p1", name="Personal", color="#111111"
    )
    assert updated["name"] == "Personal"
    deleted = handlers.delete_project(fc, project_id="p1")
    assert deleted["id"] == "p1"


def test_tag_part_b_handlers() -> None:
    fc = FakeClient()

    created = handlers.create_tag(fc, label="Deep Work", color="#4CA1FF")
    assert created["name"] == "deep work"
    assert [t["name"] for t in handlers.list_tags(fc)["tags"]] == ["deep work"]
    renamed = handlers.rename_tag(fc, name="deep work", new_label="Focus")
    assert renamed["label"] == "Focus"
    deleted = handlers.delete_tag(fc, name="deep work")
    assert deleted["name"] == "deep work"
    tagged = handlers.add_tag_to_task(fc, task_id="t1", tag_name="Home")
    assert tagged["tags"] == ["home"]
    untagged = handlers.remove_tag_from_task(fc, task_id="t1", tag_name="Home")
    assert untagged["tags"] == []


def test_note_part_b_handlers() -> None:
    fc = FakeClient()

    assert handlers.get_note(fc, note_id="n1")["kind"] == "NOTE"
    assert [n["id"] for n in handlers.list_notes(fc)["notes"]] == ["n1"]
    updated = handlers.update_note(fc, note_id="n1", title="New", content="## Body")
    assert updated["title"] == "New"
    assert updated["content"] == "## Body"
    deleted = handlers.delete_note(fc, note_id="n1")
    assert deleted["kind"] == "NOTE"


# -- FastMCP app registration (in-memory, no creds needed to list) -----------

def test_app_registers_reference_tools() -> None:
    from fastmcp import Client

    from ticktick_mcp.server.app import mcp

    async def go() -> set[str]:
        async with Client(mcp) as client:
            return {tool.name for tool in await client.list_tools()}

    names = asyncio.run(go())
    assert {
        "create_task",
        "get_task",
        "list_tasks",
        "update_task",
        "complete_task",
        "delete_task",
        "create_project",
        "get_project",
        "list_projects",
        "update_project",
        "delete_project",
        "create_tag",
        "list_tags",
        "rename_tag",
        "delete_tag",
        "add_tag_to_task",
        "remove_tag_from_task",
        "create_note",
        "get_note",
        "list_notes",
        "update_note",
        "delete_note",
    } <= names


# -- input-guard tests for mutually-exclusive args ---------------------------

def test_update_task_due_and_clear_due_is_input_error() -> None:
    fc = FakeClient()
    result = handlers.update_task(fc, task_id="t1", due="2026-09-15", clear_due=True)
    assert result["error"]["kind"] == "input"
    assert fc.calls == []  # never reached the client


def test_list_tasks_due_today_and_overdue_is_input_error() -> None:
    fc = FakeClient()
    result = handlers.list_tasks(fc, due_today=True, overdue=True)
    assert result["error"]["kind"] == "input"
    assert fc.calls == []


# -- entrypoint transport selection ------------------------------------------

def test_main_defaults_to_stdio(monkeypatch) -> None:
    from ticktick_mcp.server import app

    captured: dict = {}
    monkeypatch.setattr(app.mcp, "run", lambda *a, **k: captured.update(args=a, kwargs=k))
    monkeypatch.delenv("TICKTICK_MCP_TRANSPORT", raising=False)
    app.main()
    assert captured == {"args": (), "kwargs": {}}


def test_main_http_transport_reads_env(monkeypatch) -> None:
    from ticktick_mcp.server import app

    captured: dict = {}
    monkeypatch.setattr(app.mcp, "run", lambda *a, **k: captured.update(k))
    monkeypatch.setenv("TICKTICK_MCP_TRANSPORT", "http")
    monkeypatch.setenv("TICKTICK_MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("TICKTICK_MCP_PORT", "9001")
    app.main()
    assert captured == {"transport": "http", "host": "127.0.0.1", "port": 9001}
