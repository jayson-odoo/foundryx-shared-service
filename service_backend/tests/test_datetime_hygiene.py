"""Datetime hygiene (plan sprint-2/05, BL-012) - UTC end-to-end:

- columns are timezone-aware (UTCDateTime) and ALWAYS read back aware-UTC,
  on SQLite (tests) and Postgres alike;
- the wire Z-suffixes every datetime (offset never ambiguous again);
- users.timezone preference: PATCH /me/preferences, IANA-validated, rides
  the login payload + /auth/me.
"""
from datetime import datetime, timedelta, timezone

from app.models import DEFAULT_TENANT_ID
from app.models.user import User
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


def _login(client):
    res = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
    )
    assert res.status_code == 200
    return res.json()


def _auth(client) -> dict:
    return {"Authorization": f"Bearer {_login(client)['access_token']}"}


# ---- storage: aware-UTC in, aware-UTC out ----


def test_columns_read_back_aware_utc(client, session_factory):
    db = session_factory()
    try:
        user = db.query(User).filter(User.email == ACTIVE_EMAIL).first()
        assert user.created_at is not None
        assert user.created_at.tzinfo is not None  # never naive again
        assert user.created_at.utcoffset() == timedelta(0)
    finally:
        db.close()


def test_aware_offset_input_round_trips_to_utc(client, session_factory):
    """+08:00 input stores the INSTANT, reads back as aware UTC."""
    db = session_factory()
    try:
        user = db.query(User).filter(User.email == ACTIVE_EMAIL).first()
        sgt = timezone(timedelta(hours=8))
        user.last_sign_in_at = datetime(2026, 6, 1, 18, 30, tzinfo=sgt)
        db.commit()
        db.refresh(user)
        assert user.last_sign_in_at == datetime(
            2026, 6, 1, 10, 30, tzinfo=timezone.utc
        )
    finally:
        db.close()


# ---- wire: Z-suffixed ISO-8601 ----


def test_users_list_datetimes_are_z_suffixed(client):
    res = client.get("/users", headers=_auth(client))
    assert res.status_code == 200
    row = res.json()["data"][0]
    assert row["createdAt"].endswith("Z"), row["createdAt"]


def test_pending_email_change_datetimes_are_z_suffixed(client):
    headers = _auth(client)
    res = client.post(
        "/me/change-email",
        json={"newEmail": "zsuffix@example.com", "password": ACTIVE_PASSWORD},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["expiresAt"].endswith("Z"), body["expiresAt"]
    assert body["createdAt"].endswith("Z")
    # cleanup - cancel the ceremony so other specs see no pending row
    client.delete("/me/change-email", headers=headers)


# ---- timezone preference ----


def test_patch_me_preferences_sets_timezone(client):
    headers = _auth(client)
    res = client.patch(
        "/me/preferences",
        json={"timezone": "Asia/Singapore"},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["timezone"] == "Asia/Singapore"

    # rides /auth/me and the login payload
    assert client.get("/auth/me", headers=headers).json()["timezone"] == (
        "Asia/Singapore"
    )
    assert _login(client)["user"]["timezone"] == "Asia/Singapore"


def test_patch_me_preferences_clears_timezone_with_null(client):
    headers = _auth(client)
    client.patch(
        "/me/preferences", json={"timezone": "Asia/Tokyo"}, headers=headers
    )
    res = client.patch("/me/preferences", json={"timezone": None}, headers=headers)
    assert res.status_code == 200
    assert res.json()["timezone"] is None
    assert client.get("/auth/me", headers=headers).json()["timezone"] is None


def test_patch_me_preferences_rejects_unknown_zone(client):
    res = client.patch(
        "/me/preferences",
        json={"timezone": "Mars/Olympus_Mons"},
        headers=_auth(client),
    )
    assert res.status_code == 422


def test_patch_me_preferences_requires_auth(client):
    res = client.patch("/me/preferences", json={"timezone": "Asia/Tokyo"})
    assert res.status_code in (401, 403)
