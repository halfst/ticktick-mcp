"""v2 API client layer.

DESIGN.md law: every TickTick v2 endpoint URL and raw payload shape lives ONLY
in this package. Nothing outside ``ticktick_mcp.client`` may construct a raw
request or know an endpoint path.

Slice 1 (done) provides auth + the transport chokepoint; Slice 2 adds the typed
endpoint methods on top of :class:`~ticktick_mcp.client.transport.Transport`.
"""

from .errors import APIError, AuthError, PayloadError, TickTickError
from .transport import BASE_URL, Transport

__all__ = [
    "Transport",
    "BASE_URL",
    "TickTickError",
    "AuthError",
    "APIError",
    "PayloadError",
]
