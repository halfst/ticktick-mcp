# Slice 1 — v2 client: auth + transport

**Owner:** Claude Code
**Depends on:** Slice 0 (`DESIGN.md`, `config.py`, `client/` package)
**Why Claude:** Highest-risk slice. Reverse-engineered auth is where this kind of project
breaks, and getting the transport/token model right is a judgment call, not a fill-in.

## Context

This slice builds the foundation of the v2 client: logging in with username/password,
caching the session token, and a base request wrapper every endpoint method (Slice 2) will
use. **Do not implement feature endpoints here** — only auth + transport + the smallest
possible "is this working" call.

**Ground in real source, not memory.** Before writing the login flow, read the current
`ticktick-py` implementation (its auth/session module) to confirm the login endpoint, the
request headers, the payload shape, and how the session token is returned and carried on
subsequent requests. The v2 API is undocumented and can drift; the library source is the
closest thing to ground truth. Note in a comment where the behavior was confirmed from.

## Deliverables

1. **A session/auth module** in `client/` that:
   - Reads credentials from the Slice 0 config (env-sourced; never hardcoded).
   - Performs the v2 login and obtains a session token.
   - **Caches the token to the configured disk path** and reuses it on subsequent
     process starts, so we are not logging in on every invocation.
   - Detects an expired/invalid session (e.g. a 401) and transparently re-authenticates
     once, then retries the request.

2. **A base request wrapper** (the transport) that:
   - Attaches the session token / required headers to every call.
   - Centralizes base URL, timeouts, and JSON handling.
   - Surfaces errors per the `DESIGN.md` Error/Result convention — distinguishing
     auth failures, HTTP errors, and payload errors.
   - Is the single chokepoint Slice 2's endpoint methods build on.

3. **One minimal authenticated read** (e.g. fetch the user's projects) used purely to
   prove end-to-end auth works. This can be a thin private method; the full project/task
   methods come in Slice 2.

4. **Handle the login-friction reality.** TickTick may challenge logins from unfamiliar
   IPs (captcha / device verification). The code can't solve a captcha, but it must fail
   with a clear, actionable error message telling the user what happened rather than a
   bare stack trace.

## Explicitly NOT in this slice

- No task/project/tag/note CRUD methods (those are Slice 2).
- No MCP tool definitions (Slice 3).
- No date/all-day logic beyond what the minimal read needs (the all-day contract is
  implemented in Slice 2 against `DESIGN.md`).

## Acceptance criteria — done when

- With valid credentials in the environment, the module logs in, caches a token to the
  configured path, and a second run **reuses the cached token without re-logging-in**.
- Forcing an invalid/expired token triggers exactly one transparent re-auth + retry.
- The minimal authenticated read returns real data from the account.
- A login challenge / bad-credential case produces a clear, human-readable error — not an
  unhandled exception.
- The token cache path is gitignored (from Slice 0); no credential or token is written
  anywhere inside the repo tree.
- A comment records which `ticktick-py` source (and roughly what version/date) the auth
  flow was confirmed against.
