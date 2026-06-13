"""Slice 2 reference-method tests with a fake transport (no network).

Asserts the exact payloads sent to the v2 batch endpoints — especially the
all-day vs timed branch — and that responses parse into typed models.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from ticktick_mcp.client import APIError, Column, Member, Project, Tag, Task, TickTickClient
from ticktick_mcp.config import Config

INBOX = "inbox-abc"


class FakeTransport:
    """Records requests; echoes id2etag for added items. ``fail_ids`` -> id2error."""

    def __init__(
        self,
        fail_ids: set[str] | None = None,
        state: dict[str, Any] | None = None,
        completed: list[dict[str, Any]] | None = None,
        columns: list[dict[str, Any]] | None = None,
        members: list[dict[str, Any]] | None = None,
    ) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.fail_ids = fail_ids or set()
        self.state = state or {
            "inboxId": INBOX,
            "syncTaskBean": {"update": []},
            "projectProfiles": [],
            "tags": [],
        }
        # Completed tasks are served from the completed endpoint, NOT batch/check.
        self.completed = completed or []
        self.columns = columns or []
        self.members = members or []

    def request(self, method: str, path: str, *, params: Any = None, json: Any = None) -> Any:
        self.calls.append((method, path, deepcopy(json)))
        if path == "batch/check/0":
            return self.state
        if path.startswith("column/project/"):
            return self.columns
        if path.startswith("project/") and path.endswith("/users"):
            return self.members
        if path.endswith("/completed/"):
            return self.completed
        if method == "DELETE":
            return {}
        return self._batch_response(json or {})

    def _batch_response(self, body: dict[str, Any]) -> dict[str, dict[str, str]]:
        changed = list(body.get("add") or []) + list(body.get("update") or [])
        changed += list(body.get("delete") or [])
        id2etag, id2error = {}, {}
        for item in changed:
            if isinstance(item, dict):
                key = item.get("id") or item.get("taskId") or item.get("name")
            else:
                key = item
            if "*" in self.fail_ids or key in self.fail_ids:
                id2error[key] = "rejected by fake"
            else:
                id2etag[key] = f"etag-{key}"
        return {"id2etag": id2etag, "id2error": id2error}

    def close(self) -> None:  # pragma: no cover - trivial
        pass

    def last_add(self, path: str) -> dict:
        for method, p, body in reversed(self.calls):
            if p == path:
                return (body["add"][0])
        raise AssertionError(f"no add call to {path}")

    def last_update(self, path: str) -> dict:
        for method, p, body in reversed(self.calls):
            if p == path and body["update"]:
                return (body["update"][0])
        raise AssertionError(f"no update call to {path}")

    def last_delete(self, path: str) -> Any:
        for method, p, body in reversed(self.calls):
            if p == path and body["delete"]:
                return body["delete"]
        raise AssertionError(f"no delete call to {path}")


def make_client(
    tmp_path: Path,
    *,
    default_tz: str = "UTC",
    fail_ids: set[str] | None = None,
    state: dict[str, Any] | None = None,
    completed: list[dict[str, Any]] | None = None,
    columns: list[dict[str, Any]] | None = None,
    members: list[dict[str, Any]] | None = None,
) -> tuple[TickTickClient, FakeTransport]:
    config = Config(
        session_token="tok",
        token_cache_path=tmp_path / "s.json",
        default_timezone=default_tz,
    )
    ft = FakeTransport(
        fail_ids=fail_ids, state=state, completed=completed, columns=columns, members=members
    )
    return TickTickClient(config, transport=ft), ft


def state_with_items() -> dict[str, Any]:
    return {
        "inboxId": INBOX,
        "syncTaskBean": {
            "update": [
                {
                    "id": "t-today",
                    "projectId": "p1",
                    "title": "Today",
                    "kind": "TEXT",
                    "status": 0,
                    "isAllDay": True,
                    "startDate": "2026-06-11T00:00:00.000+0000",
                    "dueDate": "2026-06-11T00:00:00.000+0000",
                    "timeZone": "UTC",
                    "tags": ["deep work"],
                    "etag": "old-task-etag",
                },
                {
                    "id": "t-overdue",
                    "projectId": "p1",
                    "title": "Overdue",
                    "kind": "TEXT",
                    "status": 0,
                    "isAllDay": True,
                    "dueDate": "2026-06-10T00:00:00.000+0000",
                    "timeZone": "UTC",
                },
                {
                    "id": "n1",
                    "projectId": "p1",
                    "title": "Note",
                    "kind": "NOTE",
                    "content": "# Heading",
                    "status": 0,
                },
            ]
        },
        "projectProfiles": [
            {"id": "p1", "name": "Work", "color": "#4CA1FF", "etag": "old-proj-etag"},
            {"id": "p2", "name": "Closed", "closed": True},
        ],
        "tags": [{"name": "deep work", "label": "Deep Work", "color": "#ABCDEF"}],
    }


def completed_with_items() -> list[dict[str, Any]]:
    # Completed tasks live behind the completed endpoint, not in batch/check.
    return [
        {
            "id": "t-complete",
            "projectId": "p2",
            "title": "Done",
            "kind": "TEXT",
            "status": 2,
        }
    ]


def test_create_task_all_day_payload_and_result(tmp_path: Path) -> None:
    client, ft = make_client(tmp_path)
    task = client.create_task("Pay rent", due=date(2026, 9, 15))

    sent = ft.last_add("batch/task")
    assert sent["isAllDay"] is True
    assert sent["dueDate"] == "2026-09-15T00:00:00.000+0000"
    assert sent["startDate"] == sent["dueDate"]
    assert sent["timeZone"] == "UTC"
    assert sent["projectId"] == INBOX  # defaulted to inbox

    # Headline: a date-only due comes back as a date, NOT midnight.
    assert isinstance(task, Task)
    assert task.is_all_day is True
    assert task.due == date(2026, 9, 15)


def test_create_task_timed_converts_to_utc(tmp_path: Path) -> None:
    client, ft = make_client(tmp_path)
    dt = datetime(2026, 9, 15, 14, 30, tzinfo=ZoneInfo("America/Chicago"))
    task = client.create_task("Standup", due=dt, timezone="America/Chicago")

    sent = ft.last_add("batch/task")
    assert sent["isAllDay"] is False
    assert sent["dueDate"] == "2026-09-15T19:30:00.000+0000"  # CDT -> UTC
    assert sent["timeZone"] == "America/Chicago"
    assert task.is_all_day is False
    assert task.due == dt


def test_timed_naive_due_uses_client_default_timezone(tmp_path: Path) -> None:
    client, ft = make_client(tmp_path, default_tz="America/Chicago")
    client.create_task("Lunch", due=datetime(2026, 9, 15, 12, 0))
    sent = ft.last_add("batch/task")
    assert sent["dueDate"] == "2026-09-15T17:00:00.000+0000"  # noon Chicago -> 17:00Z


def test_create_task_without_due_sends_no_date_fields(tmp_path: Path) -> None:
    client, ft = make_client(tmp_path)
    task = client.create_task("Someday idea", project_id="p1")
    sent = ft.last_add("batch/task")
    assert "dueDate" not in sent and "isAllDay" not in sent
    assert sent["projectId"] == "p1"
    assert task.due is None


def test_create_note_uses_note_kind(tmp_path: Path) -> None:
    client, ft = make_client(tmp_path)
    note = client.create_note("Recipe", "# Pasta\n\n- boil water")
    sent = ft.last_add("batch/task")
    assert sent["kind"] == "NOTE"
    assert sent["content"].startswith("# Pasta")
    assert note.is_note is True


def test_create_project_payload(tmp_path: Path) -> None:
    client, ft = make_client(tmp_path)
    proj = client.create_project("Work", color="#4CA1FF")
    sent = ft.last_add("batch/project")
    assert sent["name"] == "Work"
    assert sent["color"] == "#4CA1FF"
    assert isinstance(proj, Project)
    assert proj.name == "Work"


def test_create_tag_lowercases_name(tmp_path: Path) -> None:
    client, ft = make_client(tmp_path)
    tag = client.create_tag("Deep Work")
    sent = ft.last_add("batch/tag")
    assert sent["name"] == "deep work"
    assert sent["label"] == "Deep Work"
    assert isinstance(tag, Tag)
    assert tag.name == "deep work"


def test_batch_error_raises_api_error(tmp_path: Path) -> None:
    # Force the task's generated id to fail. We don't know the id ahead of time,
    # so fail everything: any id in the add is rejected.
    client, ft = make_client(tmp_path)
    ft.fail_ids = {"*"}

    # Patch: make every added id "fail" by overriding request to error.
    def erroring(method, path, *, params=None, json=None):
        if path == "batch/check/0":
            return {"inboxId": INBOX}
        added = (json or {}).get("add") or []
        key = added[0].get("id") or added[0].get("name")
        return {"id2etag": {}, "id2error": {key: "boom"}}

    ft.request = erroring  # type: ignore[assignment]
    with pytest.raises(APIError, match="rejected|boom"):
        client.create_task("will fail", project_id="p1")


def test_get_and_list_tasks_from_full_state(tmp_path: Path) -> None:
    client, _ = make_client(
        tmp_path, state=state_with_items(), completed=completed_with_items()
    )
    client._today = lambda: date(2026, 6, 11)  # type: ignore[method-assign]

    assert client.get_task("t-today").title == "Today"
    assert [task.id for task in client.list_tasks(project_id="p1")] == [
        "t-today",
        "t-overdue",
    ]
    assert [task.id for task in client.list_tasks(due_today=True)] == ["t-today"]
    assert [task.id for task in client.list_tasks(overdue=True)] == ["t-overdue"]
    assert [task.id for task in client.list_tasks(include_completed=True)] == [
        "t-today",
        "t-overdue",
        "t-complete",
    ]


def test_completed_tasks_read_from_completed_endpoint(tmp_path: Path) -> None:
    # Regression: completed tasks are absent from batch/check; they must be
    # fetched from project/.../completed/. get_task and include_completed both
    # depend on that fallback.
    client, ft = make_client(
        tmp_path, state=state_with_items(), completed=completed_with_items()
    )
    client._today = lambda: date(2026, 6, 11)  # type: ignore[method-assign]

    # Not in the sync bean...
    assert "t-complete" not in [t["id"] for t in ft.state["syncTaskBean"]["update"]]
    # ...but get_task finds it via the completed endpoint.
    done = client.get_task("t-complete")
    assert done.status == 2 and done.title == "Done"
    # And it's excluded unless include_completed is set.
    assert "t-complete" not in [t.id for t in client.list_tasks()]
    assert "t-complete" in [t.id for t in client.list_tasks(include_completed=True)]
    assert any(p.endswith("/completed/") for _, p, _ in ft.calls)


def test_update_task_preserves_existing_all_day_fields(tmp_path: Path) -> None:
    client, ft = make_client(tmp_path, state=state_with_items())
    task = client.update_task("t-today", title="Today renamed")

    sent = ft.last_update("batch/task")
    assert sent["title"] == "Today renamed"
    assert sent["isAllDay"] is True
    assert sent["startDate"] == "2026-06-11T00:00:00.000+0000"
    assert sent["dueDate"] == "2026-06-11T00:00:00.000+0000"
    assert sent["timeZone"] == "UTC"
    assert task.title == "Today renamed"
    assert task.due == date(2026, 6, 11)


def test_update_task_reencodes_due_and_complete_delete_payloads(tmp_path: Path) -> None:
    client, ft = make_client(tmp_path, state=state_with_items())
    client.update_task(
        "t-today",
        due=datetime(2026, 6, 12, 9, 0, tzinfo=ZoneInfo("America/Chicago")),
        timezone="America/Chicago",
    )
    sent_update = ft.last_update("batch/task")
    assert sent_update["isAllDay"] is False
    assert sent_update["dueDate"] == "2026-06-12T14:00:00.000+0000"
    assert sent_update["startDate"] == sent_update["dueDate"]
    assert sent_update["timeZone"] == "America/Chicago"

    completed = client.complete_task("t-today")
    assert ft.last_update("batch/task")["status"] == 2
    assert completed.status == 2

    deleted = client.delete_task("t-today")
    assert ft.last_delete("batch/task") == [{"taskId": "t-today", "projectId": "p1"}]
    assert deleted.id == "t-today"


def test_project_part_b_methods(tmp_path: Path) -> None:
    client, ft = make_client(tmp_path, state=state_with_items())

    assert client.get_project("p1").name == "Work"
    assert [project.id for project in client.list_projects()] == ["p1"]
    assert [project.id for project in client.list_projects(include_closed=True)] == [
        "p1",
        "p2",
    ]

    updated = client.update_project("p1", name="Personal", color="#111111")
    sent_update = ft.last_update("batch/project")
    assert sent_update["name"] == "Personal"
    assert sent_update["color"] == "#111111"
    assert updated.name == "Personal"

    deleted = client.delete_project("p1")
    assert ft.last_delete("batch/project") == ["p1"]
    assert deleted.id == "p1"


def test_tag_part_b_methods(tmp_path: Path) -> None:
    client, ft = make_client(tmp_path, state=state_with_items())

    assert [tag.name for tag in client.list_tags()] == ["deep work"]

    renamed = client.rename_tag("Deep Work", "Focus", color="#111111")
    sent_update = ft.last_update("batch/tag")
    assert sent_update == {
        "name": "deep work",
        "label": "Focus",
        "color": "#111111",
    }
    assert renamed.label == "Focus"

    tagged = client.add_tag_to_task("t-today", "Home")
    assert ft.last_update("batch/task")["tags"] == ["deep work", "home"]
    assert tagged.tags == ["deep work", "home"]

    untagged = client.remove_tag_from_task("t-today", "Deep Work")
    assert ft.last_update("batch/task")["tags"] == []
    assert untagged.tags == []

    deleted = client.delete_tag("Deep Work")
    assert ft.calls[-1] == ("DELETE", "tag?name=deep%20work", None)
    assert deleted.name == "deep work"


def test_task_from_api_surfaces_column_and_assignee() -> None:
    raw = {
        "id": "t1",
        "projectId": "p1",
        "title": "Shared",
        "kind": "TEXT",
        "columnId": "col-new",
        "assignee": 121024798,
    }
    task = Task.from_api(raw)
    assert task.column_id == "col-new"
    assert task.assignee == 121024798


def test_task_from_api_normalizes_zero_assignee_to_none() -> None:
    task = Task.from_api({"id": "t2", "assignee": 0})
    assert task.assignee is None
    assert task.column_id is None


def test_column_from_api() -> None:
    col = Column.from_api(
        {"id": "c1", "projectId": "p1", "name": "Closed", "sortOrder": 131071, "etag": "e1"}
    )
    assert (col.id, col.project_id, col.name, col.sort_order) == ("c1", "p1", "Closed", 131071)


def test_member_from_api() -> None:
    m = Member.from_api(
        {
            "userId": 121024798,
            "username": "a@example.com",
            "displayName": "Annemarie",
            "isOwner": False,
            "permission": "write",
        }
    )
    assert (m.user_id, m.display_name, m.is_owner, m.permission) == (
        121024798,
        "Annemarie",
        False,
        "write",
    )


def test_list_columns_hits_column_endpoint(tmp_path) -> None:
    cols = [
        {"id": "c-new", "projectId": "p1", "name": "New", "sortOrder": -1},
        {"id": "c-closed", "projectId": "p1", "name": "Closed", "sortOrder": 9},
    ]
    client, ft = make_client(tmp_path, columns=cols)
    result = client.list_columns("p1")
    assert ("GET", "column/project/p1", None) in ft.calls
    assert [(c.id, c.name) for c in result] == [("c-new", "New"), ("c-closed", "Closed")]


def test_list_project_members_hits_users_endpoint(tmp_path) -> None:
    members = [
        {"userId": 1, "displayName": "Ethan", "isOwner": True, "permission": "write"},
        {"userId": 2, "displayName": "Annemarie", "isOwner": False, "permission": "write"},
    ]
    client, ft = make_client(tmp_path, members=members)
    result = client.list_project_members("p1")
    assert ("GET", "project/p1/users", None) in ft.calls
    assert [(m.user_id, m.display_name) for m in result] == [(1, "Ethan"), (2, "Annemarie")]


def test_create_task_sets_column_and_assignee(tmp_path) -> None:
    client, ft = make_client(tmp_path)
    client.create_task("X", project_id="p1", column_id="col-new", assignee=121024798)
    add = ft.last_add("batch/task")
    assert add["columnId"] == "col-new"
    assert add["assignee"] == 121024798


def test_create_task_omits_column_and_assignee_when_unset(tmp_path) -> None:
    client, ft = make_client(tmp_path)
    client.create_task("X", project_id="p1")
    add = ft.last_add("batch/task")
    assert "columnId" not in add and "assignee" not in add


def test_create_note_sets_column_and_assignee(tmp_path) -> None:
    client, ft = make_client(tmp_path)
    client.create_note("X", "body", project_id="p1", column_id="col-new", assignee=121024798)
    add = ft.last_add("batch/task")
    assert add["columnId"] == "col-new"
    assert add["assignee"] == 121024798


def test_update_task_sets_column_and_assignee(tmp_path) -> None:
    state = {
        "inboxId": INBOX,
        "syncTaskBean": {"update": [{"id": "t1", "projectId": "p1", "title": "A", "kind": "TEXT"}]},
        "projectProfiles": [],
        "tags": [],
    }
    client, ft = make_client(tmp_path, state=state)
    client.update_task("t1", column_id="col-closed", assignee=121024798)
    upd = ft.last_update("batch/task")
    assert upd["columnId"] == "col-closed"
    assert upd["assignee"] == 121024798


def test_update_task_assignee_zero_reaches_wire(tmp_path) -> None:
    # assignee=0 is the unassign value and MUST reach the payload — guards the
    # `is not None` check against being weakened to a truthiness test.
    state = {
        "inboxId": INBOX,
        "syncTaskBean": {"update": [{"id": "t1", "projectId": "p1", "title": "A", "kind": "TEXT"}]},
        "projectProfiles": [],
        "tags": [],
    }
    client, ft = make_client(tmp_path, state=state)
    client.update_task("t1", assignee=0)
    upd = ft.last_update("batch/task")
    assert upd["assignee"] == 0


def test_update_note_sets_column(tmp_path) -> None:
    state = {
        "inboxId": INBOX,
        "syncTaskBean": {
            "update": [{"id": "n1", "projectId": "p1", "title": "N", "kind": "NOTE"}]
        },
        "projectProfiles": [],
        "tags": [],
    }
    client, ft = make_client(tmp_path, state=state)
    client.update_note("n1", column_id="col-closed", assignee=121024798)
    upd = ft.last_update("batch/task")
    assert upd["columnId"] == "col-closed"
    assert upd["assignee"] == 121024798


def test_note_part_b_methods(tmp_path: Path) -> None:
    client, ft = make_client(tmp_path, state=state_with_items())

    assert client.get_note("n1").content == "# Heading"
    assert [note.id for note in client.list_notes(project_id="p1")] == ["n1"]

    updated = client.update_note("n1", title="New note", content="## Body")
    sent_update = ft.last_update("batch/task")
    assert sent_update["kind"] == "NOTE"
    assert sent_update["title"] == "New note"
    assert sent_update["content"] == "## Body"
    assert updated.is_note is True

    deleted = client.delete_note("n1")
    assert ft.last_delete("batch/task") == [{"taskId": "n1", "projectId": "p1"}]
    assert deleted.is_note is True
