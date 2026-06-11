"""Session token: on-disk cache + the v2 login flow.

Auth provenance: the login endpoint, query params, headers, request body, and
token-extraction below were confirmed against current ``ticktick-py`` source
(``ticktick/api.py``, ``master``, read 2026-06). The v2 web API is undocumented
and may drift; re-confirm against source if login starts failing.

Key facts from that source:
- Base URL: ``https://api.ticktick.com/api/v2/``
- Login: ``POST user/signin?wc=true&remember=true`` with JSON ``{username, password}``
- Required headers: a browser ``User-Agent`` and an ``x-device`` JSON blob.
- The response JSON carries a ``token``; subsequent requests send it as cookie ``t``.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..config import Config
from .errors import AuthError, PayloadError

__all__ = ["TokenCache", "Authenticator", "USER_AGENT", "build_x_device"]

# Confirmed against ticktick-py (api.py). A real browser-ish UA; the API rejects
# obviously-bot agents.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:95.0) "
    "Gecko/20100101 Firefox/95.0"
)

_SIGNIN_PATH = "user/signin"
_SIGNIN_PARAMS = {"wc": "true", "remember": "true"}


def build_x_device(device_id: str) -> str:
    """Build the ``x-device`` header JSON the v2 API expects.

    Mirrors ticktick-py's ``X_DEVICE_`` constant. ``device_id`` is persisted in the
    token cache so the "device" stays stable across restarts, which makes TickTick
    less likely to issue a new-device challenge.
    """
    return json.dumps(
        {
            "platform": "web",
            "os": "OS X",
            "device": "Firefox 95.0",
            "name": "ticktick-mcp",
            "version": 4531,
            "id": device_id,
            "channel": "website",
            "campaign": "",
            "websocket": "",
        }
    )


def _new_device_id() -> str:
    # ticktick-py uses a "6490" prefix + secrets.token_hex(10).
    return "6490" + secrets.token_hex(10)


@dataclass
class _CacheData:
    token: str | None = None
    device_id: str = ""
    username: str = ""


class TokenCache:
    """Reads/writes the session token + device id at ``Config.token_cache_path``.

    The file is JSON: ``{"token", "device_id", "username"}``. The path is gitignored
    and, under Docker, lives on a persisted volume so login survives restarts.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> _CacheData:
        try:
            raw = json.loads(self._path.read_text())
        except (OSError, ValueError):
            return _CacheData()
        if not isinstance(raw, dict):
            return _CacheData()
        return _CacheData(
            token=raw.get("token") or None,
            device_id=str(raw.get("device_id") or ""),
            username=str(raw.get("username") or ""),
        )

    def save(self, data: _CacheData) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "token": data.token,
                    "device_id": data.device_id,
                    "username": data.username,
                }
            )
        )
        # Best-effort tighten perms; the token is sensitive.
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        tmp.replace(self._path)

    def clear_token(self, data: _CacheData) -> None:
        """Drop just the token (keep device id) after a 401."""
        data.token = None
        self.save(data)


class Authenticator:
    """Performs the v2 login and surfaces failures as actionable ``AuthError``.

    Stateless aside from the injected http client; the caller owns token storage.
    """

    def __init__(self, config: Config, http: httpx.Client) -> None:
        self._config = config
        self._http = http

    def login(self, device_id: str) -> str:
        """Sign in and return a fresh session token.

        Raises:
            AuthError: bad credentials, a captcha/device challenge, or any other
                response that did not yield a token. Never includes the password.
        """
        headers = {"User-Agent": USER_AGENT, "x-device": build_x_device(device_id)}
        body = {"username": self._config.username, "password": self._config.password}
        try:
            resp = self._http.post(
                _SIGNIN_PATH, params=_SIGNIN_PARAMS, json=body, headers=headers
            )
        except httpx.HTTPError as exc:
            raise AuthError(
                f"Could not reach TickTick to sign in: {exc.__class__.__name__}."
            ) from exc

        if resp.status_code == 200:
            return self._extract_token(resp)

        raise self._explain_failure(resp)

    @staticmethod
    def _extract_token(resp: httpx.Response) -> str:
        try:
            data: Any = resp.json()
        except ValueError as exc:
            raise PayloadError("Login returned a non-JSON body.") from exc
        token = data.get("token") if isinstance(data, dict) else None
        if not token:
            raise AuthError(
                "Login succeeded but no session token was returned "
                "(the v2 login response shape may have changed)."
            )
        return str(token)

    @staticmethod
    def _explain_failure(resp: httpx.Response) -> AuthError:
        # Try to surface the server's own error code without leaking anything secret.
        error_code = None
        try:
            payload = resp.json()
            if isinstance(payload, dict):
                error_code = payload.get("errorCode") or payload.get("errorId")
        except ValueError:
            pass

        if error_code in {"username_password_not_match", "user_not_sign_on"}:
            return AuthError(
                "TickTick rejected the username/password. Check TICKTICK_USERNAME "
                "and TICKTICK_PASSWORD."
            )
        if resp.status_code in (403, 429) or error_code:
            return AuthError(
                "TickTick blocked this sign-in, likely a captcha / new-device "
                "challenge (common from an unfamiliar IP). Log in once via the "
                "TickTick web client from this network, then retry. "
                f"(status={resp.status_code}"
                + (f", code={error_code}" if error_code else "")
                + ")"
            )
        return AuthError(
            f"Login failed with HTTP {resp.status_code}. The v2 API is unofficial "
            "and may have changed."
        )
