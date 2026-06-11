"""Base request wrapper — the single chokepoint every endpoint method uses.

Responsibilities (DESIGN.md §1, §2, §4):
- Own the base URL, timeouts, and JSON handling.
- Attach the session token (cookie ``t``) and required headers to every call.
- Lazily authenticate, reusing a disk-cached token across process starts.
- On a ``401``, transparently re-authenticate ONCE and retry the request ONCE.
- Translate transport/HTTP/payload problems into the typed errors from
  ``errors.py`` — no raw ``httpx`` exception escapes this package.

Slice 2's endpoint methods are built on :meth:`Transport.request` and must not
construct their own HTTP calls.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import Config
from .errors import APIError, AuthError, PayloadError
from .session import USER_AGENT, Authenticator, TokenCache, _new_device_id, build_x_device

__all__ = ["Transport", "BASE_URL"]

BASE_URL = "https://api.ticktick.com/api/v2/"
_DEFAULT_TIMEOUT = 30.0


class Transport:
    """Authenticated JSON transport over the v2 web API."""

    def __init__(self, config: Config, *, http: httpx.Client | None = None) -> None:
        self._config = config
        self._http = http or httpx.Client(base_url=BASE_URL, timeout=_DEFAULT_TIMEOUT)
        self._cache = TokenCache(config.token_cache_path)
        self._auth = Authenticator(config, self._http)

        # Token-only mode: a session token was supplied directly (the 2FA path).
        # We can't sign in ourselves, so an expired token can't be auto-refreshed.
        self._token_only = config.has_session_token

        cached = self._cache.load()
        if config.session_token:
            # The env override always wins over whatever is cached.
            cached.token = config.session_token
        elif cached.username and cached.username != config.username:
            # Cached session belongs to a different account: discard its token.
            cached.token = None
        if not cached.device_id:
            cached.device_id = _new_device_id()
        cached.username = config.username or cached.username
        self._state = cached

    # -- public API used by Slice 2 ------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
    ) -> Any:
        """Make an authenticated request and return the parsed JSON body.

        Authenticates lazily if no token is cached, and performs exactly one
        transparent re-auth + retry on a ``401``.

        Raises:
            AuthError: authentication ultimately failed.
            APIError: a non-2xx, non-401 response.
            PayloadError: a 2xx response that was not valid JSON.
        """
        if self._state.token is None:
            self._authenticate()

        resp = self._send(method, path, params=params, json=json)
        if resp.status_code == 401:
            if self._token_only:
                # No password to sign in with (2FA path) — can't recover.
                raise AuthError(
                    "Session token was rejected (expired or revoked). Log into "
                    "TickTick in a browser, complete 2FA, copy the `t` cookie, and "
                    "update TICKTICK_SESSION_TOKEN."
                )
            # Cached token is stale: re-auth once and retry once.
            self._authenticate()
            resp = self._send(method, path, params=params, json=json)

        return self._parse(resp)

    def verify_auth(self) -> dict[str, Any]:
        """Minimal authenticated read proving end-to-end auth works.

        Hits the v2 full-state endpoint (``batch/check/0``) and returns a small,
        non-sensitive summary. This is the Slice 1 smoke read; real project/task
        methods live in Slice 2 and must not be inferred from this.
        """
        state = self.request("GET", "batch/check/0")
        if not isinstance(state, dict):
            raise PayloadError("batch/check returned an unexpected (non-object) body.")
        projects = state.get("projectProfiles") or []
        return {
            "authenticated": True,
            "inbox_id": state.get("inboxId"),
            "project_count": len(projects) if isinstance(projects, list) else 0,
        }

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "Transport":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- internals -----------------------------------------------------------

    def _authenticate(self) -> None:
        if not self._config.can_password_login:
            # Token-only mode with no/empty starting token: nothing to sign in with.
            raise AuthError(
                "No session token and no username/password available to sign in. "
                "Set TICKTICK_SESSION_TOKEN (paste the `t` cookie from a logged-in "
                "TickTick web session) or TICKTICK_USERNAME + TICKTICK_PASSWORD."
            )
        token = self._auth.login(self._state.device_id)
        self._state.token = token
        self._cache.save(self._state)

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None,
        json: Any | None,
    ) -> httpx.Response:
        headers = {
            "User-Agent": USER_AGENT,
            "x-device": build_x_device(self._state.device_id),
        }
        if self._state.token:
            # Set the cookie via header rather than the per-request ``cookies=``
            # arg, which httpx deprecates for ambiguous persistence semantics.
            headers["Cookie"] = f"t={self._state.token}"
        try:
            return self._http.request(
                method,
                path,
                params=params,
                json=json,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise APIError(
                f"Request to TickTick failed: {exc.__class__.__name__}."
            ) from exc

    def _parse(self, resp: httpx.Response) -> Any:
        if resp.status_code == 401:
            # Reached here only after a re-auth+retry also got 401.
            raise AuthError(
                "Still unauthorized after re-authenticating. The session was "
                "rejected twice — credentials may have changed or the account "
                "requires a web sign-in challenge."
            )
        if not resp.is_success:
            raise APIError(
                f"TickTick returned HTTP {resp.status_code}.",
                status_code=resp.status_code,
            )
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError as exc:
            raise PayloadError(
                f"Expected JSON from TickTick but got a {resp.status_code} non-JSON body."
            ) from exc
