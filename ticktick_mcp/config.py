"""Environment-sourced configuration.

No secret ever appears in source. Credentials are read from the environment at
runtime only, and this module is careful never to place a secret in a ``repr``,
log line, or exception message.

Required env vars:
    TICKTICK_USERNAME   TickTick account email / username.
    TICKTICK_PASSWORD   TickTick account password.

Optional env vars:
    TICKTICK_TOKEN_CACHE   Path to the on-disk session-token cache. Defaults to
                           ``$XDG_CACHE_HOME/ticktick-mcp/session.json`` (falling
                           back to ``~/.cache/ticktick-mcp/session.json``). This
                           path is gitignored and persisted by the Docker volume
                           (Slice 4) so login survives restarts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Config", "ConfigError", "load_config"]


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid.

    The message names which variable is wrong but never echoes a secret value.
    """


def _default_token_cache() -> Path:
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "ticktick-mcp" / "session.json"


@dataclass(frozen=True)
class Config:
    """Typed, immutable runtime configuration.

    Two auth modes are supported (see DESIGN.md §2):

    - **Session-token override** (``session_token`` set): use a session token
      lifted from a logged-in browser. Required for 2FA accounts, since the
      username/password ``signin`` flow has no second-factor step. The token
      cannot be auto-refreshed; on expiry the user supplies a new one.
    - **Password login** (``username`` + ``password`` set): the client signs in
      itself and can transparently re-auth on expiry.

    Both ``password`` and ``session_token`` are redacted from ``repr`` so neither
    can leak through a stack trace, log line, or debugger dump.
    """

    username: str | None = None
    password: str | None = field(default=None, repr=False)
    session_token: str | None = field(default=None, repr=False)
    token_cache_path: Path = field(default_factory=_default_token_cache)
    # Default IANA zone for *timed* tasks given without an explicit zone. All-day
    # tasks ignore this (they're encoded at UTC midnight — see client/dates.py).
    default_timezone: str = "UTC"

    @property
    def has_session_token(self) -> bool:
        return bool(self.session_token)

    @property
    def can_password_login(self) -> bool:
        return bool(self.username and self.password)

    def __post_init__(self) -> None:
        # Defensive: ``load_config`` already validates, but guard direct
        # construction too so an unusable config can never slip through.
        if not (self.has_session_token or self.can_password_login):
            raise ConfigError(
                "No usable credentials: set TICKTICK_SESSION_TOKEN, or both "
                "TICKTICK_USERNAME and TICKTICK_PASSWORD."
            )

    def __repr__(self) -> str:  # pragma: no cover - trivial, but keep secrets out
        return (
            f"Config(username={self.username!r}, "
            f"password={'***' if self.password else None}, "
            f"session_token={'***' if self.session_token else None}, "
            f"token_cache_path={str(self.token_cache_path)!r})"
        )


def load_config(env: dict[str, str] | None = None) -> Config:
    """Build a :class:`Config` from the environment.

    Accepts either a session-token override (``TICKTICK_SESSION_TOKEN``) or a
    username/password pair. The session token wins when both are present.

    Args:
        env: Mapping to read from; defaults to ``os.environ``. Injectable for
            tests so we never have to mutate the real environment.

    Raises:
        ConfigError: if neither auth mode is fully specified. The error names the
            missing variables but never includes a value.
    """
    source = os.environ if env is None else env

    username = (source.get("TICKTICK_USERNAME") or "").strip() or None
    password = source.get("TICKTICK_PASSWORD") or None  # not stripped: may be meaningful
    session_token = (source.get("TICKTICK_SESSION_TOKEN") or "").strip() or None

    if not (session_token or (username and password)):
        raise ConfigError(
            "Missing credentials. Set TICKTICK_SESSION_TOKEN (recommended, and "
            "required for 2FA accounts — paste the `t` cookie from a logged-in "
            "TickTick web session), OR set both TICKTICK_USERNAME and "
            "TICKTICK_PASSWORD. Copy .env.example to .env and fill one of these in."
        )

    cache_raw = (source.get("TICKTICK_TOKEN_CACHE") or "").strip()
    token_cache_path = Path(cache_raw).expanduser() if cache_raw else _default_token_cache()

    return Config(
        username=username,
        password=password,
        session_token=session_token,
        token_cache_path=token_cache_path,
        default_timezone=(source.get("TICKTICK_TIMEZONE") or "").strip() or "UTC",
    )
