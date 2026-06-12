"""Tests for the pluggable caller-auth factory.

These never touch the network or a real IdP — providers are constructed from an
injected env mapping and asserted by type. Secrets are dummy values.
"""

from __future__ import annotations

import pytest

from fastmcp.server.auth.auth import RemoteAuthProvider
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

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


def test_token_mode_error_names_var_without_echoing_input() -> None:
    # The only token-mode error path is an empty/whitespace token (it strips to
    # ""). The message must name the variable and must not echo the raw input.
    raw = "\t  \n"
    with pytest.raises(AuthConfigError) as exc_info:
        build_auth(
            "http",
            {"TICKTICK_MCP_AUTH": "token", "TICKTICK_MCP_BEARER_TOKEN": raw},
        )
    message = str(exc_info.value)
    assert "TICKTICK_MCP_BEARER_TOKEN" in message
    assert raw not in message


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
    env = dict(JWT_ENV)
    del env["TICKTICK_MCP_JWT_JWKS_URI"]
    with pytest.raises(AuthConfigError):
        build_auth("http", env)
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
