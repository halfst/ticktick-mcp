# v0.2.0 — Columns + Assignee

**Status:** Approved design, pre-implementation.
**Date:** 2026-06-13.
**Scope:** Additive only. No breaking changes to existing tools or payloads.

## Why

The Issues & Decisions workflow runs on a kanban board (New / Open / Hold /
Closed) and on shared-project assignment. Today the MCP drops both: `Task` uses
`extra="ignore"`, so the wire `columnId` and `assignee` fields never reach the
caller, there is no way to list a project's columns or members, and no way to
move an item between columns or assign it. This makes "surface everything not
yet Closed" and "move to Closed" manual, and "assign the meal to the cook"
impossible through the MCP.

## Recon (ground truth, verified live 2026-06-13)

Read-only probes against the live account confirmed every assumption:

- **Columns list:** `GET column/project/{projectId}` returns
  `[{id, projectId, name, sortOrder, createdTime, modifiedTime, etag}, ...]`.
  For Issues & Decisions it returned New / Hold / Closed / Open with ids.
- **Column on items:** every task/note carries `columnId` on the wire (111 of
  129 open items had one). The I&D note sat in column `2c46409ab2088ff6cf274c56`
  ("New"). Column-bearing projects have `viewMode: "kanban"`.
- **Assignee on items:** `assignee` is a first-class wire field (a numeric user
  id; unassigned items omit it or carry `0`).
- **Member roster:** `GET project/{projectId}/users` returns
  `[{recordId, userId, username, displayName, isOwner, isAccept, permission,
  ...}, ...]` — e.g. `userId: 119973298 / displayName: "Ethan"` and
  `userId: 121024798 / displayName: "AnnemarieLewis"`. Name → id resolution is a
  real, reachable endpoint.
- **Dead ends (do not use):** `project/{id}/user` returns bare `true`;
  `.../member(s)`, `share/getShareRecord`, `batch/column` all 404/405/500.

## Design decisions (settled in brainstorming)

1. **Scope:** ship columns *and* assignee in v0.2.0.
2. **Read shape — IDs only (lean):** items carry raw `column_id` and `assignee`;
   names come from separate `list_columns` / `list_project_members` tools the
   caller joins against. No per-list enrichment, so `list_tasks`/`list_notes`
   make no extra round-trips.
3. **Write inputs — by id, on create + update:** all of `create_task`,
   `create_note`, `update_task`, `update_note` accept `column_id` and `assignee`
   (a user id). Deterministic; the caller resolves names first via the new list
   tools. No server-side fuzzy name matching.

## Changes by layer

### `client/models.py`

Two new models:

- `Column` — `id: str`, `project_id: str | None`, `name: str`,
  `sort_order: int | None`, `etag: str | None`; `from_api` maps
  `projectId`/`sortOrder`.
- `Member` — `user_id: int`, `display_name: str`, `username: str | None`,
  `is_owner: bool`, `permission: str | None`; `from_api` maps
  `userId`/`displayName`/`isOwner`.

Two new fields on `Task` (and their `from_api` mapping):

- `column_id: str | None = None` ← `columnId`.
- `assignee: int | None = None` ← `assignee`, normalizing `0`/falsy → `None`.

### `client/client.py`

New read methods:

- `list_columns(project_id) -> list[Column]` — `GET column/project/{project_id}`;
  validate a list body, parse each into `Column`.
- `list_project_members(project_id) -> list[Member]` —
  `GET project/{project_id}/users`; validate a list body, parse each into
  `Member`. (Note: the bare `project/{id}/user` singular endpoint is a decoy —
  use the plural `users`.)

Threaded write params (set the corresponding wire field in the payload; omit
when `None` so existing behavior is unchanged):

- `create_task(..., column_id: str | None = None, assignee: int | None = None)`
  → set `columnId` / `assignee` on the add-payload.
- `create_note(..., column_id: str | None = None, assignee: int | None = None)`
  → same.
- `update_task(..., column_id: str | None = None, assignee: int | None = None)`
  → set on the re-POSTed raw payload.
- `update_note(..., column_id: str | None = None, assignee: int | None = None)`
  → same.

Unassign / move-off semantics (passing `assignee=0`, and whether a sentinel is
needed to *clear* assignment) are pinned down by the live write test below
before the methods are finalized.

### `server/handlers.py`

- Add `_column_dict` / `_member_dict` serializers (mirror `_task_dict`).
- New handlers `list_columns(client, *, project_id)` →
  `{"columns": [...]}` and `list_project_members(client, *, project_id)` →
  `{"members": [...]}`, both `@_safe`.
- Thread `column_id` / `assignee` through the existing `create_task`,
  `create_note`, `update_task`, `update_note` handlers.
- Add the new handler names to `__all__`.

### `server/app.py`

- Two new `@mcp.tool` functions: `list_columns(project_id)` and
  `list_project_members(project_id)`, each delegating to its handler, with
  docstrings explaining that ids returned here feed `column_id` / `assignee`.
- Add `column_id` and `assignee` params (with docstring lines) to the
  `create_task`, `create_note`, `update_task`, `update_note` tools.
- Tool count: 22 → 24.

## Implementation gate: live write verification

Before finalizing the write path, run one self-cleaning live test (the
established `set -a; . ./.env; set +a; PYTHONPATH=. python /tmp/x.py` pattern,
cleanup in `finally`) on a shared kanban project, confirming:

1. Setting `columnId` via the existing `batch/task` update actually moves the
   item between columns (read back via `batch/check`).
2. Setting `assignee` via `batch/task` update sticks — or, if it does not,
   identify the dedicated assign endpoint. Any such endpoint change is contained
   to the one client write method.
3. What value unassigns (`assignee: 0` vs field removal).

This gate exists because the v2 API is reverse-engineered; the live round-trip
has caught every real bug in this project (silent tag-delete no-op,
invisible completed tasks).

## Testing

- **Unit (mocked transport):** `Column`/`Member` `from_api`; `Task.from_api`
  surfacing `column_id`/`assignee` (incl. `assignee: 0` → `None`); `list_columns`
  / `list_project_members` request paths + parsing; the four threaded write
  methods sending the right payload fields (and omitting them when `None`);
  handler shapes (`{"columns": ...}`, `{"members": ...}`, error wrapping); the
  two new tools registered.
- **Live (self-cleaning):** the implementation-gate round-trip above, kept as an
  opt-in live test alongside the existing ones.

## Versioning & docs

- Bump `pyproject.toml` version → `0.2.0` and `compose.yaml` / README image refs
  → `0.2.0`.
- README: extend the tool list with `list_columns` + `list_project_members` and
  the new `column_id`/`assignee` params; note that column/assignee writes need a
  shared or kanban project.
- DESIGN.md: short note on the columns + assignee contract and the
  `GET column/project/{id}` / `GET project/{id}/users` endpoints.
- Release per usual flow: tag `v0.2.0` (CI builds + publishes multi-arch to GHCR
  + Gitea); GitHub Release object cut in the UI.

## Out of scope (YAGNI)

- Inline `column_name` / `assignee_name` enrichment on items (rejected: extra
  per-list round-trips; caller joins against the list tools instead).
- Server-side fuzzy name → id resolution.
- Creating / renaming / deleting columns; adding / removing project members.
- A separate start-date field (noted as a known limitation; not needed here).
