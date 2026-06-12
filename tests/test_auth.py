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
