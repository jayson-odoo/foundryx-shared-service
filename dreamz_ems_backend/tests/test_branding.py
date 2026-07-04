"""Tenant branding tests (plan sprint-2/03 §TDD — backend).

Token whitelist validation (422 with named errors) · default-equal values
normalize away · version bump per mutation · template prefilled with effective
values · asset upload caps + content sniffing + replace-deletes-old · public
endpoints (unknown slug = uniform defaults, never 404) · generated theme.css ·
RBAC boundaries (branding.read/manage, tenants.manage_branding, platform
tenant rejected).
"""
import io

import pytest

from app.services.storage import LocalDiskStorage, set_storage
from tests.conftest import (
    ACTIVE_EMAIL,
    ACTIVE_PASSWORD,
    PLATFORM_EMAIL,
    PLATFORM_PASSWORD,
)

# 1×1 transparent PNG (real magic bytes — content sniffing must pass).
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6260000000060001a2c1a1bd0000000049454e44ae426082"
)
SVG_BYTES = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'


@pytest.fixture(autouse=True)
def _tmp_storage(tmp_path):
    """Branding assets land in an isolated temp dir per test."""
    set_storage(LocalDiskStorage(str(tmp_path)))
    yield
    set_storage(None)


def _login(client, email, password, tenant_slug=None):
    payload = {"email": email, "password": password}
    if tenant_slug is not None:
        payload["tenantSlug"] = tenant_slug
    return client.post("/auth/login", json=payload)


def _demo_headers(client):
    res = _login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _platform_headers(client):
    res = _login(client, PLATFORM_EMAIL, PLATFORM_PASSWORD, "platform")
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _provision(client, headers, slug="acme", name="Acme Events"):
    res = client.post(
        "/platform/tenants",
        json={
            "name": name,
            "slug": slug,
            "adminName": "Kay Meister",
            "adminEmail": f"kay@{slug}.com",
            "adminPassword": "ChangeMe1!",
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


def _upload(client, headers, kind, content=PNG_BYTES, filename="a.png",
            mime="image/png", base="/branding"):
    return client.post(
        f"{base}/assets/{kind}",
        files={"file": (filename, io.BytesIO(content), mime)},
        headers=headers,
    )


# ---- own-tenant read/update ----


def test_get_branding_empty_defaults(client):
    res = client.get("/branding", headers=_demo_headers(client))
    assert res.status_code == 200
    body = res.json()
    assert body["slogan"] is None
    assert body["logoUrl"] is None
    assert body["tokens"] is None
    assert body["version"] == 0


def test_update_slogan_and_tokens_bumps_version(client):
    headers = _demo_headers(client)
    res = client.put(
        "/branding",
        json={"slogan": "  Events that scale.  ",
              "tokens": {"light": {"primary": "#0050FF"}, "dark": {}}},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["slogan"] == "Events that scale."
    assert body["tokens"] == {"light": {"primary": "#0050ff"}, "dark": {}}
    assert body["version"] == 1

    res = client.put("/branding", json={"slogan": None, "tokens": None}, headers=headers)
    assert res.json()["version"] == 2
    assert res.json()["tokens"] is None


def test_update_rejects_unknown_token_key(client):
    res = client.put(
        "/branding",
        json={"slogan": None, "tokens": {"light": {"not-a-token": "#ffffff"}, "dark": {}}},
        headers=_demo_headers(client),
    )
    assert res.status_code == 422
    assert "not-a-token" in res.text


def test_update_rejects_bad_color(client):
    res = client.put(
        "/branding",
        json={"slogan": None, "tokens": {"dark": {"primary": "blue"}}},
        headers=_demo_headers(client),
    )
    assert res.status_code == 422
    assert "dark.primary" in res.text


def test_default_equal_values_normalize_away(client):
    # Uploading the unchanged default = no override stored.
    res = client.put(
        "/branding",
        json={"slogan": None, "tokens": {"light": {"primary": "#FF5A00"}, "dark": {}}},
        headers=_demo_headers(client),
    )
    assert res.status_code == 200, res.text
    assert res.json()["tokens"] is None


def test_template_prefilled_with_effective_values(client):
    headers = _demo_headers(client)
    client.put(
        "/branding",
        json={"slogan": None, "tokens": {"light": {"primary": "#0050ff"}, "dark": {}}},
        headers=headers,
    )
    res = client.get("/branding/template", headers=headers)
    assert res.status_code == 200
    template = res.json()
    assert template["light"]["primary"] == "#0050ff"          # override reflected
    assert template["light"]["success"] == "#1f9d54"          # default prefilled
    assert "grey-500" in template["dark"]


# ---- assets ----


def test_upload_logo_and_serve_publicly(client):
    headers = _demo_headers(client)
    res = _upload(client, headers, "logo")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["logoUrl"] and "/public/branding/default/asset/logo" in body["logoUrl"]
    assert body["version"] == 1

    # Public asset endpoint streams it with the right content type — no auth.
    asset = client.get("/public/branding/default/asset/logo")
    assert asset.status_code == 200
    assert asset.headers["content-type"].startswith("image/png")
    assert asset.content == PNG_BYTES


def test_upload_rejects_wrong_type_for_favicon(client):
    res = _upload(client, _demo_headers(client), "favicon",
                  content=SVG_BYTES, filename="a.svg", mime="image/svg+xml")
    assert res.status_code == 422


def test_upload_rejects_oversize(client):
    big = PNG_BYTES + b"\x00" * (2 * 1024 * 1024)
    res = _upload(client, _demo_headers(client), "logo", content=big)
    assert res.status_code == 422
    assert "large" in res.text.lower()


def test_upload_rejects_unrecognized_content(client):
    # Not any known image format — rejected regardless of declared type.
    res = _upload(client, _demo_headers(client), "logo",
                  content=b"\x00\x01\x02garbage", filename="fake.png", mime="image/png")
    assert res.status_code == 422
    assert "Unrecognized" in res.text


def test_upload_trusts_sniffed_type_over_declared(client):
    # A JPEG renamed .png declares image/png — the DETECTED type wins: JPEG is
    # allowed for favicons, so this is accepted and stored as image/jpeg.
    jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 32
    res = _upload(client, _demo_headers(client), "favicon",
                  content=jpeg, filename="faviconV2.png", mime="image/png")
    assert res.status_code == 200, res.text
    asset = client.get("/public/branding/default/asset/favicon")
    assert asset.headers["content-type"].startswith("image/jpeg")


def test_replace_asset_deletes_old_file(client, tmp_path):
    headers = _demo_headers(client)
    _upload(client, headers, "logo")
    first_files = set(p for p in tmp_path.rglob("*") if p.is_file())
    assert len(first_files) == 1
    _upload(client, headers, "logo")
    second_files = set(p for p in tmp_path.rglob("*") if p.is_file())
    assert len(second_files) == 1
    assert first_files != second_files


def test_remove_asset(client, tmp_path):
    headers = _demo_headers(client)
    _upload(client, headers, "favicon")
    res = client.delete("/branding/assets/favicon", headers=headers)
    assert res.status_code == 200
    assert res.json()["faviconUrl"] is None
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]


def test_unknown_asset_kind_404(client):
    res = _upload(client, _demo_headers(client), "banner")
    assert res.status_code in (404, 422)


# ---- public endpoints ----


def test_public_branding_unknown_slug_uniform_defaults(client):
    # Unknown slug AND unbranded tenant look identical — no enumeration signal.
    unknown = client.get("/public/branding/no-such-tenant").json()
    unbranded = client.get("/public/branding/default").json()
    assert unknown == unbranded
    assert unknown["isBranded"] is False
    assert unknown["tenantName"] is None


def test_public_branding_branded_tenant(client):
    headers = _demo_headers(client)
    client.put(
        "/branding",
        json={"slogan": "Go live.", "tokens": {"light": {"primary": "#0050ff"}, "dark": {}}},
        headers=headers,
    )
    res = client.get("/public/branding/default")
    body = res.json()
    assert body["isBranded"] is True
    assert body["tenantName"] == "Dreamz EMS"  # the seeded default tenant's name
    assert body["slogan"] == "Go live."
    assert body["tokens"]["light"]["primary"] == "#0050ff"


def test_theme_css_renders_overrides_only(client):
    headers = _demo_headers(client)
    client.put(
        "/branding",
        json={"slogan": None,
              "tokens": {"light": {"primary": "#0050ff"}, "dark": {"danger": "#ff2200"}}},
        headers=headers,
    )
    res = client.get("/public/branding/default/theme.css")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/css")
    css = res.text
    assert ":root {" in css and ".dark {" in css
    assert "--dreamz-primary: #0050ff;" in css
    # Derived transparent companion rides along (0.2 alpha).
    assert "--dreamz-primary-transparent: rgba(0, 80, 255, 0.2);" in css
    assert "--dreamz-danger: #ff2200;" in css
    # Non-overridden vars are NOT emitted — defaults come from dreamz-tokens.css.
    assert "--dreamz-success" not in css


def test_theme_css_empty_for_unbranded(client):
    res = client.get("/public/branding/no-such-tenant/theme.css")
    assert res.status_code == 200
    assert res.text.strip() == ""


# ---- RBAC boundaries ----


def test_branding_requires_auth(client):
    assert client.get("/branding").status_code == 401


def test_manage_requires_branding_manage(client, session_factory):
    # Demote: a user holding only branding.read can read but not write.
    from app.models import DEFAULT_TENANT_ID, Role, User, UserStatus
    from app.models.permission import Permission
    from app.security import hash_password

    db = session_factory()
    read_perm = db.query(Permission).filter(Permission.key == "branding.read").one()
    viewer = Role(tenant_id=DEFAULT_TENANT_ID, name="Viewer")
    viewer.permissions = [read_perm]
    db.add(viewer)
    user = User(
        tenant_id=DEFAULT_TENANT_ID,
        email="viewer@example.com",
        password=hash_password("Viewer1234!"),
        name="Viewer",
        status=UserStatus.ACTIVE.value,
    )
    user.roles = [viewer]
    db.add(user)
    db.commit()
    db.close()

    res = _login(client, "viewer@example.com", "Viewer1234!")
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
    assert client.get("/branding", headers=headers).status_code == 200
    put = client.put("/branding", json={"slogan": "x", "tokens": None}, headers=headers)
    assert put.status_code == 403
    up = _upload(client, headers, "logo")
    assert up.status_code == 403


def test_operator_routes_blocked_for_tenant_admin(client):
    headers = _demo_headers(client)
    operator = _platform_headers(client)
    tenant = _provision(client, operator)
    res = client.get(f"/platform/tenants/{tenant['id']}/branding", headers=headers)
    assert res.status_code == 403


def test_operator_edits_tenant_branding(client):
    operator = _platform_headers(client)
    tenant = _provision(client, operator, slug="acme")
    base = f"/platform/tenants/{tenant['id']}/branding"

    res = client.put(
        base,
        json={"slogan": "Acme rocks.", "tokens": {"light": {"primary": "#112233"}, "dark": {}}},
        headers=operator,
    )
    assert res.status_code == 200, res.text
    up = _upload(client, operator, "logo", base=base)
    assert up.status_code == 200, up.text

    public = client.get("/public/branding/acme").json()
    assert public["isBranded"] is True
    assert public["slogan"] == "Acme rocks."
    assert public["tenantName"] == "Acme Events"
    assert "/public/branding/acme/asset/logo" in public["logoUrl"]


def test_platform_tenant_branding_rejected(client):
    operator = _platform_headers(client)
    # The console IS the product — the platform tenant keeps stock branding.
    tenants = client.get("/platform/tenants?pageSize=100", headers=operator).json()["data"]
    platform = next(t for t in tenants if t["isPlatform"])
    res = client.put(
        f"/platform/tenants/{platform['id']}/branding",
        json={"slogan": "x", "tokens": None},
        headers=operator,
    )
    assert res.status_code == 409


def test_asset_urls_version_busted(client):
    headers = _demo_headers(client)
    first = _upload(client, headers, "logo").json()["logoUrl"]
    second = _upload(client, headers, "logo").json()["logoUrl"]
    assert first != second  # ?v= bumps → cacheable URLs never go stale


# ---- review-driven coverage (sprint-2/03 code review) ----


def test_asset_response_carries_xss_guards(client):
    # Uploaded SVGs can embed <script>; the public route must sandbox the
    # document so direct navigation never executes it (stored-XSS guard).
    headers = _demo_headers(client)
    res = _upload(client, headers, "logo", content=SVG_BYTES,
                  filename="logo.svg", mime="image/svg+xml")
    assert res.status_code == 200, res.text
    asset = client.get("/public/branding/default/asset/logo")
    assert asset.status_code == 200
    assert "sandbox" in asset.headers.get("content-security-policy", "")
    assert asset.headers.get("x-content-type-options") == "nosniff"


def test_operator_read_unknown_tenant_404(client):
    operator = _platform_headers(client)
    res = client.get("/platform/tenants/no-such-id/branding", headers=operator)
    assert res.status_code == 404
    res = client.get("/platform/tenants/no-such-id/branding/template", headers=operator)
    assert res.status_code == 404


def test_operator_read_platform_tenant_allowed(client):
    # Reads on the platform tenant return the empty record (the console shows
    # its stock-branding notice); only WRITES reject with 409.
    operator = _platform_headers(client)
    tenants = client.get("/platform/tenants?pageSize=100", headers=operator).json()["data"]
    platform = next(t for t in tenants if t["isPlatform"])
    res = client.get(f"/platform/tenants/{platform['id']}/branding", headers=operator)
    assert res.status_code == 200
    assert res.json()["version"] == 0


def test_frontend_defaults_parity():
    """The frontend mirrors the canonical whitelist + Dreamz defaults
    (lib/branding-tokens.ts). validate_tokens normalizes default-equal values
    away, so ANY drift silently drops tenant overrides — this test pins the
    two copies together (review finding)."""
    import re
    from pathlib import Path

    from app.branding.token_whitelist import DREAMZ_DEFAULTS, TOKEN_DEFS

    ts_path = (
        Path(__file__).resolve().parents[2]
        / "dreamz_ems_frontend" / "lib" / "branding-tokens.ts"
    )
    src = ts_path.read_text()

    # Whitelist keys: def('key', ...) calls, in order.
    ts_keys = re.findall(r"def\('([a-z0-9-]+)',", src)
    assert ts_keys == [key for key, _ in TOKEN_DEFS]

    # Defaults: the DREAMZ_DEFAULTS block, split into light/dark sections.
    block = re.search(
        r"export const DREAMZ_DEFAULTS[^=]*=\s*\{(.*?)\n\};", src, re.DOTALL
    ).group(1)
    light_src, dark_src = re.split(r"\n\s*dark:\s*\{", block, maxsplit=1)
    pair = re.compile(r"'?([a-z0-9-]+)'?:\s*'(#[0-9a-f]{6})'")
    ts_light = dict(pair.findall(light_src.split("light: {", 1)[1]))
    ts_dark = dict(pair.findall(dark_src))
    assert ts_light == DREAMZ_DEFAULTS["light"]
    assert ts_dark == DREAMZ_DEFAULTS["dark"]
