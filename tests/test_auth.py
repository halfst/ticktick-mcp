"""Tests for the pluggable caller-auth factory.

These never touch the network or a real IdP — providers are constructed from an
injected env mapping and asserted by type. Secrets are dummy values.
"""

from __future__ import annotations

import pytest

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


def test_token_mode_error_never_leaks_secret() -> None:
    try:
        build_auth("http", {"TICKTICK_MCP_AUTH": "token", "TICKTICK_MCP_BEARER_TOKEN": "  "})
    except AuthConfigError as exc:
        assert "  " not in str(exc) or "TICKTICK_MCP_BEARER_TOKEN" in str(exc)
