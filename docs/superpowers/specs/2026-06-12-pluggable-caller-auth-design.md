# v0.1.1 — Pluggable caller authentication

**Date:** 2026-06-12
**Status:** Approved (design)
**Target:** `ticktick-mcp` v0.1.1 (app repo only)

## Problem

The server (`ticktick_mcp/server/app.py`) authenticates *to TickTick* via env
credentials but does nothing to authenticate *callers*. `FastMCP(...)` is built
with no `auth=`. Deploying it remotely (e.g. `https://ticktick.half.st/mcp/`)
therefore has no app-level protection, and Claude's MCP connector — which expects
either a bearer token or an OAuth discovery flow — cannot connect.

Delegating caller-auth to a reverse-proxy forward-auth layer (Authentik browser
cookies) does **not** satisfy an MCP client, because forward-auth (browser
cookies) ≠ MCP client auth (OAuth bearer tokens).

## Goal

Add a **pluggable, secure-by-default caller-auth layer to the app** so anyone
deploying this open-source server can pick the mode that fits, and whatever they
pick is secure. Three modes, one env switch.

## Environment

- Installed runtime is **`fastmcp` 3.4.2** (not 2.x). Relevant verified API:
  - `StaticTokenVerifier(tokens: dict)` and `JWTVerifier(...)` live in
    `fastmcp.server.auth.providers.jwt`.
  - `RemoteAuthProvider(token_verifier, authorization_servers, base_url, ...)`
    lives in `fastmcp.server.auth.auth`. It serves
    `/.well-known/oauth-protected-resource` advertising the authorization
    server(s), so an MCP client can run OAuth discovery.
  - `FastMCP(...)` accepts an `auth=` constructor arg, and `mcp.auth` is a
    settable attribute after construction. `mcp.run(...)` does **not** take
    `auth`.

## Decisions (from brainstorming)

1. **Breadth:** pluggable `none / token / jwt` via a single env switch. (Not
   "token only"; not the full ~18-provider IdP matrix.)
2. **Default mode:** `none` for stdio (local process, safe); **require an
   explicit mode for http** (refuse to start otherwise).
3. **Owner's own deployment** (`ticktick.half.st`): **JWT via Authentik** — out
   of scope for this spec's code, handled as a follow-on deploy task.

## Design

### 1. New module `ticktick_mcp/server/auth.py`

Mirrors the existing `config.py` style: env-sourced, immutable intent, secrets
never placed in `repr`, log lines, or exception messages.

Public surface:

```python
class AuthConfigError(RuntimeError):
    """Missing/invalid caller-auth configuration. Names the bad var,
    never echoes a secret value."""

def build_auth(transport: str, env: Mapping[str, str] | None = None) -> AuthProvider | None:
    ...
```

Driven by **`TICKTICK_MCP_AUTH`** ∈ `{none, token, jwt}` (case-insensitive,
whitespace-stripped):

- **`none`** → return `None`. No caller auth.
- **`token`** → read `TICKTICK_MCP_BEARER_TOKEN` (required, non-empty after
  strip; else `AuthConfigError`). Return
  `StaticTokenVerifier({token: {"client_id": "ticktick-mcp", "scopes": []}})`.
- **`jwt`** → read:
  - `TICKTICK_MCP_JWT_JWKS_URI` **or** `TICKTICK_MCP_JWT_PUBLIC_KEY` (exactly one
    required; if both/neither → `AuthConfigError`),
  - `TICKTICK_MCP_JWT_ISSUER` (required),
  - `TICKTICK_MCP_JWT_AUDIENCE` (required),
  - `TICKTICK_MCP_AUTH_SERVER` (required — IdP authorization-server URL advertised
    to clients),
  - `TICKTICK_MCP_BASE_URL` (required — this server's public base URL, e.g.
    `https://ticktick.half.st`).

  Build `JWTVerifier(jwks_uri=… | public_key=…, issuer=…, audience=…)`, wrap in
  `RemoteAuthProvider(token_verifier=verifier, authorization_servers=[auth_server],
  base_url=base_url)`, and return it.

- Any other value of `TICKTICK_MCP_AUTH` → `AuthConfigError` listing the valid
  modes.

### 2. Default-mode / secure-by-default logic (inside `build_auth`)

When `TICKTICK_MCP_AUTH` is **unset/empty**:

- transport `stdio` → behave as `none` (return `None`).
- transport `http` (or `streamable-http`) → raise `AuthConfigError` refusing to
  start, message listing the three modes.

Escape hatch: an explicit `TICKTICK_MCP_AUTH=none` starts fine on http — the
deployer made a deliberate choice. **No separate opt-out flag** (e.g.
`ALLOW_INSECURE_HTTP`); explicit `=none` already expresses intent (YAGNI).

### 3. Wiring in `app.py`

In `main()`, after resolving `transport` (unchanged logic), set:

```python
mcp.auth = build_auth(transport, os.environ)
```

before calling `mcp.run(...)`. The module-level `FastMCP` and every `@mcp.tool`
are untouched. The `none`/stdio path is byte-for-byte the v0.1.0 behavior →
backward compatible. `build_auth` is called once at startup; an
`AuthConfigError` surfaces as a clear startup failure (not a per-request error).

### 4. Config surface, docs, tests

- **`.env.example`**: a new commented `TICKTICK_MCP_AUTH=` block documenting all
  three modes and each mode's vars.
- **`README.md`**: a "Caller authentication" section covering:
  - local stdio (`none`),
  - remote static token (`token`) incl. setting the Claude connector custom
    `Authorization: Bearer <token>` header,
  - remote JWT/OAuth (`jwt`) incl. the served discovery endpoint and the IdP
    values a deployer must supply.
- **`tests/test_auth.py`** (no network — construct-and-assert-type only):
  - `none`/stdio and explicit `none` → `None`.
  - http + unset → raises `AuthConfigError`.
  - `token` mode returns `StaticTokenVerifier`; missing token → raises.
  - `jwt` mode with required vars (using a public key or a jwks uri) returns
    `RemoteAuthProvider`; missing/contradictory vars → raises.
  - invalid mode value → raises.
  - Assert `AuthConfigError` messages never contain a supplied secret value.
- **`pyproject.toml`**: bump `version` to `0.1.1`.

### 5. Scope boundary

This spec covers the **app repo (`ticktick-mcp` → v0.1.1) only.**

Out of scope (follow-on deployment task in `ticktick-mcp-dasha`):

- Edit `compose.yaml` to set `TICKTICK_MCP_AUTH=jwt` + the JWT vars, and remove
  the Authentik forward-auth middleware (`ticktick-strip@docker,authentik@file`)
  so JWT-bearing requests reach uvicorn.
- Create the Authentik OAuth2/OIDC provider + application for this MCP.

The README will list the exact env values the deploy needs, for a clean handoff.

⚠️ **Deploy-time risk (not an app-code blocker):** Claude's MCP connector relies
on OAuth Dynamic Client Registration (DCR) or a pre-registered client. The
follow-on task must confirm Authentik exposes DCR, or create a static client and
paste its Client ID into the Claude connector dialog.

## Acceptance (app)

- `build_auth("stdio", {})` → `None`.
- `build_auth("http", {})` → raises `AuthConfigError`.
- `build_auth("http", {"TICKTICK_MCP_AUTH": "token", "TICKTICK_MCP_BEARER_TOKEN": "x"})`
  → `StaticTokenVerifier`.
- `build_auth("http", {"TICKTICK_MCP_AUTH": "jwt", ...full jwt vars...})`
  → `RemoteAuthProvider`.
- `pytest` green; v0.1.0 stdio quickstart unchanged.

## Acceptance (deploy follow-on, for reference)

```bash
# No token -> 401 from uvicorn (not an authentik 404):
curl -sI https://ticktick.half.st/mcp/
# Discovery reaches the app:
curl -sI https://ticktick.half.st/.well-known/oauth-protected-resource  # 200, server: uvicorn
```
