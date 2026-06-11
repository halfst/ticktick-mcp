# Slice 3 — MCP server / tool layer

**Owner:** Claude (tool contracts + reference tools) → Codex (repetitive fill)
**Depends on:** Slice 2 (client methods), Slice 0 (`DESIGN.md`)
**Why split:** Tool naming, argument design, and the date/all-day surface are decisions
that affect everyone who uses the server — Claude owns those. Once the pattern is set, the
remaining mechanical tool definitions are a clean Codex fill.

## Context

Expose the Slice 2 client through FastMCP tools — the public interface of the server. The
tool layer is thin: validate/shape inputs, call a typed client method, return a clean
result. **The tool layer never touches a raw endpoint or payload** (DESIGN.md law); it
only calls client methods.

The single most important UX decision here is the **date input contract**, because the
broken all-day behavior is what motivated the whole project. Tools that accept a due date
must let the caller express "this date, no time" naturally, and that must flow into the
all-day path from Slice 2. A bare date in must never come back out as midnight.

## Part A — Claude: tool contracts + reference tools

1. **Write the tool contract doc** (`TOOLS.md`): for every v1 tool, its name, arguments
   (names, types, which are optional), what it returns, and error behavior. Decide naming
   conventions once (e.g. verb_noun) and the **date argument convention** — how a caller
   passes a date-only due date vs. a timed one. This doc is the spec Codex fills against.

2. **Implement a few reference tools** spanning the families so the pattern is concrete:
   - `create_task` — including the date argument handling that routes a date-only value
     into the Slice 2 all-day path. This is the headline tool; get its argument design and
     docstring right.
   - `create_project`.
   - `create_note` — Markdown content in, note created.
   - one read tool (e.g. `list_tasks`).

   Each reference tool shows: FastMCP tool definition, input validation, the client call,
   and a clean typed/serializable return. Docstrings must be good — they are what the
   MCP host shows the model.

## Part B — Codex: fill remaining tools against `TOOLS.md`

Implement the rest to match the reference tools exactly:

- **Tasks:** get/list variants, update, delete, complete. (Date args follow the reference
  `create_task` convention; the all-day routing is already solved — reuse it.)
- **Projects:** list, update, delete.
- **Tags:** list, create, rename, delete, apply/remove on task.
- **Notes:** list, update, delete.

> Codex note: every tool is a thin wrapper over an existing Slice 2 client method. Do not
> add logic beyond input shaping and result serialization. Do not bypass the client. Match
> the reference tools' structure and docstring style.

## Acceptance criteria — done when

- The server starts and registers every v1 tool; an MCP host can list and call them.
- **Date contract holds end to end:** calling `create_task` with a date and no time yields
  an all-day task that reads back with no clock time, through the tool layer. A timed
  create stays timed. This is the acceptance test that this whole project succeeded.
- `create_note` with Markdown produces a formatted note in TickTick.
- Project and tag tools work through to the account.
- No tool references a raw endpoint or payload; everything goes via Slice 2 client methods.
- `TOOLS.md` documents every tool and matches the implemented behavior.
