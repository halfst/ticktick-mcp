"""TickTickClient — the typed method surface the server layer calls.

This is the ONLY place outside the transport that knows v2 endpoint paths and
payload shapes (DESIGN.md §1). Slice 2 Part A implements one reference method per
family (task / project / tag / note); Codex fills the remaining methods in Part B
following the exact same pattern (see CLIENT_METHODS.md).

Endpoints + payloads here were confirmed against a live v2 account (2026-06):
- Tasks (and notes): ``POST batch/task`` with ``{"add":[...], "update":[...],
  "delete":[{"taskId","projectId"}]}``; client generates the 24-hex task ``id``;
  response is ``{"id2etag": {...}, "id2error": {...}}``.
- Projects: ``POST batch/project`` with ``{"add":[...]}``; delete by id in
  ``"delete": [projectId]``.
- Tags: ``POST batch/tag`` with ``{"add":[{"name","label"}]}``; delete by name.
- Full state read: ``GET batch/check/0`` → ``syncTaskBean.update`` (tasks),
  ``projectProfiles``, ``tags``, ``inboxId``.
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..config import Config
from .dates import encode_due
from .errors import APIError, PayloadError
from .models import Column, Member, Project, Tag, Task
from .transport import Transport

__all__ = ["TickTickClient"]


def _new_object_id() -> str:
    """A 24-hex MongoDB-style ObjectId (4-byte time + 8 random bytes).

    TickTick task/project ids are client-generated ObjectIds; the server accepts
    ours and echoes them back in ``id2etag`` (confirmed live).
    """
    return format(int(time.time()), "08x") + os.urandom(8).hex()


class TickTickClient:
    """Typed wrapper over the v2 API. Construct once; methods are synchronous."""

    def __init__(self, config: Config, *, transport: Transport | None = None) -> None:
        self._config = config
        self._t = transport if transport is not None else Transport(config)
        self._default_tz = config.default_timezone
        self._inbox_id: str | None = None

    def close(self) -> None:
        self._t.close()

    def __enter__(self) -> "TickTickClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- shared helpers ------------------------------------------------------

    @property
    def inbox_id(self) -> str:
        """The account inbox project id, fetched once and cached."""
        if self._inbox_id is None:
            state = self._t.request("GET", "batch/check/0")
            inbox = state.get("inboxId") if isinstance(state, dict) else None
            if not inbox:
                raise PayloadError("Could not determine the inbox id from batch/check.")
            self._inbox_id = inbox
        return self._inbox_id

    @staticmethod
    def _check_batch(resp: Any, item_id: str, what: str) -> str | None:
        """Validate a batch response and return the new etag for ``item_id``.

        Raises:
            PayloadError: response wasn't the expected ``id2etag``/``id2error`` shape.
            APIError: the server reported an error for our item.
        """
        if not isinstance(resp, dict) or "id2etag" not in resp:
            raise PayloadError(f"Unexpected batch response for {what}: {resp!r}.")
        errors = resp.get("id2error") or {}
        if item_id in errors:
            raise APIError(f"TickTick rejected the {what}: {errors[item_id]}.")
        return (resp.get("id2etag") or {}).get(item_id)

    @staticmethod
    def _check_tag_batch(resp: Any, what: str) -> None:
        """Validate a tag batch response.

        Tag batch calls do not reliably return an etag keyed by tag name, so the
        only stable failure signal is a non-empty ``id2error``.
        """
        if not isinstance(resp, dict) or "id2error" not in resp:
            raise PayloadError(f"Unexpected batch response for {what}: {resp!r}.")
        if resp.get("id2error") or {}:
            raise APIError(f"TickTick rejected the {what}: {resp['id2error']}.")

    @staticmethod
    def _tag_name(label_or_name: str) -> str:
        """TickTick keys tags by lowercased name."""
        return label_or_name.lower()

    def _today(self) -> date:
        try:
            tz = ZoneInfo(self._default_tz)
        except (ZoneInfoNotFoundError, ValueError):
            tz = ZoneInfo("UTC")
        return datetime.now(tz).date()

    def _full_state(self) -> dict[str, Any]:
        state = self._t.request("GET", "batch/check/0")
        if not isinstance(state, dict):
            raise PayloadError("batch/check returned an unexpected non-object body.")
        return state

    def _raw_tasks(self) -> list[dict[str, Any]]:
        bean = self._full_state().get("syncTaskBean") or {}
        tasks = bean.get("update") if isinstance(bean, dict) else None
        if not isinstance(tasks, list):
            raise PayloadError("batch/check did not include syncTaskBean.update.")
        if not all(isinstance(item, dict) for item in tasks):
            raise PayloadError("batch/check returned a malformed task list.")
        return tasks

    def _raw_projects(self) -> list[dict[str, Any]]:
        projects = self._full_state().get("projectProfiles")
        if not isinstance(projects, list):
            raise PayloadError("batch/check did not include projectProfiles.")
        if not all(isinstance(item, dict) for item in projects):
            raise PayloadError("batch/check returned a malformed project list.")
        return projects

    def _raw_tags(self) -> list[dict[str, Any]]:
        tags = self._full_state().get("tags")
        if not isinstance(tags, list):
            raise PayloadError("batch/check did not include tags.")
        if not all(isinstance(item, dict) for item in tags):
            raise PayloadError("batch/check returned a malformed tag list.")
        return tags

    def _raw_completed_tasks(
        self, *, project_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Completed tasks — fetched from the completed endpoint, NOT batch/check.

        ``batch/check/0`` only returns uncompleted tasks, so completed items are
        invisible there (confirmed live). They live at ``project/all/completed/``
        (or per-project ``project/{id}/completed/``).
        """
        scope = project_id if project_id else "all"
        res = self._t.request(
            "GET", f"project/{scope}/completed/", params={"limit": limit}
        )
        if not isinstance(res, list):
            raise PayloadError("completed-tasks endpoint returned a non-list body.")
        return [item for item in res if isinstance(item, dict)]

    def _find_raw_task(self, task_id: str, *, kind: str | None = None) -> dict[str, Any]:
        # Search open tasks first, then fall back to completed (which are absent
        # from batch/check) so get/update/delete work on a completed task too.
        for raw in self._raw_tasks():
            if raw.get("id") == task_id and not raw.get("deleted"):
                if kind is None or raw.get("kind") == kind:
                    return dict(raw)
        for raw in self._raw_completed_tasks():
            if raw.get("id") == task_id and not raw.get("deleted"):
                if kind is None or raw.get("kind") == kind:
                    return dict(raw)
        noun = "note" if kind == "NOTE" else "task"
        raise APIError(f"No {noun} found with id {task_id!r}.")

    def _find_raw_project(self, project_id: str) -> dict[str, Any]:
        for raw in self._raw_projects():
            if raw.get("id") == project_id:
                return dict(raw)
        raise APIError(f"No project found with id {project_id!r}.")

    def _find_raw_tag(self, name: str) -> dict[str, Any]:
        tag_name = self._tag_name(name)
        for raw in self._raw_tags():
            if self._tag_name(str(raw.get("name"))) == tag_name:
                return dict(raw)
        raise APIError(f"No tag found with name {name!r}.")

    def _add_task_payload(self, payload: dict[str, Any]) -> Task:
        """POST a single task ``add`` and return the parsed Task."""
        resp = self._t.request(
            "POST", "batch/task", json={"add": [payload], "update": [], "delete": []}
        )
        payload["etag"] = self._check_batch(resp, payload["id"], "task")
        return Task.from_api(payload)

    def _update_task_payload(self, payload: dict[str, Any], what: str = "task") -> Task:
        """POST a single task ``update`` and return the parsed Task."""
        resp = self._t.request(
            "POST", "batch/task", json={"add": [], "update": [payload], "delete": []}
        )
        payload["etag"] = self._check_batch(resp, payload["id"], what)
        return Task.from_api(payload)

    def _delete_task_payload(self, payload: dict[str, Any], what: str = "task") -> Task:
        """POST a single task ``delete`` and return the deleted Task model."""
        task_id = payload["id"]
        project_id = payload.get("projectId")
        if not project_id:
            raise PayloadError(f"Cannot delete {what} {task_id!r} without projectId.")
        resp = self._t.request(
            "POST",
            "batch/task",
            json={
                "add": [],
                "update": [],
                "delete": [{"taskId": task_id, "projectId": project_id}],
            },
        )
        self._check_batch(resp, task_id, what)
        return Task.from_api(payload)

    @staticmethod
    def _due_day(task: Task) -> date | None:
        if isinstance(task.due, datetime):
            return task.due.date()
        return task.due

    # -- reference methods (Slice 2 Part A) ----------------------------------

    def create_task(
        self,
        title: str,
        *,
        project_id: str | None = None,
        content: str | None = None,
        due: date | datetime | None = None,
        priority: int = 0,
        timezone: str | None = None,
    ) -> Task:
        """Create a task. **This is the canonical reference method** — it implements
        the all-day date contract that every other dated task method reuses.

        Args:
            title: Task title.
            project_id: Target project; defaults to the inbox.
            content: Optional body text.
            due: A ``date`` (no time) → an **all-day** task; a ``datetime`` → a
                **timed** task. This single distinction drives the whole contract.
            priority: 0 (none), 1 (low), 3 (medium), 5 (high) — TickTick's scale.
            timezone: IANA zone for a *timed* ``due``; defaults to the client's
                ``TICKTICK_TIMEZONE``. Ignored for all-day (always UTC midnight).

        Returns:
            The created :class:`Task`, with ``due`` round-tripped through the
            contract (a date-only ``due`` comes back as a ``date``, never midnight).
        """
        payload: dict[str, Any] = {
            "id": _new_object_id(),
            "projectId": project_id or self.inbox_id,
            "title": title,
            "priority": priority,
        }
        if content is not None:
            payload["content"] = content
        if due is not None:
            due_str, tz, is_all_day = encode_due(due, timezone or self._default_tz)
            payload.update(
                isAllDay=is_all_day, startDate=due_str, dueDate=due_str, timeZone=tz
            )
        return self._add_task_payload(payload)

    def create_note(
        self, title: str, content: str, *, project_id: str | None = None
    ) -> Task:
        """Create a Markdown note (a task with ``kind == "NOTE"``).

        Confirmed live: a note-kind task renders ``content`` as Markdown in TickTick.

        Args:
            title: Note title.
            content: Markdown body.
            project_id: Target project; defaults to the inbox.
        """
        payload: dict[str, Any] = {
            "id": _new_object_id(),
            "projectId": project_id or self.inbox_id,
            "title": title,
            "kind": "NOTE",
            "content": content,
        }
        return self._add_task_payload(payload)

    def create_project(self, name: str, *, color: str | None = None) -> Project:
        """Create a project via the ``batch/project`` endpoint.

        Args:
            name: Project name.
            color: Optional hex color like ``"#4CA1FF"``.
        """
        payload: dict[str, Any] = {"id": _new_object_id(), "name": name}
        if color is not None:
            payload["color"] = color
        resp = self._t.request(
            "POST", "batch/project", json={"add": [payload], "update": [], "delete": []}
        )
        payload["etag"] = self._check_batch(resp, payload["id"], "project")
        return Project.from_api(payload)

    def create_tag(self, label: str, *, color: str | None = None) -> Tag:
        """Create a tag via the ``batch/tag`` endpoint.

        TickTick keys tags by a lowercased ``name``; ``label`` is the display form.

        Args:
            label: Display label (e.g. ``"Deep Work"``).
            color: Optional hex color.
        """
        name = self._tag_name(label)
        payload: dict[str, Any] = {"name": name, "label": label}
        if color is not None:
            payload["color"] = color
        resp = self._t.request(
            "POST", "batch/tag", json={"add": [payload], "update": [], "delete": []}
        )
        self._check_tag_batch(resp, "tag")
        return Tag.from_api(payload)

    # -- remaining methods (Slice 2 Part B) ---------------------------------

    def get_task(self, task_id: str) -> Task:
        """Read one task by id from the full-state endpoint."""
        return Task.from_api(self._find_raw_task(task_id))

    def list_tasks(
        self,
        *,
        project_id: str | None = None,
        due_today: bool = False,
        overdue: bool = False,
        include_completed: bool = False,
        completed_limit: int = 100,
    ) -> list[Task]:
        """List tasks, optionally filtered by project, today, or overdue.

        ``include_completed`` pulls completed tasks from the completed endpoint
        (capped at ``completed_limit``), since they are not in batch/check.
        """
        if due_today and overdue:
            raise ValueError("due_today and overdue cannot both be true.")

        today = self._today()
        raws = list(self._raw_tasks())
        if include_completed:
            raws += self._raw_completed_tasks(project_id=project_id, limit=completed_limit)

        tasks: list[Task] = []
        for raw in raws:
            if raw.get("deleted") or raw.get("kind") == "NOTE":
                continue
            task = Task.from_api(raw)
            if project_id is not None and task.project_id != project_id:
                continue
            if not include_completed and task.status == 2:
                continue
            due_day = self._due_day(task)
            if due_today and due_day != today:
                continue
            if overdue and (due_day is None or due_day >= today):
                continue
            tasks.append(task)
        return tasks

    def update_task(
        self,
        task_id: str,
        *,
        title: str | None = None,
        content: str | None = None,
        due: date | datetime | None = None,
        clear_due: bool = False,
        priority: int | None = None,
        project_id: str | None = None,
        tags: list[str] | None = None,
        timezone: str | None = None,
    ) -> Task:
        """Update a task via ``batch/task`` while preserving existing date fields."""
        if due is not None and clear_due:
            raise ValueError("due and clear_due cannot both be supplied.")

        payload = self._find_raw_task(task_id)
        if title is not None:
            payload["title"] = title
        if content is not None:
            payload["content"] = content
        if priority is not None:
            payload["priority"] = priority
        if project_id is not None:
            payload["projectId"] = project_id
        if tags is not None:
            payload["tags"] = [self._tag_name(tag) for tag in tags]
        if clear_due:
            for key in ("isAllDay", "startDate", "dueDate", "timeZone"):
                payload.pop(key, None)
        elif due is not None:
            due_str, tz, is_all_day = encode_due(due, timezone or self._default_tz)
            payload.update(
                isAllDay=is_all_day, startDate=due_str, dueDate=due_str, timeZone=tz
            )
        return self._update_task_payload(payload)

    def complete_task(self, task_id: str) -> Task:
        """Mark a task complete by setting ``status`` to TickTick's completed value."""
        payload = self._find_raw_task(task_id)
        payload["status"] = 2
        return self._update_task_payload(payload)

    def delete_task(self, task_id: str, *, project_id: str | None = None) -> Task:
        """Delete a task via ``batch/task`` and return the deleted task model."""
        payload = self._find_raw_task(task_id)
        if project_id is not None:
            payload["projectId"] = project_id
        return self._delete_task_payload(payload)

    def get_project(self, project_id: str) -> Project:
        """Read one project by id from the full-state endpoint."""
        return Project.from_api(self._find_raw_project(project_id))

    def list_projects(self, *, include_closed: bool = False) -> list[Project]:
        """List projects from the full-state endpoint."""
        projects: list[Project] = []
        for raw in self._raw_projects():
            project = Project.from_api(raw)
            if not include_closed and project.closed:
                continue
            projects.append(project)
        return projects

    def list_columns(self, project_id: str) -> list[Column]:
        """List a project's kanban columns (id → name).

        Endpoint confirmed live: ``GET column/project/{projectId}`` →
        ``[{id, projectId, name, sortOrder, ...}, ...]``. Use the returned ids as
        ``column_id`` on create/update to place or move an item.
        """
        res = self._t.request("GET", f"column/project/{project_id}")
        if not isinstance(res, list):
            raise PayloadError("column endpoint returned a non-list body.")
        return [Column.from_api(raw) for raw in res if isinstance(raw, dict)]

    def list_project_members(self, project_id: str) -> list[Member]:
        """List a shared project's members (resolve a person → assignee id).

        Endpoint confirmed live: ``GET project/{projectId}/users`` (plural — the
        singular ``/user`` is a decoy that returns bare ``true``). Use the
        returned ``user_id`` as ``assignee`` on create/update.
        """
        res = self._t.request("GET", f"project/{project_id}/users")
        if not isinstance(res, list):
            raise PayloadError("project users endpoint returned a non-list body.")
        return [Member.from_api(raw) for raw in res if isinstance(raw, dict)]

    def update_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        color: str | None = None,
        group_id: str | None = None,
        kind: str | None = None,
    ) -> Project:
        """Update a project via ``batch/project``."""
        payload = self._find_raw_project(project_id)
        if name is not None:
            payload["name"] = name
        if color is not None:
            payload["color"] = color
        if group_id is not None:
            payload["groupId"] = group_id
        if kind is not None:
            payload["kind"] = kind
        resp = self._t.request(
            "POST", "batch/project", json={"add": [], "update": [payload], "delete": []}
        )
        payload["etag"] = self._check_batch(resp, project_id, "project")
        return Project.from_api(payload)

    def delete_project(self, project_id: str) -> Project:
        """Delete a project via ``batch/project`` and return the deleted project."""
        payload = self._find_raw_project(project_id)
        resp = self._t.request(
            "POST", "batch/project", json={"add": [], "update": [], "delete": [project_id]}
        )
        self._check_batch(resp, project_id, "project")
        return Project.from_api(payload)

    def list_tags(self) -> list[Tag]:
        """List tags from the full-state endpoint."""
        return [Tag.from_api(raw) for raw in self._raw_tags()]

    def rename_tag(
        self, name: str, new_label: str, *, color: str | None = None
    ) -> Tag:
        """Rename a tag display label via ``batch/tag``."""
        payload = self._find_raw_tag(name)
        payload["name"] = self._tag_name(str(payload["name"]))
        payload["label"] = new_label
        if color is not None:
            payload["color"] = color
        resp = self._t.request(
            "POST", "batch/tag", json={"add": [], "update": [payload], "delete": []}
        )
        self._check_tag_batch(resp, "tag")
        return Tag.from_api(payload)

    def delete_tag(self, name: str) -> Tag:
        """Delete a tag by name.

        Tag deletion is not a batch operation; ``batch/tag`` delete is a no-op.
        """
        payload = self._find_raw_tag(name)
        tag_name = self._tag_name(str(payload["name"]))
        self._t.request("DELETE", f"tag?name={quote(tag_name, safe='')}")
        return Tag.from_api(payload)

    def add_tag_to_task(self, task_id: str, tag_name: str) -> Task:
        """Apply a tag to a task by updating the task's tag list."""
        payload = self._find_raw_task(task_id)
        tag = self._tag_name(tag_name)
        tags = [self._tag_name(str(item)) for item in payload.get("tags") or []]
        if tag not in tags:
            tags.append(tag)
        payload["tags"] = tags
        return self._update_task_payload(payload)

    def remove_tag_from_task(self, task_id: str, tag_name: str) -> Task:
        """Remove a tag from a task by updating the task's tag list."""
        payload = self._find_raw_task(task_id)
        tag = self._tag_name(tag_name)
        payload["tags"] = [
            self._tag_name(str(item))
            for item in payload.get("tags") or []
            if self._tag_name(str(item)) != tag
        ]
        return self._update_task_payload(payload)

    def get_note(self, note_id: str) -> Task:
        """Read one Markdown note by id."""
        return Task.from_api(self._find_raw_task(note_id, kind="NOTE"))

    def list_notes(
        self,
        *,
        project_id: str | None = None,
        include_completed: bool = False,
        completed_limit: int = 100,
    ) -> list[Task]:
        """List Markdown notes, optionally filtered by project."""
        raws = list(self._raw_tasks())
        if include_completed:
            raws += self._raw_completed_tasks(project_id=project_id, limit=completed_limit)

        notes: list[Task] = []
        for raw in raws:
            if raw.get("deleted") or raw.get("kind") != "NOTE":
                continue
            note = Task.from_api(raw)
            if project_id is not None and note.project_id != project_id:
                continue
            if not include_completed and note.status == 2:
                continue
            notes.append(note)
        return notes

    def update_note(
        self,
        note_id: str,
        *,
        title: str | None = None,
        content: str | None = None,
        project_id: str | None = None,
    ) -> Task:
        """Update a Markdown note via ``batch/task``."""
        payload = self._find_raw_task(note_id, kind="NOTE")
        if title is not None:
            payload["title"] = title
        if content is not None:
            payload["content"] = content
        if project_id is not None:
            payload["projectId"] = project_id
        payload["kind"] = "NOTE"
        return self._update_task_payload(payload, "note")

    def delete_note(self, note_id: str) -> Task:
        """Delete a Markdown note via ``batch/task``."""
        return self._delete_task_payload(self._find_raw_task(note_id, kind="NOTE"), "note")
