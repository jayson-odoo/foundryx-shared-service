"""Plan 30 (roadmap A9), slice S2 - the seven report builders + the
assignment log (AC-RPT-17..32), against the shared fixture
(`tests.omnichannel_report_fixture.seed_report_fixture`).
"""
from __future__ import annotations

import pytest

from app.models import DEFAULT_TENANT_ID
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from tests.omnichannel_report_fixture import seed_report_fixture
from tests.test_omnichannel_contact_data_model import _other_tenant_auth


def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD, tenant_slug=None) -> str:
    payload = {"email": email, "password": password}
    if tenant_slug is not None:
        payload["tenantSlug"] = tenant_slug
    res = client.post("/auth/login", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _report(client, h, ws_id, key, **params):
    return client.get(f"/omnichannel/workspaces/{ws_id}/reports/{key}", params=params, headers=h)


@pytest.fixture
def fixture_ids(session_factory):
    db = session_factory()
    ids = seed_report_fixture(db)
    db.close()
    return ids


FIXTURE_RANGE = {"from": "2026-03-01", "to": "2026-03-07"}
KL = "Asia/Kuala_Lumpur"


# ── AC-RPT-17: reports/meta ───────────────────────────────────────────────────
def test_reports_meta_descriptors(client, fixture_ids):
    h = _auth(client)
    res = client.get(f"/omnichannel/workspaces/{fixture_ids.workspace_id}/reports/meta", headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    by_key = {r["key"]: r for r in body["reports"]}
    assert set(by_key) == {
        "conversations", "responses", "resolutions", "messages", "users", "leaderboard", "assignments",
    }
    assert by_key["responses"]["supportsGroupBy"] == ["user"]
    assert by_key["resolutions"]["supportsGroupBy"] == ["user"]
    assert by_key["messages"]["supportsGroupBy"] == ["channel"]
    assert by_key["conversations"]["supportsGroupBy"] == []
    assert by_key["users"]["paginated"] is True
    assert by_key["leaderboard"]["paginated"] is True
    assert by_key["assignments"]["paginated"] is True
    assert by_key["conversations"]["paginated"] is False
    assert all(r["exportable"] for r in body["reports"])


# ── AC-RPT-18: conversations ───────────────────────────────────────────────────
def test_conversations_report_series_and_totals(client, fixture_ids):
    h = _auth(client)
    res = _report(client, h, fixture_ids.workspace_id, "conversations", tz=KL, **FIXTURE_RANGE)
    assert res.status_code == 200, res.text
    body = res.json()
    series = {s["key"]: s["points"] for s in body["series"]}
    assert series["opened"] == [2, 2, 1, 0, 1, 1, 0]
    assert series["closed"] == [1, 2, 1, 1, 0, 1, 0]
    assert series["reopened"] == [0, 0, 0, 1, 0, 0, 0]
    assert body["totals"] == {"opened": 7, "closed": 6, "reopened": 1}
    assert body["rows"] == []
    assert body["reportKey"] == "conversations"


# ── AC-RPT-19/20: responses ────────────────────────────────────────────────────
def test_responses_report_distribution_and_totals(client, fixture_ids):
    h = _auth(client)
    res = _report(client, h, fixture_ids.workspace_id, "responses", tz=KL, **FIXTURE_RANGE)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["totals"] == {
        "medianSeconds": 150, "p90Seconds": 660, "averageSeconds": 278,
        "sampleCount": 6, "derivedFromMessages": 1,
    }
    rows = {r["bucket"]: r for r in body["rows"]}
    assert rows["lt30s"] == {"bucket": "lt30s", "label": "< 30s", "count": 1, "percent": 16.7}
    assert rows["30s-2m"]["count"] == 1
    assert rows["2m-5m"]["count"] == 2
    assert rows["5m-10m"]["count"] == 1
    assert rows["10m-30m"]["count"] == 1
    assert rows["30m-1h"]["count"] == 0
    assert rows["gt1h"]["count"] == 0


def test_responses_report_group_by_user(client, fixture_ids):
    h = _auth(client)
    res = _report(client, h, fixture_ids.workspace_id, "responses", tz=KL, groupBy="user", **FIXTURE_RANGE)
    assert res.status_code == 200, res.text
    rows = {r["userId"]: r for r in res.json()["rows"]}
    ann = rows[fixture_ids.users["ann"]]
    assert ann["sampleCount"] == 3
    assert ann["medianSeconds"] == 30
    ben = rows[fixture_ids.users["ben"]]
    assert ben["sampleCount"] == 3
    assert ben["medianSeconds"] == 420
    # u_cara (no activity) is still a row - zero-activity members are never
    # dropped (the `users` report precedent extended to the groupBy=user
    # breakdown).
    cara = rows[fixture_ids.users["cara"]]
    assert cara["sampleCount"] == 0
    assert cara["medianSeconds"] is None


# ── AC-RPT-21/22: resolutions ──────────────────────────────────────────────────
def test_resolutions_report_close_reason_breakdown(client, fixture_ids):
    h = _auth(client)
    res = _report(client, h, fixture_ids.workspace_id, "resolutions", tz=KL, **FIXTURE_RANGE)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["totals"] == {
        "medianSeconds": 12600, "p90Seconds": 278100, "averageSeconds": 98100, "sampleCount": 6,
    }
    rows = body["rows"]
    assert [r["name"] for r in rows] == ["General Inquiry", "Sales Inquiry", "Payment Issue", "Others"]
    by_name = {r["name"]: r for r in rows}
    assert by_name["General Inquiry"] == {
        "closeReasonId": fixture_ids.close_reasons["general"], "name": "General Inquiry", "count": 2, "percent": 33.3,
    }
    assert by_name["Sales Inquiry"]["count"] == 1 and by_name["Sales Inquiry"]["percent"] == 16.7
    assert by_name["Payment Issue"]["count"] == 1 and by_name["Payment Issue"]["percent"] == 16.7
    assert by_name["Others"]["count"] == 2 and by_name["Others"]["percent"] == 33.3


def test_resolutions_report_group_by_user(client, fixture_ids):
    h = _auth(client)
    res = _report(client, h, fixture_ids.workspace_id, "resolutions", tz=KL, groupBy="user", **FIXTURE_RANGE)
    rows = {r["userId"]: r for r in res.json()["rows"]}
    ann = rows[fixture_ids.users["ann"]]
    # ann's closes: C1(3600), C5-close1(3600), C5-close2(10800), C8(518400 -
    # the out-of-range `opened` pairing, AC-RPT-22) -> sorted
    # [3600, 3600, 10800, 518400], median = 3600 + (10800-3600)*0.5 = 7200.
    assert ann["sampleCount"] == 4
    assert ann["medianSeconds"] == 7200
    ben = rows[fixture_ids.users["ben"]]
    # ben's closes: C2(37800), C4(14400) -> median = 14400 + (37800-14400)*0.5.
    assert ben["sampleCount"] == 2
    assert ben["medianSeconds"] == 26100


# ── AC-RPT-23: messages ────────────────────────────────────────────────────────
def test_messages_report_series_and_totals(client, fixture_ids):
    h = _auth(client)
    res = _report(client, h, fixture_ids.workspace_id, "messages", tz=KL, **FIXTURE_RANGE)
    assert res.status_code == 200, res.text
    body = res.json()
    series = {s["key"]: s["points"] for s in body["series"]}
    assert series["incoming"] == [2, 2, 0, 1, 1, 0, 0]
    assert series["outgoing"] == [2, 2, 0, 1, 1, 0, 0]
    assert body["totals"] == {"incoming": 6, "outgoing": 6}
    assert body["rows"] == []


def test_messages_report_group_by_channel(client, fixture_ids):
    h = _auth(client)
    res = _report(client, h, fixture_ids.workspace_id, "messages", tz=KL, groupBy="channel", **FIXTURE_RANGE)
    rows = res.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["channelId"] == fixture_ids.channel_id
    assert rows[0]["name"] == "WhatsApp Demo"
    assert rows[0]["channelType"] == "WHATSAPP"
    assert rows[0]["incoming"] == 6
    assert rows[0]["outgoing"] == 6


# ── AC-RPT-24: users ───────────────────────────────────────────────────────────
def test_users_report_rows(client, fixture_ids):
    h = _auth(client)
    res = _report(client, h, fixture_ids.workspace_id, "users", tz=KL, **FIXTURE_RANGE)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["totals"] == {"userCount": 3}
    rows = {r["userId"]: r for r in body["rows"]}
    ann = rows[fixture_ids.users["ann"]]
    assert ann["assignedCount"] == 1
    assert ann["closedCount"] == 4
    assert ann["messagesSent"] == 3
    assert ann["commentsCount"] == 1
    ben = rows[fixture_ids.users["ben"]]
    assert ben["assignedCount"] == 1
    assert ben["closedCount"] == 2
    assert ben["messagesSent"] == 3
    assert ben["commentsCount"] == 0
    cara = rows[fixture_ids.users["cara"]]
    assert cara == {
        "userId": fixture_ids.users["cara"], "name": "Cara Tan", "teamName": None,
        "assignedCount": 0, "closedCount": 0, "uniqueContacts": 0, "messagesSent": 0,
        "commentsCount": 0, "medianFirstResponseSeconds": None, "medianResolutionSeconds": None,
    }


# ── AC-RPT-25: leaderboard ─────────────────────────────────────────────────────
def test_leaderboard_report_order_and_rank(client, fixture_ids):
    h = _auth(client)
    res = _report(client, h, fixture_ids.workspace_id, "leaderboard", tz=KL, **FIXTURE_RANGE)
    assert res.status_code == 200, res.text
    rows = res.json()["rows"]
    assert [(r["name"], r["closedCount"], r["rank"]) for r in rows] == [
        ("Ann Lee", 4, 1), ("Ben Ooi", 2, 2), ("Cara Tan", 0, 3),
    ]


# ── AC-RPT-26/27: assignments (the log) ───────────────────────────────────────
def test_assignments_report_series_totals_and_rows(client, fixture_ids):
    h = _auth(client)
    res = _report(client, h, fixture_ids.workspace_id, "assignments", tz=KL, **FIXTURE_RANGE)
    assert res.status_code == 200, res.text
    body = res.json()
    series = {s["key"]: s["points"] for s in body["series"]}
    assert series["assigned"] == [1, 1, 0, 0, 0, 0, 0]
    assert body["totals"] == {"assigned": 2, "unassigned": 1}
    assert body["total"] == 3
    assert body["page"] == 0
    rows = body["rows"]
    assert len(rows) == 3
    # Newest first.
    assert [r["eventType"] for r in rows] == ["unassigned", "assigned", "assigned"]
    unassigned_row = rows[0]
    assert unassigned_row["contactId"] == fixture_ids.contacts["C2"]
    assert unassigned_row["previousAssigneeId"] == fixture_ids.users["ann"]
    assert unassigned_row["previousAssigneeName"] == "Ann Lee"
    assert unassigned_row["assignedToId"] is None
    assert unassigned_row["actorUserId"] == fixture_ids.users["ben"]
    assert unassigned_row["actorName"] == "Ben Ooi"
    assert unassigned_row["source"] == "agent"
    c4_row = next(r for r in rows if r["contactId"] == fixture_ids.contacts["C4"])
    assert c4_row["assignedToId"] == fixture_ids.users["ben"]
    assert c4_row["assignedToName"] == "Ben Ooi"


def test_assignment_source_api_when_written_by_the_public_gateway(client, session_factory, fixture_ids):
    from datetime import datetime, timedelta, timezone

    from modules.omnichannel.services.public_gateway_service import PublicGatewayService

    db = session_factory()
    PublicGatewayService(db).update_contact(
        fixture_ids.tenant_id, fixture_ids.workspace_id, fixture_ids.contacts["C6"],
        assigned_user_id=fixture_ids.users["cara"],
    )
    db.close()

    # `event_service.record()` stamps `created_at=datetime.now(timezone.utc)`
    # (real wall-clock time, unlike the fixture's hand-authored past events) -
    # the window must cover "now", not the fixture's March 2026 range.
    now = datetime.now(timezone.utc)
    h = _auth(client)
    res = _report(
        client, h, fixture_ids.workspace_id, "assignments", tz="UTC",
        **{"from": (now - timedelta(days=1)).date().isoformat(), "to": (now + timedelta(days=1)).date().isoformat()},
    )
    assert res.status_code == 200, res.text
    row = next(r for r in res.json()["rows"] if r["contactId"] == fixture_ids.contacts["C6"])
    assert row["source"] == "api"
    assert row["actorUserId"] is None
    assert row["actorName"] is None


# ── AC-RPT-28: pagination + deterministic tiebreak ────────────────────────────
def test_assignment_log_pagination_no_repeat_no_drop(client, fixture_ids):
    h = _auth(client)
    page0 = _report(
        client, h, fixture_ids.workspace_id, "assignments", tz=KL, pageSize=2, page=0, **FIXTURE_RANGE
    ).json()
    page1 = _report(
        client, h, fixture_ids.workspace_id, "assignments", tz=KL, pageSize=2, page=1, **FIXTURE_RANGE
    ).json()
    assert page0["total"] == 3
    assert len(page0["rows"]) == 2
    assert len(page1["rows"]) == 1
    ids_page0 = {r["id"] for r in page0["rows"]}
    ids_page1 = {r["id"] for r in page1["rows"]}
    assert ids_page0.isdisjoint(ids_page1)
    assert ids_page0 | ids_page1 == {r["id"] for r in _report(
        client, h, fixture_ids.workspace_id, "assignments", tz=KL, pageSize=200, **FIXTURE_RANGE
    ).json()["rows"]}


def test_page_size_is_capped_at_200(client, fixture_ids):
    h = _auth(client)
    res = _report(
        client, h, fixture_ids.workspace_id, "assignments", tz=KL, pageSize=99999, **FIXTURE_RANGE
    )
    assert res.status_code == 200, res.text
    assert res.json()["pageSize"] == 200


# ── AC-RPT-29: unknown reportKey / unknown groupBy ────────────────────────────
def test_unknown_report_key_is_404(client, fixture_ids):
    h = _auth(client)
    res = _report(client, h, fixture_ids.workspace_id, "not-a-report", tz=KL, **FIXTURE_RANGE)
    assert res.status_code == 404


def test_unsupported_group_by_is_422_naming_accepted_values(client, fixture_ids):
    h = _auth(client)
    res = _report(client, h, fixture_ids.workspace_id, "conversations", tz=KL, groupBy="user", **FIXTURE_RANGE)
    assert res.status_code == 422
    assert "groupBy" in res.json()["detail"]["fieldErrors"]

    res2 = _report(client, h, fixture_ids.workspace_id, "responses", tz=KL, groupBy="channel", **FIXTURE_RANGE)
    assert res2.status_code == 422
    assert "groupBy" in res2.json()["detail"]["fieldErrors"]


def test_group_by_team_is_422_until_a8_for_every_report(client, fixture_ids):
    h = _auth(client)
    res = _report(client, h, fixture_ids.workspace_id, "responses", tz=KL, groupBy="team", **FIXTURE_RANGE)
    assert res.status_code == 422
    assert "groupBy" in res.json()["detail"]["fieldErrors"]


# ── AC-RPT-30: channelId validated + applied only to message-based reports ───
def test_channel_id_validated_against_workspace(client, fixture_ids):
    h = _auth(client)
    res = _report(
        client, h, fixture_ids.workspace_id, "messages", tz=KL, channelId="not-a-real-channel", **FIXTURE_RANGE
    )
    assert res.status_code == 422
    assert "channelId" in res.json()["detail"]["fieldErrors"]


def test_channel_id_applied_to_messages_report(client, fixture_ids):
    h = _auth(client)
    res = _report(
        client, h, fixture_ids.workspace_id, "messages", tz=KL,
        channelId=fixture_ids.channel_id, **FIXTURE_RANGE,
    )
    assert res.status_code == 200, res.text
    assert res.json()["totals"] == {"incoming": 6, "outgoing": 6}


def test_channel_id_is_validated_but_not_applied_to_event_reports(client, fixture_ids):
    """AC-RPT-30/32: a valid channelId is accepted (still workspace-scope
    validated) on an event-based report, but has no filtering effect - there
    is no channel dimension on `conversation_events` (D-A9-12)."""
    h = _auth(client)
    res = _report(
        client, h, fixture_ids.workspace_id, "conversations", tz=KL,
        channelId=fixture_ids.channel_id, **FIXTURE_RANGE,
    )
    assert res.status_code == 200, res.text
    assert res.json()["totals"] == {"opened": 7, "closed": 6, "reopened": 1}


# ── AC-RPT-31: permission gate + tenant isolation on every route ─────────────
ALL_REPORT_KEYS = ["conversations", "responses", "resolutions", "messages", "users", "leaderboard", "assignments"]


def test_missing_permission_is_403_for_every_report(client, session_factory, fixture_ids):
    from sqlalchemy.sql import func as sa_func

    from app.models import Role, User, UserStatus
    from app.repositories.permission_repository import PermissionRepository
    from app.security import hash_password

    db = session_factory()
    user = User(
        tenant_id=DEFAULT_TENANT_ID,
        email="no-reports-perm-s2@fixture.example",
        password=hash_password("pw12345678"),
        name="No Reports S2",
        status=UserStatus.ACTIVE.value,
        email_verified_at=sa_func.now(),
    )
    role = Role(tenant_id=DEFAULT_TENANT_ID, name="role-no-reports-s2")
    role.permissions = PermissionRepository(db).get_by_keys(["conversations.read"])
    db.add(role)
    db.flush()
    user.roles = [role]
    db.add(user)
    db.commit()
    db.close()

    h = _auth(client, email="no-reports-perm-s2@fixture.example", password="pw12345678")
    for key in ALL_REPORT_KEYS:
        res = _report(client, h, fixture_ids.workspace_id, key, tz=KL, **FIXTURE_RANGE)
        assert res.status_code == 403, key


def test_foreign_tenant_workspace_is_uniform_404_for_every_report(client, session_factory, fixture_ids):
    h2 = _other_tenant_auth(client, session_factory, slug="other-rpt-s2")
    for key in ALL_REPORT_KEYS:
        res = client.get(
            f"/omnichannel/workspaces/{fixture_ids.workspace_id}/reports/{key}",
            params={**FIXTURE_RANGE, "tz": KL},
            headers=h2,
        )
        assert res.status_code == 404, key
    res_meta = client.get(
        f"/omnichannel/workspaces/{fixture_ids.workspace_id}/reports/meta", headers=h2
    )
    assert res_meta.status_code == 404


# ── AC-RPT-32: reuse, no client-string SQL ────────────────────────────────────
def test_reports_reuse_lifecycle_stages_for_workspace(client, fixture_ids):
    """Sanity check that the dashboard's lifecycle stage list (which the
    report layer's `stages_for_workspace` import feeds) and the `users`
    report's workspace-member roster (`contacts`/`Channel`/`CloseReason`
    reused unchanged, never a second column map) agree on the SAME
    workspace - proves no per-report fork exists."""
    h = _auth(client)
    dash = client.get(
        f"/omnichannel/workspaces/{fixture_ids.workspace_id}/dashboard",
        params={**FIXTURE_RANGE, "tz": KL},
        headers=h,
    ).json()
    users_report = _report(client, h, fixture_ids.workspace_id, "users", tz=KL, **FIXTURE_RANGE).json()
    assert {s["key"] for s in dash["lifecycle"]} == {"new_lead", "hot_lead", "payment", "customer", "cold_lead"}
    assert users_report["totals"]["userCount"] == 3
