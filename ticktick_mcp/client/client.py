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

from ..config import Config
from .dates import encode_due
from .errors import APIError, PayloadError
from .models import Project, Tag, Task
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
    def _check_batch(resp: Any, item_id: str, what: str) -> str:
        """Validate a batch response and return the new etag for ``item_id``.

        Raises:
            PayloadError: response wasn't the expected ``id2etag``/``id2error`` shape.
            APIError: the server reported an error for our item.
        """
        if not isinstance(resp, dict) or "id2etag" not in resp:
            raise PayloadError(f"Unexpected response creating {what}: {resp!r}.")
        errors = resp.get("id2error") or {}
        if item_id in errors:
            raise APIError(f"TickTick rejected the {what}: {errors[item_id]}.")
        return (resp.get("id2etag") or {}).get(item_id)

    def _add_task_payload(self, payload: dict[str, Any]) -> Task:
        """POST a single task ``add`` and return the parsed Task."""
        resp = self._t.request(
            "POST", "batch/task", json={"add": [payload], "update": [], "delete": []}
        )
        payload["etag"] = self._check_batch(resp, payload["id"], "task")
        return Task.from_api(payload)

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
        name = label.lower()
        payload: dict[str, Any] = {"name": name, "label": label}
        if color is not None:
            payload["color"] = color
        resp = self._t.request(
            "POST", "batch/tag", json={"add": [payload], "update": [], "delete": []}
        )
        # Tags are keyed by name, not by a generated id; a non-empty id2error means
        # failure. Treat any reported error as fatal.
        if isinstance(resp, dict) and (resp.get("id2error") or {}):
            raise APIError(f"TickTick rejected the tag: {resp['id2error']}.")
        return Tag.from_api(payload)
