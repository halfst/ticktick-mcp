# CLIENT_METHODS.md — the client method pattern (Slice 2)

This is the contract for filling in the remaining `client/` endpoint methods
(**Part B**, Codex). Part A established the pattern with one reference method per
family in `ticktick_mcp/client/client.py`:

| Family  | Reference method (Part A)         |
|---------|-----------------------------------|
| Task    | `TickTickClient.create_task`      |
| Note    | `TickTickClient.create_note`      |
| Project | `TickTickClient.create_project`   |
| Tag     | `TickTickClient.create_tag`       |

**Copy these. Do not invent new conventions.** All endpoint paths and payload
shapes below were confirmed against a live v2 account (2026-06).

## The pattern (every method follows this)

1. **Typed inputs** — plain typed parameters; dates as `date | datetime` (see the
   date contract below). No raw dicts in the public signature.
2. **Build the payload** in camelCase wire shape. Client-generated items get a
   24-hex id from `_new_object_id()`.
3. **One transport call** — `self._t.request(method, path, json=...)`. Never build
   HTTP yourself; never call an endpoint from outside `client/`.
4. **Validate the batch response** with `self._check_batch(resp, item_id, what)`
   (raises `APIError` on `id2error`, `PayloadError` on a malformed body) and pull
   the new `etag`.
5. **Return a typed model** via `Task.from_api` / `Project.from_api` / `Tag.from_api`.
6. **Errors** follow DESIGN.md §4 — let the typed exceptions propagate; don't catch
   and return `None`.

## The date contract (DESIGN.md §3) — reuse, never reimplement

`client/dates.py` already solves this. Any method that writes a due date calls
`encode_due(due, tz)`; any method that reads one relies on `Task.from_api`, which
calls `decode_due`. **Do not hand-roll date math.**

- A bare `date` ⇒ **all-day**, encoded at UTC midnight (`...T00:00:00.000+0000`,
  `timeZone:"UTC"`). A `datetime` ⇒ **timed**, converted to UTC.
- Update/complete must preserve `isAllDay` + the existing date when not changing it.

## Confirmed endpoints

### Tasks & notes — `batch/task`
- **Create/Update/Delete** all go through `POST batch/task` with a body of
  `{"add": [...], "update": [...], "delete": [{"taskId","projectId"}]}`.
  - Create → put the full task object in `add`.
  - Update → put the full modified object (keep its `id`, `etag`, `projectId`) in
    `update`. Re-send `isAllDay`/`dueDate`/`startDate`/`timeZone` to keep the
    all-day contract intact.
  - Delete → `{"taskId": id, "projectId": projectId}` in `delete`.
- **Complete** → set `status` to `2` and send via `update` (status 0 = open).
- **Read** → `GET batch/check/0`; tasks are in `syncTaskBean.update` (a list of
  task objects). Filter client-side by `projectId`, due date, etc.
- A **note** is just a task with `"kind": "NOTE"` and Markdown in `content`.
- Task object keys (subset that matters): `id, projectId, title, content, kind,
  priority, status, isAllDay, startDate, dueDate, timeZone, tags, etag`.

### Projects — `batch/project`
- `POST batch/project` with `{"add":[...], "update":[...], "delete":[projectId,...]}`.
  Note delete takes a **bare id list**, not objects.
- Create/update object keys: `id, name, color, groupId, kind, ...`.
- Read → `GET batch/check/0` → `projectProfiles`.

### Tags — `batch/tag` for create/update, but **DELETE is different**
- Create/rename → `POST batch/tag` with `{"add":[{"name","label","color?"}]}` /
  `{"update":[...]}`. Tags are keyed by a **lowercased `name`**; `label` is display.
- **Delete → `DELETE tag?name=<urlencoded-name>`.** ⚠️ `batch/tag` with a `delete`
  list silently does nothing (returns empty `id2error` but the tag survives) — this
  was verified the hard way. Use the `DELETE tag` endpoint.
- Apply/remove a tag on a task → set the task's `tags` list and send via
  `batch/task` `update`.
- Read → `GET batch/check/0` → `tags`.

## Remaining methods to implement (Part B)

- **Tasks:** `get_task`, `list_tasks` (by project; due-today / overdue), `update_task`,
  `complete_task`, `delete_task`.
- **Projects:** `get_project`, `list_projects`, `update_project`, `delete_project`.
- **Tags:** `list_tags`, `rename_tag`, `delete_tag`, `add_tag_to_task`,
  `remove_tag_from_task`.
- **Notes:** `get_note`, `list_notes`, `update_note`, `delete_note` (task methods
  specialized to `kind == "NOTE"`).
