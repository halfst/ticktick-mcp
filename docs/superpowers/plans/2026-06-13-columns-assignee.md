# Columns + Assignee (v0.2.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose TickTick kanban columns and task/note assignees through the MCP — read them on items, list a project's columns and members, and write them on create/update.

**Architecture:** Strictly additive, following the existing `model → client method → handler → thin tool` spine. New `Column`/`Member` models; `column_id`/`assignee` surfaced on `Task`; two new read endpoints (`GET column/project/{id}`, `GET project/{id}/users`); write fields threaded through the existing create/update flows (which already re-POST the full raw payload). All endpoint shapes were verified live against the real account on 2026-06-13 (see the design spec).

**Tech Stack:** Python 3.11+, pydantic v2, FastMCP, httpx; pytest with a fake-transport / fake-client pattern (no network in unit tests) plus one opt-in self-cleaning live test.

**Spec:** `docs/superpowers/specs/2026-06-13-columns-assignee-design.md`

---

## File map

- `ticktick_mcp/client/models.py` — add `column_id`/`assignee` to `Task`; add `Column` and `Member` models. (modify)
- `ticktick_mcp/client/__init__.py` — export `Column`, `Member`. (modify)
- `ticktick_mcp/client/client.py` — `list_columns`, `list_project_members`; thread `column_id`/`assignee` into `create_task`/`create_note`/`update_task`/`update_note`. (modify)
- `ticktick_mcp/server/handlers.py` — `_column_dict`/`_member_dict`; `list_columns`/`list_project_members` handlers; thread params; `__all__`. (modify)
- `ticktick_mcp/server/app.py` — two new `@mcp.tool`s; new params on four tools. (modify)
- `tests/test_client_methods.py` — extend `FakeTransport`; model + client tests. (modify)
- `tests/test_server.py` — extend `FakeClient`; handler + registration tests. (modify)
- `pyproject.toml`, `compose.yaml`, `README.md`, `DESIGN.md` — version bump + docs. (modify)

---

### Task 1: Surface `column_id` + `assignee` on the `Task` model

**Files:**
- Modify: `ticktick_mcp/client/models.py:23-63`
- Test: `tests/test_client_methods.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_client_methods.py` (it already imports `Task`):

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. python -m pytest tests/test_client_methods.py -k "column_and_assignee or zero_assignee" -v`
Expected: FAIL — `AttributeError`/validation: `Task` has no `column_id`/`assignee`.

- [ ] **Step 3: Add the fields and mapping**

In `models.py`, in class `Task`, after the `tags` field (line 39) add:

```python
    column_id: str | None = None
    assignee: int | None = None
```

In `Task.from_api`, inside the `cls(...)` call (after `tags=...`, before `etag=...`), add:

```python
            column_id=raw.get("columnId"),
            assignee=raw.get("assignee") or None,
```

(`or None` collapses TickTick's `0`/absent "unassigned" to `None`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. python -m pytest tests/test_client_methods.py -k "column_and_assignee or zero_assignee" -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add ticktick_mcp/client/models.py tests/test_client_methods.py
git commit -m "feat(model): surface column_id + assignee on Task"
```

---

### Task 2: Add `Column` and `Member` models

**Files:**
- Modify: `ticktick_mcp/client/models.py` (`__all__` line 17, append classes after `Tag`)
- Modify: `ticktick_mcp/client/__init__.py:13,16-26`
- Test: `tests/test_client_methods.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_client_methods.py`, and update its import line to include the new models:

```python
from ticktick_mcp.client import APIError, Column, Member, Project, Tag, Task, TickTickClient
```

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. python -m pytest tests/test_client_methods.py -k "column_from_api or member_from_api" -v`
Expected: FAIL — `ImportError: cannot import name 'Column'`.

- [ ] **Step 3: Implement the models**

In `models.py`, change `__all__` (line 17) to:

```python
__all__ = ["Task", "Project", "Tag", "Column", "Member", "TaskKind"]
```

Append after the `Tag` class:

```python
class Column(BaseModel):
    """A kanban column (swimlane) within a project."""

    model_config = ConfigDict(extra="ignore")

    id: str
    project_id: str | None = None
    name: str = ""
    sort_order: int | None = None
    etag: str | None = None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "Column":
        return cls(
            id=raw["id"],
            project_id=raw.get("projectId"),
            name=raw.get("name") or "",
            sort_order=raw.get("sortOrder"),
            etag=raw.get("etag"),
        )


class Member(BaseModel):
    """A member of a shared project (for resolving a person to an assignee id)."""

    model_config = ConfigDict(extra="ignore")

    user_id: int
    display_name: str = ""
    username: str | None = None
    is_owner: bool = False
    permission: str | None = None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "Member":
        return cls(
            user_id=raw["userId"],
            display_name=raw.get("displayName") or "",
            username=raw.get("username"),
            is_owner=bool(raw.get("isOwner")),
            permission=raw.get("permission"),
        )
```

In `client/__init__.py`, change the models import (line 13) and `__all__`:

```python
from .models import Column, Member, Project, Tag, Task
```

Add `"Column"` and `"Member"` to the `__all__` list (after `"Tag"`).

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. python -m pytest tests/test_client_methods.py -k "column_from_api or member_from_api" -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add ticktick_mcp/client/models.py ticktick_mcp/client/__init__.py tests/test_client_methods.py
git commit -m "feat(model): add Column and Member models"
```

---

### Task 3: Extend `FakeTransport` to serve the two new GET endpoints

**Files:**
- Modify: `tests/test_client_methods.py` (`FakeTransport` ~lines 22-60; `make_client` ~lines 90-104)

This is test-infra only; no production code. It unblocks Tasks 4 and 5.

- [ ] **Step 1: Add `columns`/`members` to `FakeTransport.__init__`**

In `FakeTransport.__init__`, add two params and store them:

```python
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
        self.completed = completed or []
        self.columns = columns or []
        self.members = members or []
```

- [ ] **Step 2: Route the new paths in `FakeTransport.request`**

In `request`, add these two branches just after the `batch/check/0` branch:

```python
        if path.startswith("column/project/"):
            return self.columns
        if path.startswith("project/") and path.endswith("/users"):
            return self.members
```

- [ ] **Step 3: Thread the params through `make_client`**

Update `make_client`'s signature and the `FakeTransport(...)` construction to pass `columns` and `members`:

```python
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
```

- [ ] **Step 4: Run the existing suite to confirm nothing broke**

Run: `PYTHONPATH=. python -m pytest tests/test_client_methods.py -q`
Expected: PASS (all existing tests still green — this only adds optional params).

- [ ] **Step 5: Commit**

```bash
git add tests/test_client_methods.py
git commit -m "test: fake transport serves column + members endpoints"
```

---

### Task 4: `list_columns` and `list_project_members` client methods

**Files:**
- Modify: `ticktick_mcp/client/client.py` (import line 31; new methods near the other list methods)
- Test: `tests/test_client_methods.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

Note: `FakeTransport.request` records `(method, path, deepcopy(json))`; GET calls have `json=None`, hence the `None` third element.

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. python -m pytest tests/test_client_methods.py -k "list_columns or list_project_members" -v`
Expected: FAIL — `AttributeError: 'TickTickClient' object has no attribute 'list_columns'`.

- [ ] **Step 3: Implement the methods**

In `client.py`, update the models import (line 31) to include the new types:

```python
from .models import Column, Member, Project, Tag, Task
```

Add these methods (place after `list_projects`, around line 439):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. python -m pytest tests/test_client_methods.py -k "list_columns or list_project_members" -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add ticktick_mcp/client/client.py tests/test_client_methods.py
git commit -m "feat(client): list_columns + list_project_members"
```

---

### Task 5: Thread `column_id` + `assignee` into `create_task` / `create_note`

**Files:**
- Modify: `ticktick_mcp/client/client.py` (`create_task` lines 233-273; `create_note` lines 275-294)
- Test: `tests/test_client_methods.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. python -m pytest tests/test_client_methods.py -k "create_task_sets_column or create_task_omits or create_note_sets_column" -v`
Expected: FAIL — `TypeError: create_task() got an unexpected keyword argument 'column_id'`.

- [ ] **Step 3: Add the params**

In `create_task`, extend the signature (add after `timezone: str | None = None,`):

```python
        column_id: str | None = None,
        assignee: int | None = None,
```

And before `return self._add_task_payload(payload)` add:

```python
        if column_id is not None:
            payload["columnId"] = column_id
        if assignee is not None:
            payload["assignee"] = assignee
```

In `create_note`, extend the signature (add after `project_id: str | None = None`):

```python
        column_id: str | None = None,
        assignee: int | None = None,
```

And before `return self._add_task_payload(payload)` add the same two `if` blocks as above.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. python -m pytest tests/test_client_methods.py -k "create_task_sets_column or create_task_omits or create_note_sets_column" -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add ticktick_mcp/client/client.py tests/test_client_methods.py
git commit -m "feat(client): accept column_id + assignee on create_task/create_note"
```

---

### Task 6: Thread `column_id` + `assignee` into `update_task` / `update_note`

**Files:**
- Modify: `ticktick_mcp/client/client.py` (`update_task` lines 376-412; `update_note` lines 553-570)
- Test: `tests/test_client_methods.py`

- [ ] **Step 1: Write the failing tests**

These rely on a task/note already present in `batch/check` state so `_find_raw_task` can locate it.

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. python -m pytest tests/test_client_methods.py -k "update_task_sets_column or update_note_sets_column" -v`
Expected: FAIL — `TypeError: update_task() got an unexpected keyword argument 'column_id'`.

- [ ] **Step 3: Add the params**

In `update_task`, extend the signature (add after `timezone: str | None = None,`):

```python
        column_id: str | None = None,
        assignee: int | None = None,
```

After the `tags` handling block (after the `payload["tags"] = ...` line, before the `if clear_due:` block) add:

```python
        if column_id is not None:
            payload["columnId"] = column_id
        if assignee is not None:
            payload["assignee"] = assignee
```

In `update_note`, extend the signature (add after `project_id: str | None = None,`):

```python
        column_id: str | None = None,
        assignee: int | None = None,
```

After the `if project_id is not None:` block (before `payload["kind"] = "NOTE"`) add the same two `if` blocks.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. python -m pytest tests/test_client_methods.py -k "update_task_sets_column or update_note_sets_column" -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add ticktick_mcp/client/client.py tests/test_client_methods.py
git commit -m "feat(client): accept column_id + assignee on update_task/update_note"
```

---

### Task 7: Handlers — new list handlers + threaded write params

**Files:**
- Modify: `ticktick_mcp/server/handlers.py` (imports line 20; `__all__` lines 22-46; serializers ~115-121; create/update handlers; new handlers)
- Modify: `tests/test_server.py` (`FakeClient` to add new methods/params)
- Test: `tests/test_server.py`

- [ ] **Step 1: Extend `FakeClient` in `tests/test_server.py`**

Update the model import at the top of `tests/test_server.py`:

```python
from ticktick_mcp.client.models import Column, Member, Project, Tag, Task
```

In `FakeClient`, update `create_task`, `create_note`, `update_task`, `update_note` to accept and record the new kwargs, and add the two list methods. Replace `FakeClient.create_task` and `FakeClient.update_task` signatures to include `column_id=None, assignee=None`, record them, and pass to the `Task(...)` (`column_id=column_id, assignee=assignee`). Add:

```python
    def create_note(self, title, content, *, project_id=None, column_id=None, assignee=None):
        self.calls.append(
            ("create_note", {"title": title, "column_id": column_id, "assignee": assignee})
        )
        return Task(
            id="n1", title=title, content=content, kind="NOTE",
            project_id=project_id or "inbox", column_id=column_id, assignee=assignee,
        )

    def update_note(self, note_id, *, title=None, content=None, project_id=None,
                    column_id=None, assignee=None):
        self.calls.append(
            ("update_note", {"note_id": note_id, "column_id": column_id, "assignee": assignee})
        )
        return Task(
            id=note_id, title=title or "N", content=content, kind="NOTE",
            project_id=project_id or "inbox", column_id=column_id, assignee=assignee,
        )

    def list_columns(self, project_id):
        self.calls.append(("list_columns", {"project_id": project_id}))
        return [Column(id="c1", project_id=project_id, name="Closed", sort_order=9)]

    def list_project_members(self, project_id):
        self.calls.append(("list_project_members", {"project_id": project_id}))
        return [Member(user_id=2, display_name="Annemarie", is_owner=False, permission="write")]
```

(If `FakeClient` already defines `create_note`/`update_note`, replace those definitions with the versions above rather than duplicating.)

- [ ] **Step 2: Write the failing handler tests**

```python
def test_list_columns_handler_wraps_in_columns_key() -> None:
    result = handlers.list_columns(FakeClient(), project_id="p1")
    assert result == {"columns": [{"id": "c1", "project_id": "p1", "name": "Closed",
                                    "sort_order": 9, "etag": None}]}


def test_list_members_handler_wraps_in_members_key() -> None:
    result = handlers.list_project_members(FakeClient(), project_id="p1")
    assert result["members"][0]["display_name"] == "Annemarie"
    assert result["members"][0]["user_id"] == 2


def test_create_task_handler_threads_column_and_assignee() -> None:
    fc = FakeClient()
    out = handlers.create_task(fc, title="X", column_id="c1", assignee=2)
    assert ("create_task", {"title": "X", "due": None, "timezone": None}) not in fc.calls  # sanity
    assert out["column_id"] == "c1" and out["assignee"] == 2


def test_update_note_handler_threads_column() -> None:
    fc = FakeClient()
    out = handlers.update_note(fc, note_id="n1", column_id="c1")
    assert out["column_id"] == "c1"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `PYTHONPATH=. python -m pytest tests/test_server.py -k "list_columns_handler or list_members_handler or threads_column" -v`
Expected: FAIL — `AttributeError: module 'handlers' has no attribute 'list_columns'` (and `TypeError` on the threaded create/update once that is reached).

- [ ] **Step 4: Implement the handler changes**

In `handlers.py`, update the import (line 20):

```python
from ..client.models import Column, Member, Project, Tag, Task
```

Add to `__all__`: `"list_columns"` and `"list_project_members"`.

Add serializers next to `_task_dict` (after `_tag_dict`):

```python
def _column_dict(column: Column) -> dict[str, Any]:
    return column.model_dump(mode="json")


def _member_dict(member: Member) -> dict[str, Any]:
    return member.model_dump(mode="json")
```

Update `create_task` handler: add `column_id: str | None = None, assignee: int | None = None` to its signature and pass `column_id=column_id, assignee=assignee` into `client.create_task(...)`.

Update `create_note` handler: add `column_id: str | None = None, assignee: int | None = None` and pass them into `client.create_note(...)`.

Update `update_task` handler: add `column_id: str | None = None, assignee: int | None = None` and pass them into `client.update_task(...)`.

Update `update_note` handler: add `column_id: str | None = None, assignee: int | None = None` and pass them into `client.update_note(...)`.

Add the two new handlers (after `list_projects`):

```python
@_safe
def list_columns(client: TickTickClient, *, project_id: str) -> dict[str, Any]:
    cols = client.list_columns(project_id)
    return {"columns": [_column_dict(c) for c in cols]}


@_safe
def list_project_members(client: TickTickClient, *, project_id: str) -> dict[str, Any]:
    members = client.list_project_members(project_id)
    return {"members": [_member_dict(m) for m in members]}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=. python -m pytest tests/test_server.py -k "list_columns_handler or list_members_handler or threads_column" -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add ticktick_mcp/server/handlers.py tests/test_server.py
git commit -m "feat(handlers): column/member list handlers + threaded write params"
```

---

### Task 8: Tools — two new tools + new params on four tools

**Files:**
- Modify: `ticktick_mcp/server/app.py` (`create_task` 45-80; `create_note` 83-99; `update_task` 157-197; `update_note` 407-431; add two new tools; `list_projects` is the insertion neighbor)
- Test: `tests/test_server.py` (registration test ~306-336)

- [ ] **Step 1: Update the registration test (failing)**

In `test_app_registers_reference_tools`, add to the asserted set:

```python
        "list_columns",
        "list_project_members",
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. python -m pytest tests/test_server.py -k "registers_reference_tools" -v`
Expected: FAIL — set difference: `list_columns`, `list_project_members` not registered.

- [ ] **Step 3: Add params to the four existing tools and pass them through**

In `create_task` tool: add params `column_id: str | None = None,` and `assignee: int | None = None,` to the signature; add to the docstring Args:

```
        column_id: Place the task in this kanban column id (from list_columns).
            Omit to use the project default. Only meaningful in kanban projects.
        assignee: User id to assign the task to (from list_project_members). Omit
            to leave unassigned. Only meaningful in shared projects.
```

Pass `column_id=column_id, assignee=assignee` into `handlers.create_task(...)`.

In `create_note` tool: add the same two params + docstring lines; pass into `handlers.create_note(...)`.

In `update_task` tool: add the same two params + docstring lines; pass into `handlers.update_task(...)`.

In `update_note` tool: add the same two params + docstring lines; pass into `handlers.update_note(...)`.

- [ ] **Step 4: Add the two new tools**

Insert after the `list_projects` tool (after line 250):

```python
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
```

- [ ] **Step 5: Run the registration test + full suite**

Run: `PYTHONPATH=. python -m pytest tests/test_server.py -q`
Expected: PASS (all green, including `registers_reference_tools`).

- [ ] **Step 6: Commit**

```bash
git add ticktick_mcp/server/app.py tests/test_server.py
git commit -m "feat(tools): list_columns + list_project_members; column_id/assignee on create/update"
```

---

### Task 9: Live write-verification gate (self-cleaning)

**Files:**
- Create (throwaway, not committed): `/tmp/verify_v020.py`
- Possibly modify: `ticktick_mcp/client/client.py` (only if assignee-write needs a dedicated endpoint)

This is the one piece recon could not settle without mutating live data: whether `columnId`/`assignee` set via `batch/task` actually stick. Run it before declaring the write path done.

- [ ] **Step 1: Write the self-cleaning verification script**

```python
"""v0.2.0 live write verification. Self-cleans in finally. NOT committed."""
from ticktick_mcp.config import load_config
from ticktick_mcp.client import TickTickClient

IND = "6571c4c49b06e092cbc8bb99"      # Issues & Decisions (shared, kanban, NOTE)
FAMILY = "656eb398016466861242bb8d"   # Family Tasks (shared, TASK)
ANNEMARIE = 121024798

client = TickTickClient(load_config())
created = []
try:
    cols = {c.name: c.id for c in client.list_columns(IND)}
    print("COLUMNS:", cols)
    members = {m.display_name: m.user_id for m in client.list_project_members(FAMILY)}
    print("MEMBERS:", members)

    # Column move: create a note in "New", move it to "Closed", read back.
    note = client.create_note("v0.2.0 column probe", "tmp", project_id=IND,
                              column_id=cols["New"])
    created.append(("note", note.id, IND))
    print("note created in column:", note.column_id, "==", cols["New"])
    client.update_note(note.id, column_id=cols["Closed"])
    moved = client.get_note(note.id)
    print("after move, column_id:", moved.column_id, "expected:", cols["Closed"],
          "OK" if moved.column_id == cols["Closed"] else "FAIL")

    # Assignee: create a task in Family Tasks, assign to Annemarie, read back.
    task = client.create_task("v0.2.0 assignee probe", project_id=FAMILY,
                              assignee=ANNEMARIE)
    created.append(("task", task.id, FAMILY))
    got = client.get_task(task.id)
    print("assignee after create:", got.assignee, "expected:", ANNEMARIE,
          "OK" if got.assignee == ANNEMARIE else "FAIL (needs dedicated endpoint)")

    # Unassign semantics: try assignee=0 via update, read back.
    client.update_task(task.id, assignee=0)
    got2 = client.get_task(task.id)
    print("assignee after assignee=0:", got2.assignee, "(None means 0 unassigns)")
finally:
    for kind, _id, pid in created:
        try:
            client.delete_note(_id) if kind == "note" else client.delete_task(_id, project_id=pid)
            print("cleaned", kind, _id)
        except Exception as e:
            print("CLEANUP FAILED", kind, _id, e)
    client.close()
```

- [ ] **Step 2: Run it against the live account**

Run: `set -a; . ./.env; set +a; PYTHONPATH=. python /tmp/verify_v020.py`
Expected: column move prints `OK`; assignee-after-create prints `OK`; cleanup lines print for every created item.

- [ ] **Step 3: Decide based on output**

- If assignee `OK`: the batch path works — no code change. Note in the build-state memory that batch assignee-write is confirmed, and what value unassigns (likely `assignee: 0` → reads back `None`).
- If assignee `FAIL`: the batch update does not assign. Probe the dedicated endpoint (e.g. `POST project/{projectId}/task/{taskId}/assign?assignee={uid}` or a batch `taskAssignee` field) with a follow-up throwaway script, then change **only** `create_task`/`update_task`'s assignee handling in `client.py` to call it. Re-run this script until assignee prints `OK`. Keep `column_id` on the batch path regardless (recon + this test confirm it).

- [ ] **Step 4: Commit any code change (only if Step 3 required one)**

```bash
git add ticktick_mcp/client/client.py
git commit -m "fix(client): assignee write via verified endpoint"
```

(If no change was needed, there is nothing to commit for this task.)

---

### Task 10: Version bump + docs

**Files:**
- Modify: `pyproject.toml` (version line)
- Modify: `compose.yaml:16`
- Modify: `README.md:37-46` (tool surface), `README.md:93` and `README.md:112` (image refs)
- Modify: `DESIGN.md` (add a columns/assignee note)

- [ ] **Step 1: Bump the version**

In `pyproject.toml`, change `version = "0.1.2"` → `version = "0.2.0"`.

- [ ] **Step 2: Bump image references**

In `compose.yaml` line 16: `image: ghcr.io/halfst/ticktick-mcp:0.1.2` → `:0.2.0`.
In `README.md`: change the compose block image (line ~93) `:0.1.2` → `:0.2.0`, and the text "tagged by version (`0.1.2`, `0.1`)" (line ~112) → "(`0.2.0`, `0.2`)".

- [ ] **Step 3: Extend the README tool surface**

In `README.md`, update the bullets (lines 37-46). Change the Tasks/Notes bullets and add a Columns/Members bullet:

```markdown
- **Tasks** — create, read, list (by project, due-today, overdue, completed),
  update, complete, delete; set a kanban `column_id` and an `assignee` on
  create/update.
- **Projects** — create, read, list, update, delete.
- **Columns & members** — list a project's kanban columns (id → name) and a
  shared project's members (resolve a person → assignee id).
- **Tags** — list, create, rename, delete, and add/remove on a task.
- **Markdown notes** — create, read, list, update, delete; also carry
  `column_id`/`assignee`.
```

- [ ] **Step 4: Add a DESIGN.md note**

Append a short subsection to `DESIGN.md` documenting: items carry `columnId`/`assignee` on the wire; columns are read via `GET column/project/{id}` and members via `GET project/{id}/users` (plural); writes set `columnId`/`assignee` on the existing `batch/task` payload (or, if Task 9 found otherwise, the verified assignee endpoint); read shape is ids-only by design.

- [ ] **Step 5: Run the full suite**

Run: `PYTHONPATH=. python -m pytest -q`
Expected: PASS (all unit tests green).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml compose.yaml README.md DESIGN.md
git commit -m "release: v0.2.0 — columns + assignee; bump version + docs"
```

Tagging/release (`git tag v0.2.0`, push, GitHub Release object) is done by the operator per the usual flow once the branch is merged.

---

## Self-review notes

- **Spec coverage:** Column read (Task 1), Column/Member models (Task 2), `list_columns`/`list_project_members` client (Task 4) + handlers/tools (Tasks 7-8), column/assignee write on all four create/update methods incl. notes (Tasks 5-6 client, 7 handlers, 8 tools), ids-only read shape (no enrichment task — by omission, as specified), live write gate (Task 9), version+docs incl. 22→24 tool count (Tasks 8, 10). All spec sections map to a task.
- **Type consistency:** `column_id: str | None`, `assignee: int | None` used identically across model, client, handlers, tools; `Column.sort_order`/`Member.user_id` names match between model and tests; handler wrap keys `{"columns": ...}`/`{"members": ...}` match tool docstrings and tests.
- **Placeholder scan:** no TBD/TODO; every code step shows full code; Task 9's conditional branch is explicit about what to do in each outcome.
