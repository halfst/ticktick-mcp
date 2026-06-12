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


def _build_jwt_auth(source: Mapping[str, str]):
    raise AuthConfigError("jwt mode not implemented yet")  # replaced in Task 3
