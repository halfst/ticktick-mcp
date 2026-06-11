"""Slice 2 reference-method tests with a fake transport (no network).

Asserts the exact payloads sent to the v2 batch endpoints — especially the
all-day vs timed branch — and that responses parse into typed models.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from ticktick_mcp.client import APIError, Project, Tag, Task, TickTickClient
from ticktick_mcp.config import Config

INBOX = "inbox-abc"


class FakeTransport:
    """Records requests; echoes id2etag for added items. ``fail_ids`` -> id2error."""

    def __init__(self, fail_ids: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.fail_ids = fail_ids or set()

    def request(self, method: str, path: str, *, params: Any = None, json: Any = None) -> Any:
        self.calls.append((method, path, json))
        if path == "batch/check/0":
            return {"inboxId": INBOX, "syncTaskBean": {"update": []}, "projectProfiles": [], "tags": []}
        added = (json or {}).get("add") or []
        id2etag, id2error = {}, {}
        for item in added:
            key = item.get("id") or item.get("name")
            if key in self.fail_ids:
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


def make_client(tmp_path: Path, *, default_tz: str = "UTC", fail_ids: set[str] | None = None) -> tuple[TickTickClient, FakeTransport]:
    config = Config(
        session_token="tok",
        token_cache_path=tmp_path / "s.json",
        default_timezone=default_tz,
    )
    ft = FakeTransport(fail_ids=fail_ids)
    return TickTickClient(config, transport=ft), ft


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
