"""Breeze web-login callback and settings regression tests."""
from __future__ import annotations

import http.client
import json
import pytest

from src.core import config
from src.interface import backend
from src.interface import breeze_auth
from src.research_data.sources import breeze as breeze_source


@pytest.fixture(autouse=True)
def isolated_pending_logins(monkeypatch):
    monkeypatch.setattr(
        backend.breeze_auth, "PENDING_LOGINS", breeze_auth.PendingLogins()
    )


def _start_server():
    server, _ = backend.serve_backend(port=0, block=False)
    return server, int(server.server_address[1])


def _request(port: int, path: str, headers: dict | None = None,
             method: str = "GET", body: bytes | None = None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    response = conn.getresponse()
    body = response.read()
    out = response.status, dict(response.getheaders()), body
    conn.close()
    return out


def test_session_token_update_preserves_the_rest_of_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    metadata = tmp_path / "breeze_auth.json"
    env.write_text(
        "# local credentials\n"
        "BREEZE_API_KEY=key\n"
        "BREEZE_SESSION_TOKEN=old\n"
        "OTHER_SETTING=keep-me\n"
        "export BREEZE_SESSION_TOKEN=duplicate\n"
    )
    monkeypatch.delenv("BREEZE_SESSION_TOKEN", raising=False)

    refreshed_at = config.save_breeze_session_token(
        "fresh-token", env_path=env, metadata_path=metadata
    )

    assert env.read_text() == (
        "# local credentials\n"
        "BREEZE_API_KEY=key\n"
        "BREEZE_SESSION_TOKEN=fresh-token\n"
        "OTHER_SETTING=keep-me\n"
    )
    assert config.os.environ["BREEZE_SESSION_TOKEN"] == "fresh-token"
    assert config.load_breeze_session_refreshed_at(metadata) == refreshed_at
    assert json.loads(metadata.read_text()) == {
        "session_refreshed_at": refreshed_at,
    }


def test_settings_api_exposes_callback_but_no_credentials(monkeypatch):
    creds = config.BreezeCredentials("private-key", "private-secret", "daily-token")
    monkeypatch.setattr(backend.config, "load_credentials", lambda require_session=False: creds)
    monkeypatch.setattr(
        backend.config, "load_breeze_totp_secret",
        lambda: "JBSWY3DPEHPK3PXP",
    )
    monkeypatch.setattr(
        backend.config, "load_breeze_session_refreshed_at",
        lambda: "2026-08-23T12:34:56+00:00",
    )
    server, port = _start_server()
    try:
        status, _, body = _request(port, "/api/settings/breeze")
    finally:
        server.shutdown()
        server.server_close()

    assert status == 200
    payload = json.loads(body)
    assert payload == {
        "configured": True,
        "has_session_token": True,
        "session_refreshed_at": "2026-08-23T12:34:56+00:00",
        "totp_configured": True,
        "callback_url": f"http://127.0.0.1:{port}/auth/breeze/callback",
        "login_path": "/auth/breeze/login",
        "login_url": f"http://127.0.0.1:{port}/auth/breeze/login",
        "error": None,
    }
    assert b"private-key" not in body
    assert b"private-secret" not in body
    assert b"daily-token" not in body
    assert b"JBSWY3DPEHPK3PXP" not in body


def test_totp_matches_rfc_6238_sha1_vector():
    payload = breeze_auth.generate_totp(
        "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ",
        now=59,
        digits=8,
    )

    assert payload == {
        "code": "94287082",
        "period_seconds": 30,
        "valid_for_seconds": 1,
        "expires_at": "1970-01-01T00:01:00+00:00",
    }


def test_totp_api_returns_current_code_without_seed(monkeypatch):
    monkeypatch.setattr(
        backend.breeze_auth,
        "totp_payload",
        lambda: {
            "code": "123456",
            "period_seconds": 30,
            "valid_for_seconds": 12,
            "expires_at": "2026-08-23T12:35:00+00:00",
        },
    )
    server, port = _start_server()
    try:
        status, headers, body = _request(port, "/api/settings/breeze/totp")
    finally:
        server.shutdown()
        server.server_close()

    assert status == 200
    assert headers["Cache-Control"] == "no-store"
    assert json.loads(body) == {
        "code": "123456",
        "period_seconds": 30,
        "valid_for_seconds": 12,
        "expires_at": "2026-08-23T12:35:00+00:00",
    }


def test_totp_api_requires_configured_seed(monkeypatch):
    monkeypatch.setattr(backend.config, "load_breeze_totp_secret", lambda: None)
    server, port = _start_server()
    try:
        status, headers, body = _request(port, "/api/settings/breeze/totp")
    finally:
        server.shutdown()
        server.server_close()

    assert status == 400
    assert headers["Cache-Control"] == "no-store"
    assert json.loads(body) == {
        "error": "Add BREEZE_TOTP_SECRET to .env and restart the server."
    }


def test_login_callback_verifies_then_saves_without_echoing_token(monkeypatch):
    creds = config.BreezeCredentials("key", "secret", "old-token")
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(backend.config, "load_credentials", lambda require_session=False: creds)
    monkeypatch.setattr(
        backend.breeze_auth,
        "validate_session_token",
        lambda received, token: calls.append(("validate", token)),
    )
    monkeypatch.setattr(
        backend.config,
        "save_breeze_session_token",
        lambda token: calls.append(("save", token)),
    )

    server, port = _start_server()
    try:
        status, headers, _ = _request(
            port,
            "/auth/breeze/login?opener_origin=http%3A%2F%2F127.0.0.1%3A3000",
        )
        assert status == 302
        assert headers["Location"] == creds.login_url
        cookie = headers["Set-Cookie"].split(";", 1)[0]

        status, headers, body = _request(
            port,
            "/auth/breeze/callback?apisession=fresh-token",
            headers={"Cookie": cookie},
        )
    finally:
        server.shutdown()
        server.server_close()

    assert status == 200
    assert calls == [("validate", "fresh-token"), ("save", "fresh-token")]
    assert b"fresh-token" not in body
    assert b'const openerOrigin = "http://127.0.0.1:3000"' in body
    assert "Max-Age=0" in headers["Set-Cookie"]
    assert b"verified and saved" in body


def test_callback_without_settings_login_cannot_overwrite_token(monkeypatch):
    creds = config.BreezeCredentials("key", "secret", None)
    saved: list[str] = []
    monkeypatch.setattr(backend.config, "load_credentials", lambda require_session=False: creds)
    monkeypatch.setattr(backend.config, "save_breeze_session_token", saved.append)

    server, port = _start_server()
    try:
        status, _, body = _request(
            port, "/auth/breeze/callback?API_Session=unsolicited-token"
        )
    finally:
        server.shutdown()
        server.server_close()

    assert status == 400
    assert saved == []
    assert b"unsolicited-token" not in body
    assert b"not started from the brickbreak Settings page" in body


def test_form_post_callback_used_by_popup_verifies_and_saves(monkeypatch):
    creds = config.BreezeCredentials("key", "secret", None)
    saved: list[str] = []
    monkeypatch.setattr(backend.config, "load_credentials", lambda require_session=False: creds)
    monkeypatch.setattr(backend.breeze_auth, "validate_session_token", lambda *_: None)
    monkeypatch.setattr(backend.config, "save_breeze_session_token", saved.append)

    server, port = _start_server()
    try:
        status, headers, _ = _request(port, "/auth/breeze/login")
        assert status == 302
        cookie = headers["Set-Cookie"].split(";", 1)[0]

        status, _, response_body = _request(
            port,
            "/auth/breeze/callback",
            method="POST",
            body=b"apisession=popup-token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
    finally:
        server.shutdown()
        server.server_close()

    assert status == 200
    assert saved == ["popup-token"]
    assert b"popup-token" not in response_body
    assert b"verified and saved" in response_body


def test_form_post_without_pending_login_is_rejected(monkeypatch):
    saved: list[str] = []
    monkeypatch.setattr(backend.config, "save_breeze_session_token", saved.append)

    server, port = _start_server()
    try:
        status, _, response_body = _request(
            port,
            "/auth/breeze/callback",
            method="POST",
            body=b"apisession=unsolicited-token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    finally:
        server.shutdown()
        server.server_close()

    assert status == 400
    assert saved == []
    assert b"unsolicited-token" not in response_body
    assert b"not started from the brickbreak Settings page" in response_body


def test_validation_uses_authenticated_customer_details(monkeypatch):
    seen = {}

    class FakeSdk:
        def get_customer_details(self, api_session=""):
            seen["api_session"] = api_session
            return {"Success": {"account": "ok"}, "Status": 200, "Error": None}

    class FakeClient:
        def __init__(self, creds):
            seen["credentials"] = creds
            self.breeze = FakeSdk()

        def authenticate(self):
            seen["authenticated"] = True

    monkeypatch.setattr(breeze_source, "BreezeClient", FakeClient)
    creds = config.BreezeCredentials("key", "secret", "old")

    breeze_auth.validate_session_token(creds, "candidate")

    assert seen["credentials"].session_token == "candidate"
    assert seen["authenticated"] is True
    assert seen["api_session"] == "candidate"


def test_validation_rejects_error_response_without_echoing_it(monkeypatch):
    class FakeSdk:
        def get_customer_details(self, api_session=""):
            return {"Success": None, "Status": 401,
                    "Error": f"bad session {api_session}"}

    class FakeClient:
        def __init__(self, creds):
            self.breeze = FakeSdk()

        def authenticate(self):
            return None

    monkeypatch.setattr(breeze_source, "BreezeClient", FakeClient)

    try:
        breeze_auth.validate_session_token(
            config.BreezeCredentials("key", "secret", None), "sensitive-token"
        )
    except breeze_auth.BreezeAuthError as exc:
        assert str(exc) == "Breeze rejected the session token."
        assert "sensitive-token" not in str(exc)
    else:
        raise AssertionError("invalid token was accepted")
