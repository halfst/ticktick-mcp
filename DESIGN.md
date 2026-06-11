# DESIGN.md — ticktick-mcp

This document fixes the contracts every later slice implements against. Where a
slice brief and this document disagree, **this document wins** for contracts; if
this document is wrong about real v2 behavior, fix it here first, then implement.

`ticktick-mcp` is an **unofficial** MCP server for TickTick built on the
reverse-engineered **v2 web API** — the same API the first-party web client uses,
as surfaced by projects like [`ticktick-py`](https://github.com/lazeroffmichael/ticktick-py).
It is not affiliated with, endorsed by, or sponsored by TickTick / Appest Inc.

---

## 1. Layering rule (LAW)

There are exactly two layers, and the boundary is absolute.

```
ticktick_mcp/
  client/   ← knows TickTick. Owns every endpoint URL and raw payload shape.
  server/   ← knows MCP. Calls typed client methods. Never sees a URL or payload.
```

- **Every v2 endpoint path, query parameter, header, and raw JSON payload shape
  lives ONLY in `client/`.** No string that looks like an endpoint (`/api/v2/...`,
  `batch/task`) and no raw TickTick field name (`isAllDay`, `dueDate`, `sortOrder`)
  may appear outside `client/`.
- The `server/` (tool) layer calls **typed client methods** that take and return
  typed models. It does input shaping and result serialization only — no business
  logic, no HTTP, no awareness of TickTick's wire format.
- This isolates v2 fragility: when the undocumented API drifts, the blast radius is
  one package. The tool surface and its tests should not move.

A change is a layering violation if deleting `client/` would leave a TickTick
endpoint or field name referenced anywhere else. Treat that as a build failure.

---

## 2. Auth model

The v2 API authenticates with **username + password**, not OAuth. Because that
flow has **no second-factor step**, accounts with 2FA enabled cannot use it; for
those we accept a session token directly. There are therefore two modes:

**Mode A — session-token override (`TICKTICK_SESSION_TOKEN`).** The user logs into
the TickTick web client (completing 2FA there), copies the `t` session cookie, and
supplies it. The client uses it as the token verbatim and **never calls `signin`**.
No password need be set at all. The trade-off: this token **cannot be
auto-refreshed** (refreshing would require the 2FA prompt again), so on a `401` the
client does **not** retry — it raises a clear `AuthError` telling the user to paste
a fresh token. This is the recommended/required path for 2FA accounts.

**Mode B — username/password login.** Used when no session token is given (no-2FA
accounts). The client signs in itself and can transparently re-auth on expiry (the
flow below). The session token wins if both modes are configured.

- Credentials come from the environment only (`TICKTICK_USERNAME`,
  `TICKTICK_PASSWORD`, or `TICKTICK_SESSION_TOKEN`) via `config.py`. They are never
  hardcoded, logged, or committed.
- On first use the client **logs in once** and receives a **session token**.
- The token is **cached to disk** at `Config.token_cache_path`
  (`TICKTICK_TOKEN_CACHE`, default `${XDG_CACHE_HOME:-~/.cache}/ticktick-mcp/session.json`).
  The path is gitignored and, under Docker, lives on a persisted volume.
- On a subsequent process start the client **reuses the cached token** instead of
  logging in again.
- If a request comes back **`401` / unauthorized**, the client treats the cached
  token as expired, **re-authenticates exactly once**, replaces the cache, and
  **retries the original request once**. A second failure surfaces as an auth error
  (no infinite retry loop).
- **Login friction is expected.** TickTick may challenge logins from unfamiliar IPs
  with a captcha / device verification. The client cannot solve that; it must fail
  with a clear, human-readable `AuthError` explaining what happened and what to do
  (log in via the web client from this IP, then retry) — never a bare stack trace.

The concrete login endpoint, headers, and payload are confirmed against current
`ticktick-py` source in Slice 1 and documented there in a code comment.

---

## 3. The all-day date contract (CRITICAL)

This is the whole reason the project exists. Other tooling stores a date-only due
date as a clock time (local midnight, then converted to UTC), so a task due
"June 15" reads back as "June 14, 5:00 PM" for a viewer in another timezone. We do
not do that. **A date with no time is all-day, stored as all-day, and round-trips
as all-day.**

### v2 fields involved

A v2 task carries these date-related fields (camelCase, as on the wire):

| Field      | Type   | Meaning                                                        |
|------------|--------|---------------------------------------------------------------|
| `isAllDay` | bool   | `true` ⇒ the task is a whole-day task; the clock is meaningless. |
| `dueDate`  | string | ISO 8601 with a UTC offset, e.g. `2026-06-15T00:00:00.000+0000`. |
| `startDate`| string | Same format as `dueDate`; for a single-day task equals `dueDate`. |
| `timeZone` | string | IANA zone, e.g. `America/Los_Angeles`. The user's zone.        |

Wire date format (both directions): `YYYY-MM-DDTHH:mm:ss.SSS+0000` — note the
millisecond `.SSS` and the **basic** offset `+0000` (no colon). The server returns
this exact shape; we send this exact shape.

### Internal representation

The client's typed model represents a due value as one of two cases — never an
ambiguous `datetime`:

- **`AllDayDate(date)`** — a calendar date with no time component.
- **`Timed(datetime, tz)`** — an instant with an explicit timezone.

> **Empirically confirmed (2026-06, live v2 account).** The server stores what we
> send for `dueDate`/`isAllDay`/`timeZone` **verbatim** — it does not re-normalize.
> Crucially, all-day tasks created by the first-party apps store `dueDate` as
> **local midnight converted to UTC**, with `timeZone` = the device zone. Example
> from a real `America/Chicago` account: an all-day task on **July 1** is stored as
> `dueDate = 2026-07-01T05:00:00.000+0000` (05:00Z = 00:00 Chicago, CDT = UTC-5),
> `timeZone = America/Chicago`. This is why the read side **must** convert through
> the stored `timeZone`.

### MCP input → client payload (writing)

- **All-day** (caller gave a date, no time): encode the date at **UTC midnight**.
  - `isAllDay = true`
  - `dueDate = startDate = "<YYYY-MM-DD>T00:00:00.000+0000"`
  - `timeZone = "UTC"`

  Using UTC (rather than localizing into some `TZ`) is deliberate: the date is then
  literally present in the string, and it is **DST-proof** — midnight in some zones
  on some dates is ambiguous or non-existent, but UTC midnight never is. Because
  `isAllDay` short-circuits clock interpretation in the TickTick UI, a UTC-encoded
  all-day task displays on the same calendar date as a device-zone-encoded one.

- **Timed** (caller gave a date *and* a time) with timezone `TZ` (caller-supplied,
  else the client default `TICKTICK_TIMEZONE`, else UTC):
  - `isAllDay = false`
  - Make the `datetime` timezone-aware in `TZ`, convert to UTC, format as `...+0000`.
  - `timeZone = TZ`.

### API response → MCP output (reading)

- If `isAllDay == true`: parse the `dueDate` instant, **convert it into the task's
  stored `timeZone`, then take the calendar date.** Return a **date-only** value; no
  clock. This is the load-bearing step: our own tasks store `...T00:00:00+0000`/`UTC`
  (date falls straight out), but app-created tasks store local-midnight-UTC — e.g. a
  Tokyo (UTC+9) all-day July 1 is `2026-06-30T15:00:00+0000`, whose **UTC** date is
  June 30. Only converting through `timeZone` recovers July 1. Taking the raw UTC
  date is the off-by-one bug for zones east of UTC.
- If `isAllDay == false`: parse the full instant and present it in `timeZone` (an
  offset-aware datetime), clock time intact.

### The invariant (headline regression test)

> Create a task with date `D` and no time → on the server `isAllDay` is `true` and
> the stored date component is `D` → reading it back yields date-only `D` with no
> clock time, **for any viewer timezone**. Create with date `D` + time `T` → it is
> timed and reads back as `D`/`T`.

Round-trip stability for all-day is non-negotiable: `read(create(D)) == D`.

### Multi-day note

TickTick treats an all-day range's `dueDate` as **exclusive** (one day past the
last visible day). Single-day tasks (the v1 default) set `startDate == dueDate` and
do not hit this. If/when multi-day ranges are added, the client adds one day to the
exclusive `dueDate` on write and subtracts it on read — and that adjustment lives in
the client date builder, nowhere else.

---

## 4. Error / Result conventions

**Client layer** signals failure with typed exceptions, not sentinel values or ad
hoc dicts. A small exception hierarchy rooted at `TickTickError`:

- `AuthError` — login failed, credentials rejected, or a login challenge
  (captcha/device) blocked sign-in. Message is human-actionable.
- `APIError` — the API returned a non-2xx HTTP status that is not auth-related.
  Carries the status code and any server-provided message (with secrets stripped).
- `PayloadError` — a 2xx response whose body did not match the expected shape
  (missing/renamed fields — the classic "v2 drifted" signal).

Client methods either **return a typed result model or raise** one of the above.
They never return `None`-on-error or leak an `httpx` exception type upward.

**Server (tool) layer** catches `TickTickError` and returns a clean, structured
error to the MCP host: a short human-readable message plus a stable error kind
(`auth`, `api`, `payload`). Tool docstrings state what a tool returns and that it
may report these errors. Stack traces and secrets never reach the host. Unexpected
(non-`TickTickError`) exceptions are caught at the tool boundary and reported as a
generic internal error without leaking internals.

---

## 5. v1 tool surface

**In scope for v1:**

- **Tasks** — full CRUD: create, get, list (by project; due-today / overdue),
  update, complete, delete. All honor the all-day contract.
- **Projects** — full CRUD: create, get, list, update, delete (via the v2 batch
  endpoint pattern).
- **Tags** — list, create, rename, delete, and apply/remove on a task.
- **Notes** — Markdown notes. A note is a task of the **note kind** whose `content`
  is Markdown. Create, get, list, update, delete (task methods specialized to the
  note kind).

**Explicitly OUT of scope for v1:**

- Filters / smart lists
- Habits
- Focus / pomodoro
- Attachments

(Tags **are** in v1. The four above are not.)

---

## 6. Configuration & secrets (supporting contract)

- All secrets come from env vars; `config.py` loads them into a typed, immutable
  `Config` and fails loudly (`ConfigError`) when a required var is missing.
- The `password` is redacted from `Config`'s `repr`; no code path logs a secret.
- The token cache path is gitignored; no token, password, or cookie is ever written
  inside the repo tree.

---

## Provenance

Endpoint paths, payload shapes, and the date-field behavior in this document are
grounded in the current `ticktick-py` source and the v2 task model (confirmed
2026-06; e.g. responses formatted `2021-05-06T21:30:00.000+0000`, fields
`isAllDay` / `dueDate` / `startDate` / `timeZone`). The v2 API is undocumented and
may drift; Slices 1–2 re-confirm specifics against source at implementation time and
record where each was verified.
