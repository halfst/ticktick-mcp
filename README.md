# ticktick-mcp

A complete, **unofficial** [Model Context Protocol](https://modelcontextprotocol.io)
(MCP) server for [TickTick](https://ticktick.com). It gives an MCP host (Claude, or
any MCP-capable agent) full control over your TickTick tasks, projects, tags, and
Markdown notes — and it's built to run as more than a toy:

- **Full CRUD**, not a read-only wrapper — 22 tools spanning tasks, projects,
  tags, and notes.
- **Two transports from one image** — a local **stdio** server your host spawns,
  or a long-running **HTTP** service you deploy.
- **Pluggable, secure-by-default caller auth** — `none` / shared `token` /
  `jwt` (OAuth via your IdP). The HTTP transport **refuses to start unauthenticated**.
- **Correctness under fire** — the fragile reverse-engineered API is isolated in
  one client layer, behind typed methods and tests run against a real account.
- **Secrets stay out of the code, image, and git** — credentials live only in the
  environment, redacted from logs and reprs.

> ### ⚠️ Read this first
>
> - **Unofficial and unsupported.** This project is **not affiliated with,
>   endorsed by, or sponsored by TickTick or Appest Inc.** "TickTick" is used only
>   to name the service it talks to.
> - **It uses the reverse-engineered v2 *web* API** — the same private API the
>   TickTick web client uses — **not** the official Open API. That API is
>   undocumented and can **change or break without notice.** When it breaks, this
>   project breaks.
> - **It logs in with your account credentials** (or a session token you provide).
>   You are responsible for your account and for complying with TickTick's Terms
>   of Service. Use at your own risk.
>
> Why the v2 API at all? The official Open API can't do full project CRUD, has
> awkward all-day date handling, and exposes little of the note/tag model. The v2
> API gives full control — at the cost of fragility, which this project isolates
> in a single client layer.

## Tool surface

- **Tasks** — create, read, list (by project, due-today, overdue, completed),
  update, complete, delete.
- **Projects** — create, read, list, update, delete.
- **Tags** — list, create, rename, delete, and add/remove on a task.
- **Markdown notes** — create, read, list, update, delete (notes are note-kind
  items whose body is Markdown).

Out of scope: filters / smart lists, habits, focus / pomodoro, attachments.

### Dates that stay correct

A standout of the date handling: a task with a **date but no time** is an
**all-day** task, and it round-trips as all-day — **never silently shifted to
midnight** or to the day before/after in another timezone. If you've hit the
"due June 15" → "shows as June 14, 5:00 PM" bug in other TickTick tooling, that
class of bug is exactly what this avoids (covered by tests against a real account).

- Pass a date → `2026-06-15` → all-day task.
- Pass a date and time → `2026-06-15T09:30` → timed task.

## Setup

### 1. Credentials

Copy the example env file and fill in **one** auth mode:

```bash
cp .env.example .env
```

- **Session token (recommended — and required if your account has 2FA).** Log
  into TickTick in a browser, complete any 2FA prompt, then copy the value of the
  `t` cookie (DevTools → Application/Storage → Cookies → `ticktick.com`) into
  `TICKTICK_SESSION_TOKEN`. No password is stored, and it works with 2FA. The
  token can't be auto-refreshed, so when it eventually expires you paste a fresh
  one.
- **Username + password.** Set `TICKTICK_USERNAME` and `TICKTICK_PASSWORD`. This
  only works on accounts **without** 2FA (the v2 sign-in has no second-factor
  step).

`.env` is gitignored and is never baked into the image.

### 2. Run with Docker Compose

```bash
docker compose up -d
```

This builds the image and starts the server over HTTP on port `8000`, persisting
the session-token cache in a named volume (`ticktick-token`) so it survives
restarts. Check it's up:

```bash
docker compose logs -f ticktick-mcp
```

### 3. Wire it into your MCP host

The container serves the **streamable HTTP** transport at:

```
http://<docker-host>:8000/mcp/
```

Point your MCP host at that URL. For example, in Claude Code:

```bash
claude mcp add --transport http ticktick http://localhost:8000/mcp/
```

#### Running without Docker (stdio)

You can also run it as a local stdio server that your MCP host spawns directly:

```bash
pip install .
# with your .env values exported into the environment:
ticktick-mcp           # TICKTICK_MCP_TRANSPORT defaults to stdio
```

Verify auth at any time:

```bash
python -m ticktick_mcp.client      # prints "Authenticated OK ..." or a clear error
```

## Auth caveat

TickTick may challenge sign-ins from an unfamiliar IP with a **captcha / device
verification**. The server can't solve that. If a username/password login fails
with a challenge error, log into the TickTick web client once from the same
network (or just use the session-token method above), then retry. With 2FA
enabled, the session-token method is the only one that works.

## Caller authentication

The server can authenticate the *clients that connect to it* (separate from how it
logs in to TickTick). Pick a mode with `TICKTICK_MCP_AUTH`. On the **http**
transport a mode is **required** — the server refuses to start if it is unset.
**stdio** defaults to `none`.

| Mode    | When to use                                  | Required vars |
|---------|----------------------------------------------|---------------|
| `none`  | Local stdio, or http behind your own auth    | — |
| `token` | A personal remote server / single connector  | `TICKTICK_MCP_BEARER_TOKEN` |
| `jwt`   | Real per-user OAuth via your IdP             | `TICKTICK_MCP_JWT_JWKS_URI` *or* `TICKTICK_MCP_JWT_PUBLIC_KEY`, `TICKTICK_MCP_JWT_ISSUER`, `TICKTICK_MCP_JWT_AUDIENCE`, `TICKTICK_MCP_AUTH_SERVER`, `TICKTICK_MCP_BASE_URL` |

### token mode

Set a long random secret:

```bash
TICKTICK_MCP_AUTH=token
TICKTICK_MCP_BEARER_TOKEN=$(openssl rand -hex 32)
```

In a client (e.g. a Claude custom connector), add a custom header
`Authorization: Bearer <token>`. Requests without it get `401`.

### jwt mode

The server validates IdP-issued JWTs and serves
`/.well-known/oauth-protected-resource`, which points MCP clients at your
authorization server so they can run the OAuth flow. Supply your IdP's values:

```bash
TICKTICK_MCP_AUTH=jwt
TICKTICK_MCP_JWT_JWKS_URI=https://idp.example/application/o/ticktick/jwks/
TICKTICK_MCP_JWT_ISSUER=https://idp.example/application/o/ticktick/
TICKTICK_MCP_JWT_AUDIENCE=ticktick-mcp
TICKTICK_MCP_AUTH_SERVER=https://idp.example/application/o/ticktick/
TICKTICK_MCP_BASE_URL=https://your-public-host
```

> Note: when fronting this with a reverse proxy, do **not** also apply a
> browser-cookie forward-auth layer — it blocks the unauthenticated discovery
> calls an MCP client must make. Let JWT-bearing requests reach the app. Some MCP
> clients require OAuth Dynamic Client Registration (DCR); if your IdP lacks DCR,
> pre-register a client and use its Client ID in the client.

## Security

- Credentials live **only** in the environment (via `.env`), never in code, the
  image, or git. `.env` and the token cache are gitignored; `.dockerignore` keeps
  them out of the build context.
- The session-token cache is written to a local/volume path (`TICKTICK_TOKEN_CACHE`),
  not into the repo.
- Secrets are redacted from the config's representation and never logged.
- The container runs as a non-root user.

## Configuration reference

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `TICKTICK_SESSION_TOKEN` | one auth mode | — | `t` cookie from a logged-in browser (2FA-friendly). |
| `TICKTICK_USERNAME` / `TICKTICK_PASSWORD` | one auth mode | — | Account login (no-2FA accounts only). |
| `TICKTICK_TOKEN_CACHE` | no | `${XDG_CACHE_HOME:-~/.cache}/ticktick-mcp/session.json` | Where the session token is cached. |
| `TICKTICK_TIMEZONE` | no | `UTC` | Default IANA zone for *timed* tasks (all-day ignores it). |
| `TICKTICK_MCP_TRANSPORT` | no | `stdio` | `stdio` or `http`. |
| `TICKTICK_MCP_HOST` / `TICKTICK_MCP_PORT` | no | `0.0.0.0` / `8000` | HTTP bind address (http transport only). |
| `TICKTICK_MCP_AUTH` | http: yes | none (stdio) | Caller-auth mode: `none`/`token`/`jwt`. http refuses to start if unset. See [Caller authentication](#caller-authentication). |
| `TICKTICK_MCP_BEARER_TOKEN` | token mode | — | Shared bearer token clients send as `Authorization: Bearer`. |
| `TICKTICK_MCP_JWT_JWKS_URI` / `TICKTICK_MCP_JWT_PUBLIC_KEY` | jwt mode (exactly one) | — | Key source for validating IdP-issued JWTs. |
| `TICKTICK_MCP_JWT_ISSUER` / `TICKTICK_MCP_JWT_AUDIENCE` | jwt mode | — | Expected JWT `iss` and `aud`. |
| `TICKTICK_MCP_AUTH_SERVER` | jwt mode | — | IdP authorization-server URL advertised via OAuth discovery. |
| `TICKTICK_MCP_BASE_URL` | jwt mode | — | This server's public base URL (for resource metadata). |

## How it's built

Two layers, strictly separated (see [`DESIGN.md`](DESIGN.md)):

- `ticktick_mcp/client/` — the only code that knows v2 endpoints and payloads.
  All fragility (and the all-day date contract) is isolated here.
- `ticktick_mcp/server/` — thin FastMCP tools that call typed client methods and
  return clean results.

See [`TOOLS.md`](TOOLS.md) for the tool reference and
[`CLIENT_METHODS.md`](CLIENT_METHODS.md) for the client method reference.

## Contributing

Issues and PRs welcome. A few ground rules:

- Never commit a real credential or token.
- Keep endpoint URLs and payload shapes inside `ticktick_mcp/client/` — the server
  layer must not know them.
- The all-day date contract is load-bearing; if you touch dates, keep its tests
  green (and add live coverage where you can).

Run the tests:

```bash
pip install -e ".[dev]"
pytest                 # unit tests; the live test self-skips without credentials
```

## License

[Apache-2.0](LICENSE). See [`NOTICE`](NOTICE) for attribution and the unofficial /
not-affiliated disclaimer.
