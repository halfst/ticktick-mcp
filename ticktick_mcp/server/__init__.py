"""MCP server / tool layer.

DESIGN.md law: this layer is thin. Tools validate/shape inputs, call a typed
client method, and return a clean result. A tool NEVER touches a raw endpoint or
payload — it only calls ``ticktick_mcp.client`` methods.

The FastMCP app lives in :mod:`.app`; pure tool logic lives in :mod:`.handlers`.
``main`` imports the app lazily so importing this package (e.g. to test handlers)
does not require FastMCP to be installed.
"""

from __future__ import annotations

__all__ = ["main"]


def main() -> None:
    """Console-script entrypoint (``ticktick-mcp``): run the MCP server."""
    from .app import main as _main

    _main()
