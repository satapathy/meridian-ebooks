import base64

import pytest

from app import auth
from app.config import settings

from .conftest import make_epub


@pytest.fixture()
def locked(monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "s3cret!")
    auth._fails.clear()


def _up(client, **kw):
    return client.post("/api/books/upload", files=[("files", ("a.epub", make_epub(title="A", marker="au")))], **kw)


def test_open_when_no_credentials_configured(client):
    assert client.get("/api/auth/status").json() == {"auth_enabled": False, "admin": True}
    assert _up(client).status_code == 200
    assert client.post("/api/auth/login", json={"password": "y"}).status_code == 400


def test_reading_is_public_but_writes_need_admin(client, locked):
    assert client.get("/api/auth/status").json() == {"auth_enabled": True, "admin": False}
    assert client.get("/api/books").status_code == 200 and client.get("/api/facets").status_code == 200
    assert _up(client).status_code == 401
    assert client.post("/api/books/upload-folder", files=[("files", ("a.epub", b"x"))]).status_code == 401
    for method, url, kw in [("patch", "/api/books/x", {"json": {"title": "t"}}), ("delete", "/api/books/x", {}),
                            ("post", "/api/books/x/rename", {"json": {"filename": "n"}}),
                            ("put", "/api/books/x/cover", {"files": {"file": ("c.png", b"x")}}),
                            ("delete", "/api/books/x/cover", {}),
                            ("post", "/api/books/bulk-update", {"json": {"ids": ["x"], "fields": {"category": "c"}}}),
                            ("post", "/api/books/bulk-transform", {"json": {"ids": ["x"], "field": "title", "operation": "trim"}}),
                            ("post", "/api/books/bulk-delete", {"json": {"ids": ["x"]}}),
                            ("post", "/api/cleanup", {}), ("post", "/api/import", {"json": {"path": ""}}),
                            ("post", "/api/thumbnails/rebuild", {})]:
        assert getattr(client, method)(url, **kw).status_code == 401, (method, url)


def test_login_logout_cycle(client, locked):
    assert client.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    r = client.post("/api/auth/login", json={"password": "s3cret!"})
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()
    assert client.get("/api/auth/status").json()["admin"] is True
    assert _up(client).status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/auth/status").json()["admin"] is False
    assert _up(client).status_code == 401


def test_basic_auth_header_for_scripts(client, locked):
    good = {"Authorization": "Basic " + base64.b64encode(b"admin:s3cret!").decode()}
    bad = {"Authorization": "Basic " + base64.b64encode(b"admin:wrong").decode()}
    other_user = {"Authorization": "Basic " + base64.b64encode(b"root:s3cret!").decode()}
    assert _up(client, headers=bad).status_code == 401
    assert _up(client, headers=other_user).status_code == 401      # the user name is always admin
    assert _up(client, headers=good).status_code == 200


def test_forged_expired_and_stale_tokens_rejected(client, locked, monkeypatch):
    assert not auth.valid_token("9999999999.abc.deadbeef") and not auth.valid_token("garbage") and not auth.valid_token(None)
    tok = auth.make_token()
    assert auth.valid_token(tok)
    monkeypatch.setattr(auth.time, "time", lambda: 10**10)
    assert not auth.valid_token(tok)                                   # expired
    monkeypatch.undo()
    monkeypatch.setattr(settings, "admin_password", "changed")
    assert not auth.valid_token(tok)                                   # password changed -> old sessions die


def test_lockout_after_repeated_failures(client, locked):
    for _ in range(auth.MAX_FAILS):
        assert client.post("/api/auth/login", json={"password": "bad"}).status_code == 401
    assert client.post("/api/auth/login", json={"password": "s3cret!"}).status_code == 429
