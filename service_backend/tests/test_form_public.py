"""Public (pre-auth) form surface tests (plan sprint-3/02, slice 2 §TDD).

Covers: open view + honeypot field · uniform 404 (unknown tenant/form,
internal-access form, unpublished form - no enumeration) · anonymous submit
lands a row (user_id NULL) · honeypot tripped → silently dropped (no row) ·
422 {fieldErrors} re-validated server-side · window-closed → view 'closed' +
POST 409 · per-IP throttle 429 with Retry-After.
"""
from datetime import datetime, timedelta, timezone

from app.config import settings
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


def _admin(client):
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _doc():
    return {
        "schemaVersion": 1,
        "pages": [
            {
                "id": "p1",
                "title": "Register",
                "sections": [
                    {
                        "id": "s1",
                        "fields": [
                            {"id": "f1", "type": "text", "key": "name", "label": "Name", "required": True},
                            {"id": "f2", "type": "email", "key": "email", "label": "Email", "required": True},
                        ],
                    }
                ],
            }
        ],
    }


def _publish_public_form(client, headers, **patch):
    res = client.post("/forms", json={"name": "Public Reg", "access": "public"}, headers=headers)
    assert res.status_code == 201, res.text
    form = res.json()
    body = {"draftDefinition": _doc()}
    body.update(patch)
    assert client.patch(f"/forms/{form['id']}", json=body, headers=headers).status_code == 200
    assert client.post(f"/forms/{form['id']}/publish", headers=headers).status_code == 200, "publish"
    return form


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


# ---- view ----


def test_public_view_open(client):
    headers = _admin(client)
    form = _publish_public_form(client, headers)
    res = client.get(f"/public/forms/default/{form['slug']}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["state"] == "open"
    assert body["definition"]["pages"]
    assert body["honeypotField"]
    assert body["formId"] == form["id"]


def test_public_view_unknown_is_404(client):
    headers = _admin(client)
    _publish_public_form(client, headers)
    assert client.get("/public/forms/default/does-not-exist").status_code == 404
    assert client.get("/public/forms/no-such-tenant/whatever").status_code == 404


def test_public_view_internal_form_is_404(client):
    """An internal published form must NOT be servable publicly (no leak)."""
    headers = _admin(client)
    res = client.post("/forms", json={"name": "Staff Only", "access": "internal"}, headers=headers)
    form = res.json()
    client.patch(f"/forms/{form['id']}", json={"draftDefinition": _doc()}, headers=headers)
    client.post(f"/forms/{form['id']}/publish", headers=headers)
    assert client.get(f"/public/forms/default/{form['slug']}").status_code == 404


def test_public_view_unpublished_is_404(client):
    headers = _admin(client)
    res = client.post("/forms", json={"name": "Draft Pub", "access": "public"}, headers=headers)
    form = res.json()
    client.patch(f"/forms/{form['id']}", json={"draftDefinition": _doc()}, headers=headers)
    # never published
    assert client.get(f"/public/forms/default/{form['slug']}").status_code == 404


# ---- submit ----


def _submissions(client, headers, form_id):
    res = client.get(f"/forms/{form_id}/submissions", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def test_public_submit_anonymous_lands_row(client):
    headers = _admin(client)
    form = _publish_public_form(client, headers)
    res = client.post(
        f"/public/forms/default/{form['slug']}/submissions",
        json={"answers": {"name": "Ada", "email": "ada@example.com"}},
    )
    assert res.status_code == 204, res.text
    rows = _submissions(client, headers, form["id"])
    assert rows["total"] == 1
    row = rows["data"][0]
    assert row["userId"] is None  # anonymous
    assert row["statusKey"] == "submitted"


def test_public_submit_honeypot_dropped(client):
    headers = _admin(client)
    form = _publish_public_form(client, headers)
    res = client.post(
        f"/public/forms/default/{form['slug']}/submissions",
        json={"answers": {"name": "Bot", "email": "bot@spam.com"}, "honeypot": "ACME Corp"},
    )
    # Pretend success, store nothing (never tip off the bot).
    assert res.status_code == 204
    assert _submissions(client, headers, form["id"])["total"] == 0


def test_public_submit_validation_422(client):
    headers = _admin(client)
    form = _publish_public_form(client, headers)
    res = client.post(
        f"/public/forms/default/{form['slug']}/submissions",
        json={"answers": {"name": "NoEmail"}},
    )
    assert res.status_code == 422
    assert "email" in res.json()["detail"]["fieldErrors"]


def test_public_submit_closed_window(client):
    headers = _admin(client)
    past = datetime.now(timezone.utc) - timedelta(days=1)
    form = _publish_public_form(client, headers, closesAt=_iso(past))
    view = client.get(f"/public/forms/default/{form['slug']}").json()
    assert view["state"] == "closed"
    assert view["definition"] is None
    res = client.post(
        f"/public/forms/default/{form['slug']}/submissions",
        json={"answers": {"name": "Late", "email": "late@example.com"}},
    )
    assert res.status_code == 409


def test_public_submit_throttle_429(client, monkeypatch):
    monkeypatch.setattr(settings, "throttle_form_public_max_fails", 2)
    headers = _admin(client)
    form = _publish_public_form(client, headers)
    url = f"/public/forms/default/{form['slug']}/submissions"
    body = {"answers": {"name": "A", "email": "a@example.com"}}
    assert client.post(url, json=body).status_code == 204
    assert client.post(url, json=body).status_code == 204
    res = client.post(url, json=body)
    assert res.status_code == 429
    assert res.headers.get("Retry-After")
