"""Live end-to-end test against a real TickTick account. Opt-in.

Skipped automatically unless credentials are present in the environment
(``TICKTICK_SESSION_TOKEN`` or username/password). It creates clearly-labelled
throwaway items, verifies the all-day contract round-trips through the real API,
and deletes everything it created in a ``finally`` block.

Run locally with:  ``set -a; . ./.env; set +a; pytest -q tests/test_client_live.py``
"""

from __future__ import annotations

from datetime import date, datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pytest

from ticktick_mcp.client import TickTickClient
from ticktick_mcp.config import ConfigError, load_config

try:
    _CONFIG = load_config()
except ConfigError:
    _CONFIG = None

pytestmark = pytest.mark.skipif(
    _CONFIG is None, reason="no TickTick credentials in environment"
)

LABEL = "ttmcp-live-test (delete me)"


def _delete_tasks(client: TickTickClient, items: list[tuple[str, str]]) -> None:
    if items:
        client._t.request(
            "POST", "batch/task",
            json={"add": [], "update": [], "delete": [{"taskId": i, "projectId": p} for i, p in items]},
        )


def test_all_day_round_trip_live() -> None:
    client = TickTickClient(_CONFIG)
    created: list[tuple[str, str]] = []
    projects: list[str] = []
    tags: list[str] = []
    try:
        # All-day: a date with no time must read back as that exact date.
        d = date(2026, 9, 16)
        allday = client.create_task(LABEL, due=d)
        created.append((allday.id, allday.project_id))
        assert allday.is_all_day is True
        assert allday.due == d

        # Timed stays timed.
        dt = datetime(2026, 9, 16, 9, 30, tzinfo=ZoneInfo("America/Chicago"))
        timed = client.create_task(LABEL, due=dt, timezone="America/Chicago")
        created.append((timed.id, timed.project_id))
        assert timed.is_all_day is False

        # Read back from the server and confirm the all-day task is all-day there.
        state = client._t.request("GET", "batch/check/0")
        by_id = {t["id"]: t for t in state["syncTaskBean"]["update"]}
        assert by_id[allday.id]["isAllDay"] is True
        assert by_id[timed.id]["isAllDay"] is False
        # And decode the raw server value back to the original calendar date.
        from ticktick_mcp.client.dates import decode_due
        raw = by_id[allday.id]
        assert decode_due(raw["dueDate"], True, raw.get("timeZone")) == d

        # Complete the timed task, then confirm it's still readable — completed
        # tasks are absent from batch/check and come from the completed endpoint.
        client.complete_task(timed.id)
        assert client.get_task(timed.id).status == 2
        assert timed.id in [t.id for t in client.list_tasks(include_completed=True)]
        assert timed.id not in [t.id for t in client.list_tasks()]

        # Markdown note.
        note = client.create_note(LABEL, "# Heading\n\n- **bold** item")
        created.append((note.id, note.project_id))
        assert by_id_kind(client, note.id) == "NOTE"

        # Project + tag.
        proj = client.create_project("ttmcp-live-proj (delete me)")
        projects.append(proj.id)
        tag = client.create_tag("ttmcp-live-tag")
        tags.append(tag.name)
    finally:
        _delete_tasks(client, created)
        for pid in projects:
            client._t.request("POST", "batch/project", json={"add": [], "update": [], "delete": [pid]})
        for name in tags:
            # Tag delete is DELETE tag?name=<name> (batch/tag delete is a no-op).
            client._t.request("DELETE", f"tag?name={quote(name)}")
        client.close()


def by_id_kind(client: TickTickClient, task_id: str) -> str:
    state = client._t.request("GET", "batch/check/0")
    for t in state["syncTaskBean"]["update"]:
        if t["id"] == task_id:
            return t.get("kind")
    raise AssertionError("note not found on readback")
