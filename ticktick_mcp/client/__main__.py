"""Live auth smoke test: ``python -m ticktick_mcp.client``.

Loads credentials from the environment, authenticates against the real v2 API,
and prints a small summary. Exits non-zero with a clear message on any failure.
Useful for confirming Slice 1 end-to-end with real credentials; it never prints a
secret.
"""

from __future__ import annotations

import sys

from ..config import ConfigError, load_config
from .errors import TickTickError
from .transport import Transport


def main() -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    try:
        with Transport(config) as transport:
            summary = transport.verify_auth()
    except TickTickError as exc:
        print(f"Auth check failed: {exc}", file=sys.stderr)
        return 1

    mode = (
        "session-token override"
        if config.has_session_token
        else f"password login (token cached at {config.token_cache_path})"
    )
    print(
        "Authenticated OK via "
        f"{mode}. inbox_id={summary['inbox_id']} "
        f"project_count={summary['project_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
