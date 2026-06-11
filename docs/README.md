# ticktick-mcp — Build Plan

This folder holds the implementation plan for `ticktick-mcp`, an **unofficial** MCP
server for TickTick built against the reverse-engineered v2 web API. The work is sliced
into self-contained task briefs so each can be handed to an AI coding agent (Claude Code
or Codex) and executed against a fixed contract.

## Why the v2 (unofficial) API

The official TickTick Open API is OAuth-based and stable, but its write surface is too
limited for this project — notably it cannot do full project CRUD, has awkward all-day
date handling, and exposes little of the note/tag model. The v2 web API (the one the
first-party web client uses, as reverse-engineered by projects like `ticktick-py`) gives
full control at the cost of fragility: it authenticates with username/password and can
change without notice. This project accepts that tradeoff and isolates the risk in a
single client layer.

## Slice map and ownership

The slices have a strict dependency spine: **0 → 1 → 2 → 3 → 4**. Slices 2 and 3 each
have an internal seam where Claude establishes a reference pattern and Codex fills in the
repetitive remainder against a spec.

| Slice | Title | Owner | Depends on |
|-------|-------|-------|------------|
| 0 | Repo scaffold + design doc | Claude Code | — |
| 1 | v2 client: auth + transport | Claude Code | 0 |
| 2 | Client endpoint methods | Claude (pattern) → Codex (fill) | 1 |
| 3 | MCP server / tool layer | Claude (pattern) → Codex (fill) | 2 |
| 4 | Docker + compose + README finalize | Codex (infra) / Claude (prose) | 3 |

## How to use these briefs

Each `slice-N-*.md` is standalone: it states its context, the exact interface/contract it
must satisfy, and explicit acceptance criteria ("done when…"). Hand the whole file to the
named tool. Where a slice depends on an earlier one, it references the artifact (file,
class, or contract) the earlier slice produced rather than restating it.

## Hard rules that apply to every slice

- **Never commit secrets.** Credentials come from environment variables only. The session
  token cache is written to a gitignored path. No real token, password, or cookie ever
  lands in the repo.
- **The all-day date contract is the reason this project exists.** Get it right (see
  Slice 0 `DESIGN.md` and Slice 2). A task with a date but no time must round-trip as
  all-day, not as midnight.
- **Isolate v2 fragility.** All endpoint URLs and payload shapes live in the client layer
  only. The MCP tool layer never knows a raw endpoint.
- **Honest framing.** The README and package metadata state plainly that this is
  unofficial, uses the v2 API, may break, and is not affiliated with TickTick/Appest.
