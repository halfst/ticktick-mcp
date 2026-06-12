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

import os
from collections.abc import Mapping

# The ``AuthProvider`` base type is cheap and needed for the public signature, so
# it is imported here. The concrete providers (StaticTokenVerifier, JWTVerifier,
# RemoteAuthProvider) pull in fastmcp's auth subsystem and are deferred into the
# private builders below so importing this module stays light.
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


def _build_token_auth(source: Mapping[str, str]) -> AuthProvider:
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    token = (source.get("TICKTICK_MCP_BEARER_TOKEN") or "").strip()
    if not token:
        raise AuthConfigError(
            "token mode requires TICKTICK_MCP_BEARER_TOKEN (a non-empty shared "
            "secret). Set it in the environment."
        )
    # StaticTokenVerifier maps each accepted token to its claims; a single shared
    # bearer caller needs no scopes.
    return StaticTokenVerifier(
        {token: {"client_id": "ticktick-mcp", "scopes": []}}
    )


def _build_jwt_auth(source: Mapping[str, str]) -> AuthProvider:
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
