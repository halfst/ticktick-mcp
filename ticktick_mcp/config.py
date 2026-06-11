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

    The ``password`` field is redacted from ``repr`` so it cannot leak through a
    stack trace, log line, or debugger dump.
    """

    username: str
    password: str = field(repr=False)
    token_cache_path: Path

    def __post_init__(self) -> None:
        # Defensive: ``load_config`` already validates, but guard direct
        # construction too so an empty secret can never slip through.
        if not self.username:
            raise ConfigError("TICKTICK_USERNAME must not be empty.")
        if not self.password:
            raise ConfigError("TICKTICK_PASSWORD must not be empty.")

    def __repr__(self) -> str:  # pragma: no cover - trivial, but keep secrets out
        return (
            f"Config(username={self.username!r}, password='***', "
            f"token_cache_path={str(self.token_cache_path)!r})"
        )


def load_config(env: dict[str, str] | None = None) -> Config:
    """Build a :class:`Config` from the environment.

    Args:
        env: Mapping to read from; defaults to ``os.environ``. Injectable for
            tests so we never have to mutate the real environment.

    Raises:
        ConfigError: if a required variable is missing or blank. The error names
            the offending variable but never includes its value.
    """
    source = os.environ if env is None else env

    missing = [
        name
        for name in ("TICKTICK_USERNAME", "TICKTICK_PASSWORD")
        if not (source.get(name) or "").strip()
    ]
    if missing:
        raise ConfigError(
            "Missing required environment variable(s): "
            + ", ".join(missing)
            + ". Copy .env.example to .env and fill these in."
        )

    cache_raw = (source.get("TICKTICK_TOKEN_CACHE") or "").strip()
    token_cache_path = Path(cache_raw).expanduser() if cache_raw else _default_token_cache()

    return Config(
        username=source["TICKTICK_USERNAME"].strip(),
        password=source["TICKTICK_PASSWORD"],
        token_cache_path=token_cache_path,
    )
