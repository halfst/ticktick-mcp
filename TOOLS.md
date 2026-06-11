# TOOLS.md — MCP tool contract (Slice 3)

The public tool surface of `ticktick-mcp`. **Part A** (Claude) fixes these
contracts and implements the reference tools; **Part B** (Codex) implements the
rest to match. Every tool is a thin wrapper over one `TickTickClient` method — no
tool touches a raw endpoint or payload (DESIGN.md §1).

## Conventions (decide once, apply everywhere)

- **Naming:** `verb_noun`, snake_case (`create_task`, `list_projects`,
  `complete_task`, `add_tag_to_task`).
- **Date argument (`due`) — the all-day contract surface (DESIGN.md §3):**
  - `"YYYY-MM-DD"` (bare date) → an **all-day** task. It must round-trip as a date;
    it is never shifted to a clock time.
  - `"YYYY-MM-DDTHH:MM"` (optionally `:SS` and/or a `+0000` offset) → a **timed**
    task.
  - Parsing lives in `handlers.parse_due`; tools pass the result straight to the
    client. Reuse it — do not re-parse dates per tool.
  - `timezone` (IANA, e.g. `"America/Chicago"`) applies to **timed** dates only;
    all-day ignores it. Defaults to the server's configured timezone.
- **Return shape:** every tool returns a JSON object.
  - Success: the entity (`task`/`project`/`tag`) as an object, or a wrapper like
    `{"tasks": [...]}` for lists.
  - Failure: `{"error": {"kind", "message"}}` where `kind` ∈
    `input | auth | api | payload | internal`. Use the `@_safe` wrapper in
    `handlers.py`; never raise out of a handler, never leak internals.
- **Object fields** (from the client models): a task has `id, project_id, title,
  content, kind, priority, status, is_all_day, due, timezone, tags, etag`. `due`
  is a date string for all-day, a datetime string for timed, or null.

## Reference tools (Part A — implemented)

| Tool | Args | Returns |
|------|------|---------|
| `create_task` | `title`, `due?`, `project_id?`, `content?`, `priority=0`, `timezone?` | the created task |
| `create_note` | `title`, `content`, `project_id?` | the created note (`kind:"NOTE"`) |
| `create_project` | `name`, `color?` | the created project |
| `list_tasks` | `project_id?`, `due_today=false`, `overdue=false`, `include_completed=false` | `{"tasks":[...]}` |

## Tools to implement (Part B — Codex)

Each is a thin wrapper over the like-named `TickTickClient` method (Slice 2). Match
the reference tools' structure, docstrings, and error handling. The all-day routing
is already solved by `parse_due` — reuse it for any tool taking a `due`.

**Tasks**
- `get_task(task_id)` → task
- `update_task(task_id, title?, content?, due?, clear_due=false, priority?, project_id?, tags?, timezone?)` → task
  (a `due` follows the same date convention; `clear_due` removes the date)
- `complete_task(task_id)` → task
- `delete_task(task_id, project_id?)` → the deleted task

**Projects**
- `get_project(project_id)` → project
- `list_projects(include_closed=false)` → `{"projects":[...]}`
- `update_project(project_id, name?, color?)` → project
- `delete_project(project_id)` → the deleted project

**Tags**
- `list_tags()` → `{"tags":[...]}`
- `create_tag(label, color?)` → tag
- `rename_tag(name, new_label, color?)` → tag
- `delete_tag(name)` → the deleted tag
- `add_tag_to_task(task_id, tag_name)` → task
- `remove_tag_from_task(task_id, tag_name)` → task

**Notes**
- `get_note(note_id)` → note
- `list_notes(project_id?, include_completed=false)` → `{"notes":[...]}`
- `update_note(note_id, title?, content?, project_id?)` → note
- `delete_note(note_id)` → the deleted note

> Codex note: register each tool in `app.py` with a good docstring (the host shows
> it to the model) and delegate to a `@_safe` handler in `handlers.py`. Do not add
> logic beyond input shaping and result serialization; do not bypass the client.
