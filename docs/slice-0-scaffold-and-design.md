# Slice 0 — Repo scaffold + design doc

**Owner:** Claude Code
**Depends on:** nothing
**Why Claude:** This slice fixes the architecture every later slice references. Wrong
decisions here compound. Must be done with judgment, not filled in from a spec.

## Context

We are building `ticktick-mcp`, an unofficial MCP server for TickTick using the
reverse-engineered v2 web API (same approach as `ticktick-py`). Python, FastMCP, packaged
to run as a Docker Compose service alongside other self-hosted MCP servers. Public repo;
honest "unofficial / not affiliated" framing throughout.

This slice produces the skeleton and — most importantly — a `DESIGN.md` that nails down
the contracts the rest of the build depends on. No real feature code yet.

## Deliverables

1. **Project layout**, roughly:
   ```
   ticktick_mcp/
     __init__.py
     client/          # v2 API client (Slices 1–2 fill this)
       __init__.py
     server/          # MCP tool layer (Slice 3 fills this)
       __init__.py
     config.py        # env-var loading; NO secrets in code
   tests/
   docs/              # these briefs already live here
   pyproject.toml
   .gitignore
   .env.example
   README.md          # stub; finalized in Slice 4
   Dockerfile         # stub; filled in Slice 4
   compose.yaml       # stub; filled in Slice 4
   ```

2. **`pyproject.toml`** with deps: an MCP/FastMCP package, an HTTP client (`httpx`),
   `pydantic` for payload models. Pin nothing exotic. Target Python 3.11+.
   - **Declare the license** so package metadata matches the repo: `license = "Apache-2.0"`
     (SPDX expression) and the `License :: OSI Approved :: Apache Software License`
     classifier. (`LICENSE` and `NOTICE` already exist at the repo root.)

3. **`config.py`** — loads `TICKTICK_USERNAME`, `TICKTICK_PASSWORD`, and a token-cache
   path from the environment. Provides a typed config object. Raises a clear error if
   required vars are missing. Never logs secret values.

4. **`.env.example`** — documents the env vars with placeholder values. **`.gitignore`**
   — ignores `.env`, the token cache path, `__pycache__`, build artifacts, virtualenvs.

5. **`DESIGN.md`** — the keystone. Must specify:
   - **Layering rule:** endpoint URLs and payload shapes live ONLY in `client/`. The
     server layer calls typed client methods, never raw HTTP. State this as law.
   - **Auth model:** username/password from env → session token; token cached to disk at
     the configured path; cache reused across restarts; re-auth on expiry/401.
   - **The all-day date contract (CRITICAL).** Specify exactly how a date-only due date is
     represented end to end. The rule: a task given a date but no time is **all-day**;
     it must be stored and round-trip as all-day, never coerced to midnight-local or any
     clock time. Document the v2 fields involved (`isAllDay`, `dueDate`, and the timezone
     field) and the conversion both directions (MCP tool input → client payload, and API
     response → tool output). This contract is the whole reason the project exists; later
     slices implement against it verbatim.
   - **Error/Result conventions:** how client methods signal success/failure, how the
     server layer surfaces errors to the MCP host.
   - **v1 tool surface (agreed):** full task CRUD, full project CRUD, Markdown-note
     support (notes are tasks with note kind whose `content` is Markdown), and tags.
     Explicitly list as **out of scope for v1:** filters/smart-lists, habits,
     focus/pomodoro, attachments. (Tags ARE in v1.)

## Licensing note (already in place; keep consistent)

The repo is **Apache-2.0**. `LICENSE` (full Apache-2.0 text, copyright `2026 Ethan J Lewis`)
and `NOTICE` (attribution + "not affiliated with TickTick/Appest" disclaimer) already
exist at the repo root — do not overwrite them. This slice only needs to make the
`pyproject.toml` metadata agree (see Deliverable 2). The SPDX identifier to use everywhere
is `Apache-2.0`; Slice 4's README states it.

Per-source-file license headers (the short "Licensed under the Apache License…"
boilerplate) are **optional** for a project this size — skip them in this slice. If wanted
later, Codex can stamp them across files as a mechanical pass.

## Acceptance criteria — done when

- The tree above exists; package imports cleanly (`python -c "import ticktick_mcp"`).
- `config.py` reads env vars and fails loudly when they're absent; no secret ever appears
  in a log line or in the repo.
- `.gitignore` covers `.env` and the token cache path; `.env.example` documents every var.
- `pyproject.toml` declares `license = "Apache-2.0"` and the OSI Apache classifier,
  matching the existing `LICENSE`/`NOTICE` files.
- `DESIGN.md` exists and pins down all six items above, with the **all-day date contract
  written out unambiguously enough that a later slice can implement it without rethinking
  the design.**
- Nothing in the repo contains a real credential or token.
