"""Avatar endpoints + PATCH /me/profile (plan sprint-2/06 D4/D5, BL-007).

Self routes are perm-free (like /auth/me); the admin route rides users.update.
The public route resolves the stored KEY per request - local backend here.
"""
import io

import pytest

from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD, INACTIVE_EMAIL

# Tiny valid magic-byte payloads (the sniffer reads headers, not full images).
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"0" * 64
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
GIF = b"GIF89a" + b"0" * 64


@pytest.fixture(autouse=True)
def local_media(monkeypatch, tmp_path):
    from app.config import settings

    monkeypatch.setattr(settings, "media_root", str(tmp_path))


def _login(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD):
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    body = res.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]


def _upload(client, headers, content=PNG, declared="image/png", path="/me/avatar"):
    return client.post(
        path,
        headers=headers,
        files={"file": ("avatar.png", io.BytesIO(content), declared)},
    )


# ── self-service (/me/avatar) ──────────────────────────────────────────────

def test_upload_own_avatar_roundtrip(client):
    h, me = _login(client)
    res = _upload(client, h)
    assert res.status_code == 200, res.text
    url = res.json()["avatar"]
    assert f"/public/avatars/{me['id']}?v=1" in url

    # /auth/me carries the same URL (session refresh path).
    assert client.get("/auth/me", headers=h).json()["avatar"] == url

    # The public route serves the bytes - no auth (avatars render in <img>).
    public = client.get(f"/public/avatars/{me['id']}")
    assert public.status_code == 200
    assert public.content == PNG
    assert public.headers["content-type"].startswith("image/png")


def test_replace_bumps_version(client):
    h, me = _login(client)
    assert "?v=1" in _upload(client, h).json()["avatar"]
    assert "?v=2" in _upload(client, h, content=JPEG).json()["avatar"]
    assert client.get(f"/public/avatars/{me['id']}").content == JPEG


def test_remove_own_avatar(client):
    h, me = _login(client)
    _upload(client, h)
    res = client.delete("/me/avatar", headers=h)
    assert res.status_code == 200
    assert res.json()["avatar"] is None
    assert client.get("/auth/me", headers=h).json()["avatar"] is None
    assert client.get(f"/public/avatars/{me['id']}").status_code == 404


def test_public_route_404s_without_avatar(client):
    _, me = _login(client)
    assert client.get(f"/public/avatars/{me['id']}").status_code == 404
    assert client.get("/public/avatars/nope").status_code == 404


# ── the sniff gate (D5 - declared type is ignored) ─────────────────────────

def test_webp_accepted(client):
    h, _ = _login(client)
    assert _upload(client, h, content=WEBP, declared="image/webp").status_code == 200


def test_svg_rejected_even_declared_png(client):
    h, _ = _login(client)
    res = _upload(client, h, content=SVG, declared="image/png")
    assert res.status_code == 422
    assert "png, jpg or webp" in res.json()["detail"].lower()


def test_gif_rejected(client):
    h, _ = _login(client)
    assert _upload(client, h, content=GIF, declared="image/gif").status_code == 422


def test_oversize_rejected(client):
    h, _ = _login(client)
    big = PNG + b"0" * (2 * 1024 * 1024)
    res = _upload(client, h, content=big)
    assert res.status_code == 422
    assert "2 mb" in res.json()["detail"].lower()


# ── admin path (/users/{id}/avatar) ────────────────────────────────────────

def test_admin_sets_another_users_avatar(client):
    h, _ = _login(client)
    target_id = next(
        u["id"]
        for u in client.get("/users?page_size=50", headers=h).json()["data"]
        if u["email"] == INACTIVE_EMAIL
    )
    res = _upload(client, h, path=f"/users/{target_id}/avatar")
    assert res.status_code == 200
    assert f"/public/avatars/{target_id}?v=1" in res.json()["avatar"]

    removed = client.delete(f"/users/{target_id}/avatar", headers=h)
    assert removed.status_code == 200
    assert removed.json()["avatar"] is None


def test_admin_route_404s_on_unknown_user(client):
    h, _ = _login(client)
    assert _upload(client, h, path="/users/ghost/avatar").status_code == 404


# ── PATCH /me/profile (plan 06 A5 backend) ─────────────────────────────────

def test_update_own_name(client):
    h, _ = _login(client)
    res = client.patch("/me/profile", json={"name": "Renamed Person"}, headers=h)
    assert res.status_code == 200
    assert res.json()["name"] == "Renamed Person"
    assert client.get("/auth/me", headers=h).json()["name"] == "Renamed Person"


def test_blank_name_rejected(client):
    h, _ = _login(client)
    assert client.patch("/me/profile", json={"name": "  "}, headers=h).status_code == 422


def test_profile_requires_auth(client):
    assert client.patch("/me/profile", json={"name": "X"}).status_code == 401
