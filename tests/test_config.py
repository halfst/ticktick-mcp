"""Tests for environment-sourced configuration.

These never touch the real environment or a real credential — config is loaded
from an injected mapping.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ticktick_mcp.config import Config, ConfigError, load_config

SECRET = "hunter2-not-real"


def test_load_config_reads_required_vars() -> None:
    cfg = load_config({"TICKTICK_USERNAME": "me@example.com", "TICKTICK_PASSWORD": SECRET})
    assert cfg.username == "me@example.com"
    assert cfg.password == SECRET


def test_default_token_cache_is_outside_repo() -> None:
    cfg = load_config({"TICKTICK_USERNAME": "me@example.com", "TICKTICK_PASSWORD": SECRET})
    # Default lives under a cache dir, not in the working tree.
    assert cfg.token_cache_path.name == "session.json"
    assert "ticktick-mcp" in cfg.token_cache_path.parts


def test_token_cache_override_is_expanded() -> None:
    cfg = load_config(
        {
            "TICKTICK_USERNAME": "me@example.com",
            "TICKTICK_PASSWORD": SECRET,
            "TICKTICK_TOKEN_CACHE": "~/somewhere/tok.json",
        }
    )
    assert cfg.token_cache_path == Path.home() / "somewhere" / "tok.json"


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"TICKTICK_USERNAME": "me@example.com"},
        {"TICKTICK_PASSWORD": SECRET},
        {"TICKTICK_USERNAME": "  ", "TICKTICK_PASSWORD": SECRET},
    ],
)
def test_missing_required_vars_raises(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        load_config(env)


def test_secret_never_appears_in_repr() -> None:
    cfg = load_config({"TICKTICK_USERNAME": "me@example.com", "TICKTICK_PASSWORD": SECRET})
    assert SECRET not in repr(cfg)
    assert "***" in repr(cfg)


def test_direct_construction_rejects_empty_secret() -> None:
    with pytest.raises(ConfigError):
        Config(username="me@example.com", password="", token_cache_path=Path("/tmp/x"))


def test_session_token_alone_is_valid_config() -> None:
    cfg = load_config({"TICKTICK_SESSION_TOKEN": "tok-from-browser"})
    assert cfg.has_session_token is True
    assert cfg.can_password_login is False
    assert cfg.session_token == "tok-from-browser"


def test_session_token_redacted_in_repr() -> None:
    cfg = load_config({"TICKTICK_SESSION_TOKEN": "tok-from-browser"})
    assert "tok-from-browser" not in repr(cfg)
    assert "session_token=***" in repr(cfg)


def test_session_token_wins_when_both_modes_present() -> None:
    cfg = load_config(
        {
            "TICKTICK_SESSION_TOKEN": "tok",
            "TICKTICK_USERNAME": "me@example.com",
            "TICKTICK_PASSWORD": SECRET,
        }
    )
    assert cfg.has_session_token is True
    assert cfg.can_password_login is True  # available as a fallback, but token wins
