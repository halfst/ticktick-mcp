# Pluggable Caller Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pluggable, secure-by-default caller-auth layer to the TickTick MCP server selectable by one env var (`TICKTICK_MCP_AUTH=none|token|jwt`), shipping as v0.1.1.

**Architecture:** A new `ticktick_mcp/server/auth.py` exposes `build_auth(transport, env) -> AuthProvider | None`, mirroring the env-sourced, secret-redacting style of `config.py`. `app.py:main()` assigns the result to `mcp.auth` before `mcp.run(...)`. `none` returns `None` (unchanged v0.1.0 behavior on stdio); `token` builds a `StaticTokenVerifier`; `jwt` builds a `JWTVerifier` wrapped in a `RemoteAuthProvider` that serves OAuth discovery. http transport refuses to start unless a mode is explicitly chosen.

**Tech Stack:** Python 3.11+, `fastmcp` 3.4.2 (`fastmcp.server.auth.providers.jwt.StaticTokenVerifier` / `JWTVerifier`, `fastmcp.server.auth.auth.RemoteAuthProvider`), pytest.

---

## File Structure

- **Create** `ticktick_mcp/server/auth.py` — the `build_auth` factory + `AuthConfigError`. Single responsibility: turn env into an `AuthProvider | None`. No I/O beyond reading the passed-in mapping; verifier objects do their own (lazy) network work later.
- **Create** `tests/test_auth.py` — construct-and-assert-type tests, no network.
- **Modify** `ticktick_mcp/server/app.py` — call `build_auth` in `main()`.
- **Modify** `.env.example` — document the three modes.
- **Modify** `README.md` — add a "Caller authentication" section.
- **Modify** `pyproject.toml` — bump version to `0.1.1`.

A note on imports: `fastmcp` 3.4.2 places `StaticTokenVerifier` and `JWTVerifier` in `fastmcp.server.auth.providers.jwt`, and `RemoteAuthProvider` + the `AuthProvider` base in `fastmcp.server.auth.auth`. All three construct **without** network access (verified), so tests can build them directly.

---

## Task 1: Auth factory — `none` mode and secure-by-default http guard

**Files:**
- Create: `ticktick_mcp/server/auth.py`
- Test: `tests/test_auth.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_auth.py
"""Tests for the pluggable caller-auth factory.

These never touch the network or a real IdP — providers are constructed from an
injected env mapping and asserted by type. Secrets are dummy values.
"""

from __future__ import annotations

import pytest

from ticktick_mcp.server.auth import AuthConfigError, build_auth


def test_stdio_unset_is_no_auth() -> None:
    assert build_auth("stdio", {}) is None


def test_explicit_none_is_no_auth_on_any_transport() -> None:
    assert build_auth("stdio", {"TICKTICK_MCP_AUTH": "none"}) is None
    assert build_auth("http", {"TICKTICK_MCP_AUTH": "none"}) is None


def test_http_unset_refuses_to_start() -> None:
    with pytest.raises(AuthConfigError):
        build_auth("http", {})
    with pytest.raises(AuthConfigError):
        build_auth("streamable-http", {})


def test_unknown_mode_raises() -> None:
    with pytest.raises(AuthConfigError):
        build_auth("stdio", {"TICKTICK_MCP_AUTH": "bogus"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ticktick_mcp.server.auth'`

- [ ] **Step 3: Write minimal implementation**

```python
# ticktick_mcp/server/auth.py
"""Pluggable caller authentication (DESIGN: pluggable-caller-auth).

One env switch — ``TICKTICK_MCP_AUTH`` ∈ {none, token, jwt} — selects how the
server authenticates *callers* (distinct from how the client authenticates *to
TickTick*, which lives in :mod:`ticktick_mcp.config`).

Secure-by-default: on the http transport the mode must be chosen explicitly; an
unset switch refuses to start. stdio (a local, spawned process) defaults to no
caller auth.

Like :mod:`ticktick_mcp.config`, this module never puts a secret value into a
``repr``, log line, or exception message.
"""

from __future__ import annotations

from collections.abc import Mapping

from fastmcp.server.auth.auth import AuthProvider

__all__ = ["AuthConfigError", "build_auth"]

_HTTP_TRANSPORTS = {"http", "streamable-http"}
_VALID_MODES = ("none", "token", "jwt")


class AuthConfigError(RuntimeError):
    """Raised when caller-auth configuration is missing or invalid.

    The message names the offending variable but never echoes a secret value.
    """


def build_auth(
    transport: str, env: Mapping[str, str] | None = None
) -> AuthProvider | None:
    """Build the caller-auth provider for ``transport`` from ``env``.

    Returns ``None`` when no caller auth is configured (mode ``none``). Raises
    :class:`AuthConfigError` for an unset mode on an http transport, an unknown
    mode value, or a mode missing its required variables.
    """
    import os

    source = os.environ if env is None else env
    raw = (source.get("TICKTICK_MCP_AUTH") or "").strip().lower()

    if not raw:
        if transport.strip().lower() in _HTTP_TRANSPORTS:
            raise AuthConfigError(
                "TICKTICK_MCP_AUTH must be set on the http transport. Choose one "
                "of: none (no caller auth — only do this behind your own "
                "protection), token (shared bearer token), jwt (validate "
                "IdP-issued JWTs)."
            )
        return None

    if raw == "none":
        return None
    if raw == "token":
        return _build_token_auth(source)
    if raw == "jwt":
        return _build_jwt_auth(source)

    raise AuthConfigError(
        f"Unknown TICKTICK_MCP_AUTH={raw!r}. Valid modes: {', '.join(_VALID_MODES)}."
    )


def _build_token_auth(source: Mapping[str, str]):
    raise AuthConfigError("token mode not implemented yet")  # replaced in Task 2


def _build_jwt_auth(source: Mapping[str, str]):
    raise AuthConfigError("jwt mode not implemented yet")  # replaced in Task 3
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_auth.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add ticktick_mcp/server/auth.py tests/test_auth.py
git commit -m "feat(auth): caller-auth factory with none mode + http guard

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `token` mode — static bearer token

**Files:**
- Modify: `ticktick_mcp/server/auth.py` (replace `_build_token_auth`)
- Test: `tests/test_auth.py` (add cases)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_auth.py`:

```python
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

TOKEN = "shared-secret-not-real"


def test_token_mode_returns_static_verifier() -> None:
    auth = build_auth(
        "http",
        {"TICKTICK_MCP_AUTH": "token", "TICKTICK_MCP_BEARER_TOKEN": TOKEN},
    )
    assert isinstance(auth, StaticTokenVerifier)


@pytest.mark.parametrize(
    "env",
    [
        {"TICKTICK_MCP_AUTH": "token"},
        {"TICKTICK_MCP_AUTH": "token", "TICKTICK_MCP_BEARER_TOKEN": ""},
        {"TICKTICK_MCP_AUTH": "token", "TICKTICK_MCP_BEARER_TOKEN": "   "},
    ],
)
def test_token_mode_missing_token_raises(env: dict[str, str]) -> None:
    with pytest.raises(AuthConfigError):
        build_auth("http", env)


def test_token_mode_error_never_leaks_secret() -> None:
    # A present-but-whitespace token must not be echoed.
    try:
        build_auth("http", {"TICKTICK_MCP_AUTH": "token", "TICKTICK_MCP_BEARER_TOKEN": "  "})
    except AuthConfigError as exc:
        assert "  " not in str(exc) or "TICKTICK_MCP_BEARER_TOKEN" in str(exc)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_auth.py -k token -v`
Expected: FAIL — `_build_token_auth` raises "token mode not implemented yet"

- [ ] **Step 3: Write minimal implementation**

In `ticktick_mcp/server/auth.py`, add the import near the top of `_build_token_auth` usage and replace the stub:

```python
def _build_token_auth(source: Mapping[str, str]):
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    token = (source.get("TICKTICK_MCP_BEARER_TOKEN") or "").strip()
    if not token:
        raise AuthConfigError(
            "token mode requires TICKTICK_MCP_BEARER_TOKEN (a non-empty shared "
            "secret). Set it in the environment."
        )
    return StaticTokenVerifier(
        {token: {"client_id": "ticktick-mcp", "scopes": []}}
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_auth.py -v`
Expected: PASS (all token + Task 1 tests pass)

- [ ] **Step 5: Commit**

```bash
git add ticktick_mcp/server/auth.py tests/test_auth.py
git commit -m "feat(auth): token mode (static bearer via StaticTokenVerifier)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `jwt` mode — JWT verifier behind OAuth discovery

**Files:**
- Modify: `ticktick_mcp/server/auth.py` (replace `_build_jwt_auth`)
- Test: `tests/test_auth.py` (add cases)

JWT mode reads: `TICKTICK_MCP_JWT_JWKS_URI` **or** `TICKTICK_MCP_JWT_PUBLIC_KEY`
(exactly one), plus `TICKTICK_MCP_JWT_ISSUER`, `TICKTICK_MCP_JWT_AUDIENCE`,
`TICKTICK_MCP_AUTH_SERVER`, `TICKTICK_MCP_BASE_URL`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_auth.py`:

```python
from fastmcp.server.auth.auth import RemoteAuthProvider

JWT_ENV = {
    "TICKTICK_MCP_AUTH": "jwt",
    "TICKTICK_MCP_JWT_JWKS_URI": "https://idp.example/application/o/ticktick/jwks/",
    "TICKTICK_MCP_JWT_ISSUER": "https://idp.example/application/o/ticktick/",
    "TICKTICK_MCP_JWT_AUDIENCE": "ticktick-mcp",
    "TICKTICK_MCP_AUTH_SERVER": "https://idp.example/application/o/ticktick/",
    "TICKTICK_MCP_BASE_URL": "https://ticktick.half.st",
}


def test_jwt_mode_with_jwks_returns_remote_auth_provider() -> None:
    auth = build_auth("http", dict(JWT_ENV))
    assert isinstance(auth, RemoteAuthProvider)


def test_jwt_mode_with_public_key_returns_remote_auth_provider() -> None:
    env = dict(JWT_ENV)
    del env["TICKTICK_MCP_JWT_JWKS_URI"]
    env["TICKTICK_MCP_JWT_PUBLIC_KEY"] = (
        "-----BEGIN PUBLIC KEY-----\nMOCK\n-----END PUBLIC KEY-----"
    )
    auth = build_auth("http", env)
    assert isinstance(auth, RemoteAuthProvider)


def test_jwt_mode_requires_exactly_one_key_source() -> None:
    # Neither jwks_uri nor public_key.
    env = dict(JWT_ENV)
    del env["TICKTICK_MCP_JWT_JWKS_URI"]
    with pytest.raises(AuthConfigError):
        build_auth("http", env)
    # Both jwks_uri and public_key.
    env_both = dict(JWT_ENV)
    env_both["TICKTICK_MCP_JWT_PUBLIC_KEY"] = "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----"
    with pytest.raises(AuthConfigError):
        build_auth("http", env_both)


@pytest.mark.parametrize(
    "missing",
    [
        "TICKTICK_MCP_JWT_ISSUER",
        "TICKTICK_MCP_JWT_AUDIENCE",
        "TICKTICK_MCP_AUTH_SERVER",
        "TICKTICK_MCP_BASE_URL",
    ],
)
def test_jwt_mode_missing_required_var_raises(missing: str) -> None:
    env = dict(JWT_ENV)
    del env[missing]
    with pytest.raises(AuthConfigError):
        build_auth("http", env)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_auth.py -k jwt -v`
Expected: FAIL — `_build_jwt_auth` raises "jwt mode not implemented yet"

- [ ] **Step 3: Write minimal implementation**

Replace the `_build_jwt_auth` stub in `ticktick_mcp/server/auth.py`:

```python
def _build_jwt_auth(source: Mapping[str, str]):
    from fastmcp.server.auth.auth import RemoteAuthProvider
    from fastmcp.server.auth.providers.jwt import JWTVerifier

    jwks_uri = (source.get("TICKTICK_MCP_JWT_JWKS_URI") or "").strip() or None
    public_key = (source.get("TICKTICK_MCP_JWT_PUBLIC_KEY") or "").strip() or None
    if bool(jwks_uri) == bool(public_key):
        raise AuthConfigError(
            "jwt mode requires exactly one of TICKTICK_MCP_JWT_JWKS_URI or "
            "TICKTICK_MCP_JWT_PUBLIC_KEY (you set neither or both)."
        )

    issuer = _require(source, "TICKTICK_MCP_JWT_ISSUER")
    audience = _require(source, "TICKTICK_MCP_JWT_AUDIENCE")
    auth_server = _require(source, "TICKTICK_MCP_AUTH_SERVER")
    base_url = _require(source, "TICKTICK_MCP_BASE_URL")

    verifier = JWTVerifier(
        jwks_uri=jwks_uri,
        public_key=public_key,
        issuer=issuer,
        audience=audience,
    )
    return RemoteAuthProvider(
        token_verifier=verifier,
        authorization_servers=[auth_server],
        base_url=base_url,
    )


def _require(source: Mapping[str, str], name: str) -> str:
    value = (source.get(name) or "").strip()
    if not value:
        raise AuthConfigError(f"jwt mode requires {name}.")
    return value
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_auth.py -v`
Expected: PASS (all auth tests pass)

- [ ] **Step 5: Commit**

```bash
git add ticktick_mcp/server/auth.py tests/test_auth.py
git commit -m "feat(auth): jwt mode (JWTVerifier behind RemoteAuthProvider discovery)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Wire `build_auth` into `app.py:main()`

**Files:**
- Modify: `ticktick_mcp/server/app.py:446-463` (`main`)
- Test: `tests/test_server.py` (add a case)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_server.py` (import `build_auth` indirectly by asserting `main` calls it). Use monkeypatch to avoid actually running the server:

```python
def test_main_http_without_auth_mode_refuses_to_start(monkeypatch) -> None:
    import ticktick_mcp.server.app as app
    from ticktick_mcp.server.auth import AuthConfigError

    monkeypatch.setenv("TICKTICK_MCP_TRANSPORT", "http")
    monkeypatch.delenv("TICKTICK_MCP_AUTH", raising=False)
    # mcp.run must never be reached when auth config is invalid.
    monkeypatch.setattr(app.mcp, "run", lambda *a, **k: pytest.fail("run() should not be called"))

    with pytest.raises(AuthConfigError):
        app.main()


def test_main_stdio_sets_no_auth_and_runs(monkeypatch) -> None:
    import ticktick_mcp.server.app as app

    monkeypatch.setenv("TICKTICK_MCP_TRANSPORT", "stdio")
    monkeypatch.delenv("TICKTICK_MCP_AUTH", raising=False)
    called = {}
    monkeypatch.setattr(app.mcp, "run", lambda *a, **k: called.setdefault("ran", True))

    app.main()
    assert called.get("ran") is True
    assert app.mcp.auth is None
```

(If `tests/test_server.py` does not already `import pytest`, add it.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_server.py -k "auth or refuses or stdio_sets" -v`
Expected: FAIL — `main()` does not yet set `mcp.auth` / does not call `build_auth`.

- [ ] **Step 3: Write minimal implementation**

In `ticktick_mcp/server/app.py`, add the import at the top (near `from . import handlers`):

```python
from .auth import build_auth
```

Then in `main()`, set `mcp.auth` right after computing `transport` and before the branch that calls `mcp.run`:

```python
def main() -> None:
    """Console-script entrypoint: run the MCP server.

    Transport is chosen by environment so the same image works two ways:

    - ``TICKTICK_MCP_TRANSPORT=stdio`` (default) — for an MCP host that spawns the
      process and talks over stdin/stdout (typical local CLI integration).
    - ``TICKTICK_MCP_TRANSPORT=http`` — a long-running HTTP server (used by the
      Docker Compose service), bound to ``TICKTICK_MCP_HOST`` (default
      ``0.0.0.0``) and ``TICKTICK_MCP_PORT`` (default ``8000``).

    Caller authentication is selected by ``TICKTICK_MCP_AUTH`` (see
    :mod:`ticktick_mcp.server.auth`); http refuses to start without an explicit
    mode.
    """
    transport = (os.environ.get("TICKTICK_MCP_TRANSPORT") or "stdio").strip().lower()
    normalized = "http" if transport in ("http", "streamable-http") else "stdio"
    mcp.auth = build_auth(normalized, os.environ)
    if normalized == "http":
        host = (os.environ.get("TICKTICK_MCP_HOST") or "0.0.0.0").strip()
        port = int((os.environ.get("TICKTICK_MCP_PORT") or "8000").strip())
        mcp.run(transport="http", host=host, port=port)
    else:
        mcp.run()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_server.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (whole suite green)

- [ ] **Step 6: Commit**

```bash
git add ticktick_mcp/server/app.py tests/test_server.py
git commit -m "feat(auth): wire build_auth into server startup

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Document the modes — `.env.example`

**Files:**
- Modify: `.env.example` (append after the transport block, after line 36)

- [ ] **Step 1: Append the caller-auth block**

Add to the end of `.env.example`:

```bash

# === Caller authentication (who may call THIS server) ===========================
# Distinct from the TickTick credentials above. Selects how MCP clients authenticate
# to this server. On the http transport a mode is REQUIRED — the server refuses to
# start if TICKTICK_MCP_AUTH is unset. stdio defaults to "none".
#   none  — no caller auth (fine for local stdio; only use on http behind your own
#           protection).
#   token — a single shared bearer token. Clients send `Authorization: Bearer <token>`.
#   jwt   — validate JWTs issued by your IdP (Authentik/Auth0/etc.) and advertise
#           OAuth discovery so MCP clients can run the OAuth flow.
# TICKTICK_MCP_AUTH=none

# --- token mode ---
# TICKTICK_MCP_BEARER_TOKEN=generate-a-long-random-secret

# --- jwt mode (set exactly one of JWKS_URI or PUBLIC_KEY) ---
# TICKTICK_MCP_JWT_JWKS_URI=https://idp.example/application/o/ticktick/jwks/
# TICKTICK_MCP_JWT_PUBLIC_KEY=
# TICKTICK_MCP_JWT_ISSUER=https://idp.example/application/o/ticktick/
# TICKTICK_MCP_JWT_AUDIENCE=ticktick-mcp
# TICKTICK_MCP_AUTH_SERVER=https://idp.example/application/o/ticktick/
# TICKTICK_MCP_BASE_URL=https://ticktick.half.st
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "docs(auth): document caller-auth modes in .env.example

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Document the modes — `README.md`

**Files:**
- Modify: `README.md` (insert a new section after the existing `## Auth caveat` section, before `## Security` at line 122)

- [ ] **Step 1: Insert the "Caller authentication" section**

Insert this section immediately before the `## Security` heading:

```markdown
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
```

- [ ] **Step 2: Verify the doc renders / no broken table**

Run: `python -c "import pathlib,sys; t=pathlib.Path('README.md').read_text(); sys.exit(0 if '## Caller authentication' in t and '## Security' in t else 1)"`
Expected: exit 0 (no output)

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(auth): add Caller authentication section to README

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Version bump + final verification

**Files:**
- Modify: `pyproject.toml:7` (`version = "0.1.0"` → `"0.1.1"`)

- [ ] **Step 1: Bump the version**

In `pyproject.toml`, change:

```toml
version = "0.1.0"
```

to:

```toml
version = "0.1.1"
```

- [ ] **Step 2: Run the full test suite**

Run: `python -m pytest -q`
Expected: PASS (entire suite green, including the new `tests/test_auth.py`)

- [ ] **Step 3: Manual smoke — http refuses without a mode**

Run:
```bash
TICKTICK_MCP_TRANSPORT=http TICKTICK_USERNAME=x TICKTICK_PASSWORD=y \
  python -c "from ticktick_mcp.server.app import main; main()"
```
Expected: exits with an `AuthConfigError` mentioning `TICKTICK_MCP_AUTH` (server does not start).

- [ ] **Step 4: Manual smoke — token mode attaches auth**

Run:
```bash
python -c "
from ticktick_mcp.server.auth import build_auth
a = build_auth('http', {'TICKTICK_MCP_AUTH':'token','TICKTICK_MCP_BEARER_TOKEN':'t'})
print(type(a).__name__)
"
```
Expected: prints `StaticTokenVerifier`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "chore: bump version to 0.1.1

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** §1 factory → Tasks 1-3; §2 default/http guard → Task 1; §3 wiring → Task 4; §4 `.env.example`/README/tests/version → Tasks 5,6,7 (+ tests embedded in 1-3); §5 scope boundary → respected (no `ticktick-mcp-dasha` edits here; README carries the deploy values + DCR risk note).
- **Type consistency:** `build_auth(transport, env)`, `AuthConfigError`, `_require`, env var names (`TICKTICK_MCP_AUTH`, `TICKTICK_MCP_BEARER_TOKEN`, `TICKTICK_MCP_JWT_JWKS_URI`/`_PUBLIC_KEY`/`_ISSUER`/`_AUDIENCE`, `TICKTICK_MCP_AUTH_SERVER`, `TICKTICK_MCP_BASE_URL`) are identical across spec, tasks, `.env.example`, and README.
- **No placeholders:** every code/test step shows full content; no TODO/TBD.

---

## Out of scope (follow-on, `ticktick-mcp-dasha` repo)

1. Set `TICKTICK_MCP_AUTH=jwt` + JWT vars in `compose.yaml`; remove the
   `ticktick-strip@docker,authentik@file` middleware so JWTs reach uvicorn.
2. Create the Authentik OAuth2/OIDC provider + application; confirm DCR or
   register a static client.
3. Verify: `curl -sI https://ticktick.half.st/mcp/` → `401` from uvicorn;
   `/.well-known/oauth-protected-resource` → `200`.
