"""Slice 1 acceptance tests: auth, token cache reuse, and 401 re-auth/retry.

No real network or credentials — every HTTP call is served by an in-memory
``httpx.MockTransport`` so the auth state machine is exercised deterministically.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from ticktick_mcp.client import AuthError, Transport
from ticktick_mcp.client.transport import BASE_URL
from ticktick_mcp.config import Config

SECRET = "pw-not-real"


def make_config(tmp_path: Path) -> Config:
    return Config(
        username="me@example.com",
        password=SECRET,
        token_cache_path=tmp_path / "session.json",
    )


def cookie_token(request: httpx.Request) -> str | None:
    raw = request.headers.get("cookie")
    if not raw:
        return None
    for part in raw.split(";"):
        name, _, value = part.strip().partition("=")
        if name == "t":
            return value
    return None


class FakeServer:
    """Programmable v2 endpoint stub. Counts logins; gates reads on the token."""

    def __init__(
        self,
        *,
        valid_tokens: set[str],
        next_token: str = "fresh",
        accept_issued: bool = True,
    ) -> None:
        self.valid_tokens = valid_tokens
        self.next_token = next_token
        # When False, login issues a token the read endpoint still rejects —
        # simulating a session that never takes (forces a persistent 401).
        self.accept_issued = accept_issued
        self.login_count = 0
        self.signin_response: httpx.Response | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/user/signin"):
            self.login_count += 1
            if self.signin_response is not None:
                return self.signin_response
            if self.accept_issued:
                self.valid_tokens.add(self.next_token)
            return httpx.Response(200, json={"token": self.next_token})
        if path.endswith("/batch/check/0"):
            if cookie_token(request) in self.valid_tokens:
                return httpx.Response(
                    200, json={"inboxId": "inbox123", "projectProfiles": [{"id": "p1"}]}
                )
            return httpx.Response(401, json={"errorCode": "user_not_sign_on"})
        return httpx.Response(404)

    def transport(self, config: Config) -> Transport:
        client = httpx.Client(transport=httpx.MockTransport(self.handler), base_url=BASE_URL)
        return Transport(config, http=client)


def test_first_run_logs_in_caches_token_second_run_reuses_it(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    server1 = FakeServer(valid_tokens=set(), next_token="tok-A")
    with server1.transport(config) as t:
        summary = t.verify_auth()
    assert summary == {"authenticated": True, "inbox_id": "inbox123", "project_count": 1}
    assert server1.login_count == 1

    # Token was persisted to the configured path...
    cached = json.loads((tmp_path / "session.json").read_text())
    assert cached["token"] == "tok-A"
    assert cached["username"] == "me@example.com"

    # ...and a second process reuses it WITHOUT logging in again.
    server2 = FakeServer(valid_tokens={"tok-A"})
    with server2.transport(config) as t:
        t.verify_auth()
    assert server2.login_count == 0


def test_expired_token_triggers_exactly_one_reauth_and_retry(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    # Seed a stale token that the server will reject.
    config.token_cache_path.write_text(
        json.dumps({"token": "stale", "device_id": "dev1", "username": "me@example.com"})
    )

    server = FakeServer(valid_tokens=set(), next_token="tok-new")
    with server.transport(config) as t:
        summary = t.verify_auth()

    assert summary["authenticated"] is True
    assert server.login_count == 1  # exactly one transparent re-auth
    assert json.loads(config.token_cache_path.read_text())["token"] == "tok-new"


def test_persistent_401_does_not_loop_and_surfaces_auth_error(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    # Start from a cached (stale) token so the only login here is the single
    # re-auth — isolating "re-auth exactly once, retry once, then give up".
    config.token_cache_path.write_text(
        json.dumps({"token": "stale", "device_id": "dev1", "username": "me@example.com"})
    )

    # Login "succeeds" but issues a token the read endpoint never accepts,
    # so every read is 401. Must re-auth once, retry once, then give up.
    server = FakeServer(valid_tokens=set(), next_token="rejected", accept_issued=False)
    with server.transport(config) as t:
        with pytest.raises(AuthError):
            t.verify_auth()
    assert server.login_count == 1


def test_bad_credentials_raise_clear_auth_error(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    server = FakeServer(valid_tokens=set())
    server.signin_response = httpx.Response(
        400, json={"errorCode": "username_password_not_match"}
    )
    with server.transport(config) as t:
        with pytest.raises(AuthError, match="username/password"):
            t.verify_auth()


def test_login_challenge_raises_actionable_auth_error(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    server = FakeServer(valid_tokens=set())
    server.signin_response = httpx.Response(429, text="too many attempts")
    with server.transport(config) as t:
        with pytest.raises(AuthError, match="challenge"):
            t.verify_auth()


def make_token_config(tmp_path: Path, token: str) -> Config:
    return Config(
        session_token=token,
        token_cache_path=tmp_path / "session.json",
    )


def test_session_token_override_skips_login(tmp_path: Path) -> None:
    # The 2FA path: a browser-supplied token is used directly, never signing in.
    config = make_token_config(tmp_path, "browser-tok")
    server = FakeServer(valid_tokens={"browser-tok"})
    with server.transport(config) as t:
        summary = t.verify_auth()
    assert summary["authenticated"] is True
    assert server.login_count == 0


def test_expired_session_token_raises_actionable_error_without_login(tmp_path: Path) -> None:
    config = make_token_config(tmp_path, "stale-browser-tok")
    server = FakeServer(valid_tokens=set())  # rejects the token -> 401
    with server.transport(config) as t:
        with pytest.raises(AuthError, match="TICKTICK_SESSION_TOKEN"):
            t.verify_auth()
    # Token-only mode must NOT attempt a password login on 401.
    assert server.login_count == 0


def test_session_token_overrides_a_different_cached_token(tmp_path: Path) -> None:
    config = make_token_config(tmp_path, "env-tok")
    config.token_cache_path.write_text(
        json.dumps({"token": "old-cached", "device_id": "d", "username": ""})
    )
    server = FakeServer(valid_tokens={"env-tok"})  # only the env token is accepted
    with server.transport(config) as t:
        assert t.verify_auth()["authenticated"] is True
    assert server.login_count == 0


def test_secret_never_written_to_token_cache(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    server = FakeServer(valid_tokens=set(), next_token="tok-A")
    with server.transport(config) as t:
        t.verify_auth()
    assert SECRET not in config.token_cache_path.read_text()
