# Slice 2 — Client endpoint methods

**Owner:** Claude (reference pattern) → Codex (repetitive fill)
**Depends on:** Slice 1 (auth + transport wrapper), Slice 0 (`DESIGN.md`)
**Why split:** The first method of each kind is a design decision (shape, error handling,
the all-day contract). Once a reference exists, the remaining endpoint wrappers are
mechanical and well-suited to Codex against the table below.

## Context

Build the typed client methods that wrap v2 endpoints for the v1 surface: tasks, projects,
tags, and Markdown notes. All of these go through the Slice 1 transport. **No endpoint URL
or raw payload shape may leak outside `client/`** (DESIGN.md law).

As in Slice 1, **confirm endpoint paths and payload shapes against current `ticktick-py`
source** rather than memory, especially the batch endpoints and the project CRUD payloads
(those are the pickiest).

## Part A — Claude: establish the reference pattern

Implement ONE method from each family, fully, as the canonical example the rest copy:

- **One task create** — and this is where the **all-day date contract from `DESIGN.md`**
  gets implemented for real. A create with a date and no time must produce an all-day task
  (`isAllDay` true, correct date/timezone handling) that round-trips as all-day, NOT as
  midnight. A create with an explicit time stays timed. Bake this into the task payload
  builder so every other task method inherits it.
- **One project create** (note the batch-endpoint pattern + payload fussiness).
- **One tag operation.**
- **A note create** — a note is a task with the note kind whose `content` is Markdown.
  Confirm the field that distinguishes note-kind items and that `content` carries Markdown.

Each reference method must show: typed inputs (pydantic), payload construction, the
transport call, response parsing into a typed result, and DESIGN.md-conformant error
handling. Add a short `CLIENT_METHODS.md` (or docstring block) describing the pattern so
the Codex hand-off is unambiguous.

## Part B — Codex: fill the remaining methods against this table

Implement each remaining method to match the reference pattern exactly. Same input typing,
same error handling, same layering. Do not invent new conventions.

**Tasks:** get/list (by project, and due-today/overdue as needed), update, delete,
complete. Update/complete must preserve the all-day contract.
**Projects:** get/list, update, delete (all via the batch pattern from the reference).
**Tags:** list, create, rename, delete, plus applying/removing tags on a task.
**Notes:** get/list, update, delete (mostly task methods specialized to note kind +
Markdown `content`).

> Codex note: the all-day date handling and the batch-endpoint payload shape are ALREADY
> solved in Part A's reference methods. Reuse those builders verbatim. If a payload shape
> is unclear, copy the reference method's structure — do not guess a new shape.

## Acceptance criteria — done when

- Every v1-surface method exists and goes through the Slice 1 transport; no endpoint URL
  or raw payload appears outside `client/`.
- **All-day round-trip:** create a task with a date and no time → it is all-day on the
  server and reads back as all-day with no clock time. Create with a time → stays timed.
  (This is the regression the whole project exists to fix; treat it as the headline test.)
- A Markdown note created via the note method renders as a formatted note in TickTick.
- Project create/update/delete work via the batch endpoints.
- Tag create/rename/delete and apply/remove-on-task work.
- Methods are typed and parse responses into typed results; errors follow DESIGN.md.
