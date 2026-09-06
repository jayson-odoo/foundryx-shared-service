"""Omnichannel team assignment - plan 28 S2 (roadmap A8). Covers AC-TEM-15
(module half), 18-31, plus this slice's share of AC-TEM-49 (module-backend
pytest matrix).

`team_directory`/`team_assignment_service` are the module's only door to
core teams; `ConversationService.patch_thread`'s reworked assignee block
implements the four combinations (§5.2); `ContactRepository.list_threads`
gains `teamId`; the plan-27 `conversation_events` payload gains the team.
"""
import pytest
from sqlalchemy import event
from sqlalchemy.sql import func

from app.models import DEFAULT_TENANT_ID, Role, User, UserStatus
from app.security import hash_password
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


# ── shared helpers (mirrors test_teams.py / test_omnichannel_contacts_module.py) ──
def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD, tenant_slug=None) -> str:
    body = {"email": email, "password": password}
    if tenant_slug:
        body["tenantSlug"] = tenant_slug
    res = client.post("/auth/login", json=body)
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _workspace_id(client, h) -> str:
    data = client.get("/omnichannel/workspaces", headers=h).json()["data"]
    return next(w["id"] for w in data if w["isDefault"])


def _user(session_factory, email, *, active=True, tenant_id=DEFAULT_TENANT_ID) -> str:
    db = session_factory()
    user = User(
        tenant_id=tenant_id,
        email=email,
        password=hash_password("pw12345678"),
        name=email.split("@")[0],
        status=UserStatus.ACTIVE.value if active else UserStatus.INACTIVE.value,
        email_verified_at=func.now(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    uid = user.id
    db.close()
    return uid


def _add_workspace_member(session_factory, ws_id: str, user_id: str) -> None:
    from modules.omnichannel.models import WorkspaceMember

    db = session_factory()
    db.add(WorkspaceMember(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws_id, user_id=user_id))
    db.commit()
    db.close()


def _create_team(client, h, name: str, member_ids=None) -> dict:
    body = {
        "name": name,
        "members": [{"userId": uid, "role": "member"} for uid in (member_ids or [])],
    }
    res = client.post("/teams", headers=h, json=body)
    assert res.status_code == 201, res.text
    return res.json()


def _seed_contact(
    session_factory,
    ws_id: str,
    *,
    status_key: str = "OPEN",
    assigned_user_id=None,
    assigned_team_id=None,
    name="Thread",
) -> str:
    from modules.omnichannel.models import Contact
    from modules.omnichannel.services import statuses

    db = session_factory()
    c = Contact(
        tenant_id=DEFAULT_TENANT_ID,
        workspace_id=ws_id,
        first_name=name,
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "THREAD", status_key),
        assigned_user_id=assigned_user_id,
        assigned_team_id=assigned_team_id,
    )
    db.add(c)
    db.commit()
    cid = c.id
    db.close()
    return cid


def _grant_only(client, session_factory, email, *, keys, password="pw12345678"):
    admin = _auth(client)
    role = client.post(
        "/roles", headers=admin, json={"name": f"Custom {email}", "permissionKeys": keys}
    ).json()
    db = session_factory()
    user = User(
        tenant_id=DEFAULT_TENANT_ID,
        email=email,
        password=hash_password(password),
        name=email.split("@")[0],
        status=UserStatus.ACTIVE.value,
        email_verified_at=func.now(),
    )
    role_row = db.query(Role).filter(Role.id == role["id"]).first()
    user.roles = [role_row]
    db.add(user)
    db.commit()
    db.close()
    return {"Authorization": f"Bearer {_token(client, email=email, password=password)}"}


# ── AC-TEM-18: migration + manifest ──────────────────────────────────────────
def test_manifest_version_and_model_shape(session_factory):
    import json
    from pathlib import Path

    from modules.omnichannel.models import Contact, TeamAssignmentSetting

    manifest = json.loads(
        (Path(__file__).resolve().parents[1] / "modules" / "omnichannel" / "manifest.json").read_text()
    )
    # Plan 33 S1 bumped the manifest to 0.7.0 - this test pins "the CURRENT
    # manifest version", not a fixed string (updated the same way every prior
    # version bump updated it before).
    assert manifest["version"] == "0.7.0"
    assert any(r["name"] == "team_settings" for r in manifest["routers"])
    assert hasattr(Contact, "assigned_team_id")
    assert TeamAssignmentSetting.__tablename__ == "team_assignment_settings"

    # The table is genuinely usable (create_all path, mirrors the migration).
    db = session_factory()
    db.query(TeamAssignmentSetting).count()
    db.close()


# ── AC-TEM-19: validate assignedTeamId at write ──────────────────────────────
def test_patch_assign_team_validates_unknown_and_inactive(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    cid = _seed_contact(session_factory, ws)

    res = client.patch(
        f"/omnichannel/contacts/{cid}", headers=h, json={"assignedTeamId": "nope"}
    )
    assert res.status_code == 422, res.text
    assert "assignedTeamId" in res.json()["detail"]["fieldErrors"]

    inactive = _create_team(client, h, "Inactive Squad")
    client.patch(f"/teams/{inactive['id']}", headers=h, json={"isActive": False})
    res = client.patch(
        f"/omnichannel/contacts/{cid}", headers=h, json={"assignedTeamId": inactive["id"]}
    )
    assert res.status_code == 422, res.text
    assert "assignedTeamId" in res.json()["detail"]["fieldErrors"]

    db = session_factory()
    from modules.omnichannel.models import Contact

    c = db.query(Contact).filter(Contact.id == cid).first()
    assert c.assigned_team_id is None
    db.close()


def _provision_other_tenant(session_factory, slug="other-team-assign"):
    from app.services.tenant_service import TenantService

    db = session_factory()
    tenant = TenantService(db).provision(
        name="Other Team Assign",
        slug=slug,
        admin_email=f"admin-{slug}@example.com",
        admin_password="Password123!",
        admin_name="Admin",
    )
    db.commit()
    tenant_id = tenant.id
    db.close()
    return tenant_id, f"admin-{slug}@example.com", "Password123!"


def test_patch_assign_team_foreign_tenant_id_rejected(client, session_factory):
    """A team id belonging to another tenant fails `team.resolve@1` (returns
    None, never another tenant's team) - 422, same as an unknown id."""
    _tenant_id, other_email, other_password = _provision_other_tenant(session_factory)
    other_token = _token(
        client, email=other_email, password=other_password, tenant_slug="other-team-assign"
    )
    other_team = client.post(
        "/teams",
        headers={"Authorization": f"Bearer {other_token}"},
        json={"name": "Foreign Team", "members": []},
    ).json()

    h = _auth(client)
    ws = _workspace_id(client, h)
    cid = _seed_contact(session_factory, ws)
    res = client.patch(
        f"/omnichannel/contacts/{cid}", headers=h, json={"assignedTeamId": other_team["id"]}
    )
    assert res.status_code == 422, res.text


# ── AC-TEM-20/21: round_robin + persisted cursor ─────────────────────────────
def test_round_robin_rotation_persists_across_fresh_sessions(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    ua = _user(session_factory, "ua@foundryx.io")
    ub = _user(session_factory, "ub@foundryx.io")
    uc = _user(session_factory, "uc@foundryx.io")
    for uid in (ua, ub, uc):
        _add_workspace_member(session_factory, ws, uid)
    team = _create_team(client, h, "Rotation Team", member_ids=[ua, ub, uc])

    picked = []
    for _ in range(4):
        cid = _seed_contact(session_factory, ws)
        # A FRESH client/db round-trip each time - the cursor is read from
        # the persisted row, never an in-process cache (AC-TEM-21).
        res = client.patch(
            f"/omnichannel/contacts/{cid}", headers=h, json={"assignedTeamId": team["id"]}
        )
        assert res.status_code == 200, res.text
        picked.append(res.json()["assignedUserId"])

    ordered = sorted([ua, ub, uc])
    assert picked == [ordered[0], ordered[1], ordered[2], ordered[0]]


def test_round_robin_settings_row_survives_a_fresh_service_instance(client, session_factory):
    """A brand-new `ConversationService`/db session picks up the persisted
    cursor - proves the rotation is DB-backed, not held in Python state."""
    from modules.omnichannel.services import team_assignment_service

    h = _auth(client)
    ws = _workspace_id(client, h)
    ua = _user(session_factory, "ra@foundryx.io")
    ub = _user(session_factory, "rb@foundryx.io")
    for uid in (ua, ub):
        _add_workspace_member(session_factory, ws, uid)
    team = _create_team(client, h, "Fresh Instance Team", member_ids=[ua, ub])

    ordered = sorted([ua, ub])
    db1 = session_factory()
    first = team_assignment_service.pick(db1, DEFAULT_TENANT_ID, ws, team["id"])
    db1.commit()
    db1.close()
    assert first == ordered[0]

    db2 = session_factory()
    second = team_assignment_service.pick(db2, DEFAULT_TENANT_ID, ws, team["id"])
    db2.commit()
    db2.close()
    assert second == ordered[1]

    db3 = session_factory()
    third = team_assignment_service.pick(db3, DEFAULT_TENANT_ID, ws, team["id"])
    db3.commit()
    db3.close()
    assert third == ordered[0]


# ── AC-TEM-22: least_open ────────────────────────────────────────────────────
def test_least_open_picks_fewest_open_threads_in_workspace(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    ua = _user(session_factory, "la@foundryx.io")
    ub = _user(session_factory, "lb@foundryx.io")
    for uid in (ua, ub):
        _add_workspace_member(session_factory, ws, uid)
    team = _create_team(client, h, "Least Open Team", member_ids=[ua, ub])
    client.put(
        f"/omnichannel/workspaces/{ws}/team-settings/{team['id']}",
        headers=h,
        json={"strategy": "least_open"},
    )

    ordered = sorted([ua, ub])
    # ordered[0] already has 2 OPEN threads, ordered[1] has 0 SNOOZED-only
    # (excluded from the count) - ordered[1] must win despite sort order.
    _seed_contact(session_factory, ws, assigned_user_id=ordered[0], status_key="OPEN")
    _seed_contact(session_factory, ws, assigned_user_id=ordered[0], status_key="OPEN")
    _seed_contact(session_factory, ws, assigned_user_id=ordered[1], status_key="SNOOZED")

    cid = _seed_contact(session_factory, ws)
    res = client.patch(
        f"/omnichannel/contacts/{cid}", headers=h, json={"assignedTeamId": team["id"]}
    )
    assert res.status_code == 200, res.text
    assert res.json()["assignedUserId"] == ordered[1]


def test_least_open_ties_break_by_deterministic_order(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    ua = _user(session_factory, "ta@foundryx.io")
    ub = _user(session_factory, "tb@foundryx.io")
    for uid in (ua, ub):
        _add_workspace_member(session_factory, ws, uid)
    team = _create_team(client, h, "Tie Break Team", member_ids=[ua, ub])
    client.put(
        f"/omnichannel/workspaces/{ws}/team-settings/{team['id']}",
        headers=h,
        json={"strategy": "least_open"},
    )
    ordered = sorted([ua, ub])

    cid = _seed_contact(session_factory, ws)
    res = client.patch(
        f"/omnichannel/contacts/{cid}", headers=h, json={"assignedTeamId": team["id"]}
    )
    assert res.json()["assignedUserId"] == ordered[0]


# ── AC-TEM-23: eligibility filtering ──────────────────────────────────────────
def test_ineligible_members_never_picked(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    not_ws_member = _user(session_factory, "notws@foundryx.io")
    inactive_user = _user(session_factory, "inactive@foundryx.io", active=False)
    _add_workspace_member(session_factory, ws, inactive_user)
    eligible = _user(session_factory, "eligible@foundryx.io")
    _add_workspace_member(session_factory, ws, eligible)
    team = _create_team(
        client, h, "Eligibility Team", member_ids=[not_ws_member, inactive_user, eligible]
    )

    cid = _seed_contact(session_factory, ws)
    res = client.patch(
        f"/omnichannel/contacts/{cid}", headers=h, json={"assignedTeamId": team["id"]}
    )
    assert res.status_code == 200, res.text
    assert res.json()["assignedUserId"] == eligible


def test_trashed_member_never_picked_even_when_status_active(client, session_factory):
    """Review round 1, finding 2 - AC-TEM-23 amended: `User.status == ACTIVE`
    is not enough, a trashed user must be excluded too (a trashed row can
    linger on a team's roster; `TeamService.update` blocks NEW trashed
    additions, but `eligible_members` is the actual enforcement point for
    assignment)."""
    h = _auth(client)
    ws = _workspace_id(client, h)
    trashed = _user(session_factory, "trashedagent@foundryx.io")
    _add_workspace_member(session_factory, ws, trashed)
    eligible = _user(session_factory, "stillEligible@foundryx.io")
    _add_workspace_member(session_factory, ws, eligible)
    team = _create_team(client, h, "Trashed Eligibility Team", member_ids=[trashed, eligible])

    db = session_factory()
    trashed_row = db.query(User).filter(User.id == trashed).first()
    trashed_row.is_trashed = True
    db.commit()
    db.close()

    cid = _seed_contact(session_factory, ws)
    res = client.patch(
        f"/omnichannel/contacts/{cid}", headers=h, json={"assignedTeamId": team["id"]}
    )
    assert res.status_code == 200, res.text
    assert res.json()["assignedUserId"] == eligible


def test_eligible_members_batches_the_workspace_membership_check(client, session_factory):
    """Review round 1, finding 10 - `eligible_members` issues ONE batched
    `WorkspaceMember.user_id.in_(...)` query for the whole roster, not one
    `member_exists` call per member."""
    from modules.omnichannel.services import team_assignment_service

    h = _auth(client)
    ws = _workspace_id(client, h)
    members = [_user(session_factory, f"batchroster{i}@foundryx.io") for i in range(5)]
    for uid in members:
        _add_workspace_member(session_factory, ws, uid)
    team = _create_team(client, h, "Batched Roster Team", member_ids=members)

    db = session_factory()
    engine = session_factory.kw["bind"]
    membership_selects = {"n": 0}

    def _before(conn, cursor, statement, *a):
        if "workspace_members" in statement and statement.lstrip().upper().startswith("SELECT"):
            membership_selects["n"] += 1

    event.listen(engine, "before_cursor_execute", _before)
    try:
        eligible = team_assignment_service.eligible_members(db, DEFAULT_TENANT_ID, ws, team["id"])
    finally:
        event.remove(engine, "before_cursor_execute", _before)
    db.close()

    assert sorted(eligible) == sorted(members)
    # ONE membership query for 5 roster members, not 5.
    assert membership_selects["n"] == 1


# ── AC-TEM-24: empty roster is a SUCCESS ─────────────────────────────────────
def test_empty_roster_team_assigned_user_null(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    team = _create_team(client, h, "Empty Roster Team", member_ids=[])
    cid = _seed_contact(session_factory, ws)
    res = client.patch(
        f"/omnichannel/contacts/{cid}", headers=h, json={"assignedTeamId": team["id"]}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["assignedTeamId"] == team["id"]
    assert body["assignedUserId"] is None

    # It shows up in that team's Unassigned queue.
    listed = client.get(
        "/omnichannel/contacts",
        headers=h,
        params={"teamId": team["id"], "assignee": "unassigned"},
    ).json()
    assert any(t["id"] == cid for t in listed["data"])


# ── AC-TEM-25/26: the four assignee combinations ─────────────────────────────
def test_team_plus_user_requires_membership(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    member = _user(session_factory, "member@foundryx.io")
    outsider = _user(session_factory, "outsider@foundryx.io")
    for uid in (member, outsider):
        _add_workspace_member(session_factory, ws, uid)
    team = _create_team(client, h, "Membership Team", member_ids=[member])
    cid = _seed_contact(session_factory, ws)

    # Non-member explicit user -> 422 fieldErrors.assignedUserId.
    res = client.patch(
        f"/omnichannel/contacts/{cid}",
        headers=h,
        json={"assignedTeamId": team["id"], "assignedUserId": outsider},
    )
    assert res.status_code == 422, res.text
    assert "assignedUserId" in res.json()["detail"]["fieldErrors"]

    # A member explicitly named wins over the strategy, cursor untouched.
    res = client.patch(
        f"/omnichannel/contacts/{cid}",
        headers=h,
        json={"assignedTeamId": team["id"], "assignedUserId": member},
    )
    assert res.status_code == 200, res.text
    assert res.json()["assignedUserId"] == member
    assert res.json()["assignedTeamId"] == team["id"]


def test_team_null_user_sets_team_unassigned(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    member = _user(session_factory, "u1@foundryx.io")
    _add_workspace_member(session_factory, ws, member)
    team = _create_team(client, h, "Team Unassigned Team", member_ids=[member])
    cid = _seed_contact(session_factory, ws)

    res = client.patch(
        f"/omnichannel/contacts/{cid}",
        headers=h,
        json={"assignedTeamId": team["id"], "assignedUserId": None},
    )
    assert res.status_code == 200, res.text
    assert res.json()["assignedTeamId"] == team["id"]
    assert res.json()["assignedUserId"] is None


def test_null_team_clears_team_keeps_user(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    member = _user(session_factory, "u2@foundryx.io")
    _add_workspace_member(session_factory, ws, member)
    team = _create_team(client, h, "Clear Team", member_ids=[member])
    cid = _seed_contact(session_factory, ws, assigned_user_id=member, assigned_team_id=team["id"])

    res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"assignedTeamId": None})
    assert res.status_code == 200, res.text
    assert res.json()["assignedTeamId"] is None
    assert res.json()["assignedUserId"] == member


def test_null_user_omitted_team_keeps_team(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    member = _user(session_factory, "u3@foundryx.io")
    _add_workspace_member(session_factory, ws, member)
    team = _create_team(client, h, "Keep Team", member_ids=[member])
    cid = _seed_contact(session_factory, ws, assigned_user_id=member, assigned_team_id=team["id"])

    res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"assignedUserId": None})
    assert res.status_code == 200, res.text
    assert res.json()["assignedUserId"] is None
    assert res.json()["assignedTeamId"] == team["id"]


def test_user_only_not_member_of_current_team_clears_team(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    member = _user(session_factory, "u4@foundryx.io")
    other_user = _user(session_factory, "u5@foundryx.io")
    for uid in (member, other_user):
        _add_workspace_member(session_factory, ws, uid)
    team = _create_team(client, h, "Was Team", member_ids=[member])
    cid = _seed_contact(session_factory, ws, assigned_user_id=member, assigned_team_id=team["id"])

    res = client.patch(
        f"/omnichannel/contacts/{cid}", headers=h, json={"assignedUserId": other_user}
    )
    assert res.status_code == 200, res.text
    assert res.json()["assignedUserId"] == other_user
    assert res.json()["assignedTeamId"] is None


def test_user_only_still_member_of_current_team_keeps_team(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    m1 = _user(session_factory, "u6@foundryx.io")
    m2 = _user(session_factory, "u7@foundryx.io")
    for uid in (m1, m2):
        _add_workspace_member(session_factory, ws, uid)
    team = _create_team(client, h, "Stays Team", member_ids=[m1, m2])
    cid = _seed_contact(session_factory, ws, assigned_user_id=m1, assigned_team_id=team["id"])

    res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"assignedUserId": m2})
    assert res.status_code == 200, res.text
    assert res.json()["assignedUserId"] == m2
    assert res.json()["assignedTeamId"] == team["id"]


# ── AC-TEM-27: embed native-only ─────────────────────────────────────────────
def test_embed_principal_cannot_send_team(client, session_factory):
    from tests.test_omnichannel_embed import _assertion, _bearer, _exchange, _make_connection
    from tests.test_omnichannel_embed import _seed_contact as _embed_seed_contact
    from tests.test_omnichannel_embed import _workspace_id as _embed_workspace_id

    cid_conn = _make_connection(session_factory)
    wid = _embed_workspace_id(session_factory)
    contact_id = _embed_seed_contact(session_factory, workspace_id=wid)
    token = _exchange(client, _assertion(iss=cid_conn, workspace_id=wid)).json()["accessToken"]

    res = client.patch(
        f"/omnichannel/contacts/{contact_id}",
        json={"assignedTeamId": "whatever"},
        headers=_bearer(token),
    )
    assert res.status_code == 403, res.text
    # The existing external-agent assign path is unaffected.
    res2 = client.patch(
        f"/omnichannel/contacts/{contact_id}",
        json={"assignedUserId": None},
        headers=_bearer(token),
    )
    assert res2.status_code == 200, res2.text


# ── AC-TEM-28: team-settings CRUD + gates ────────────────────────────────────
def test_team_settings_crud_and_gates(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    team = _create_team(client, h, "Settings Team")

    # Review round 1, finding 4/5/6: the list is now every ACTIVE core team
    # (not just previously-configured rows) - a never-configured team
    # defaults to round_robin/isConfigured false.
    listed = client.get(f"/omnichannel/workspaces/{ws}/team-settings", headers=h).json()
    assert len(listed) == 1
    assert listed[0]["teamId"] == team["id"]
    assert listed[0]["strategy"] == "round_robin"
    assert listed[0]["isConfigured"] is False
    assert listed[0]["updatedAt"] is None

    # Unknown strategy -> 422.
    res = client.put(
        f"/omnichannel/workspaces/{ws}/team-settings/{team['id']}",
        headers=h,
        json={"strategy": "random"},
    )
    assert res.status_code == 422, res.text

    # Unknown team id -> 404.
    res = client.put(
        f"/omnichannel/workspaces/{ws}/team-settings/does-not-exist",
        headers=h,
        json={"strategy": "least_open"},
    )
    assert res.status_code == 404, res.text

    res = client.put(
        f"/omnichannel/workspaces/{ws}/team-settings/{team['id']}",
        headers=h,
        json={"strategy": "least_open"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["strategy"] == "least_open"
    assert res.json()["teamName"] == "Settings Team"

    listed = client.get(f"/omnichannel/workspaces/{ws}/team-settings", headers=h).json()
    assert len(listed) == 1
    assert listed[0]["teamId"] == team["id"]
    assert listed[0]["strategy"] == "least_open"
    assert listed[0]["isConfigured"] is True
    assert listed[0]["updatedAt"] is not None

    # Read gate: conversations.read; write gate: conversations.assign - NOT
    # `teams.read` (finding 4/5/6 - a reader without `teams.read` still sees
    # the full active roster).
    reader = _grant_only(
        client, session_factory, "reader@foundryx.io", keys=["conversations.read"]
    )
    reader_res = client.get(f"/omnichannel/workspaces/{ws}/team-settings", headers=reader)
    assert reader_res.status_code == 200
    # Review round 2, N7: the reader's BODY carries the team row (not just a
    # 200 with an empty list) - `least_open` as configured above.
    reader_rows = {r["teamId"]: r for r in reader_res.json()}
    assert team["id"] in reader_rows
    assert reader_rows[team["id"]]["teamName"] == "Settings Team"
    assert reader_rows[team["id"]]["strategy"] == "least_open"
    assert reader_rows[team["id"]]["isConfigured"] is True
    res = client.put(
        f"/omnichannel/workspaces/{ws}/team-settings/{team['id']}",
        headers=reader,
        json={"strategy": "round_robin"},
    )
    assert res.status_code == 403, res.text

    no_perm = _grant_only(client, session_factory, "noperm@foundryx.io", keys=[])
    assert client.get(f"/omnichannel/workspaces/{ws}/team-settings", headers=no_perm).status_code == 403


# ── AC-TEM-29: ThreadItem team fields, batched resolution ────────────────────
def test_thread_item_team_fields_batched(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    member = _user(session_factory, "batch@foundryx.io")
    _add_workspace_member(session_factory, ws, member)
    team = _create_team(client, h, "Batch Team", member_ids=[member])
    for _ in range(8):
        _seed_contact(session_factory, ws, assigned_team_id=team["id"])
    # A stale/foreign team id renders a null name, never crashes.
    _seed_contact(session_factory, ws, assigned_team_id="ghost-team-id")

    engine = session_factory.kw["bind"]
    selects = {"n": 0}

    def _before(conn, cursor, statement, *a):
        if statement.lstrip().upper().startswith("SELECT"):
            selects["n"] += 1

    event.listen(engine, "before_cursor_execute", _before)
    try:
        res = client.get("/omnichannel/contacts", headers=h)
    finally:
        event.remove(engine, "before_cursor_execute", _before)

    assert res.status_code == 200
    body = res.json()["data"]
    named = [t for t in body if t["assignedTeamId"] == team["id"]]
    assert len(named) == 8
    assert all(t["assignedTeamName"] == "Batch Team" for t in named)
    ghost = next(t for t in body if t["assignedTeamId"] == "ghost-team-id")
    assert ghost["assignedTeamName"] is None
    # ONE `teams.list@1` call resolves every row's name, not one-per-row.
    assert selects["n"] <= 25, f"expected batched resolution, got {selects['n']} SELECTs"


# ── AC-TEM-30: teamId list filter ─────────────────────────────────────────────
def test_team_id_list_filter(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    team_a = _create_team(client, h, "Filter Team A")
    team_b = _create_team(client, h, "Filter Team B")
    a1 = _seed_contact(session_factory, ws, assigned_team_id=team_a["id"])
    a2 = _seed_contact(session_factory, ws, assigned_team_id=team_a["id"])
    _seed_contact(session_factory, ws, assigned_team_id=team_b["id"])

    res = client.get("/omnichannel/contacts", headers=h, params={"teamId": team_a["id"]})
    assert res.status_code == 200
    ids = {t["id"] for t in res.json()["data"]}
    assert ids == {a1, a2}

    # Unknown/foreign team id -> empty page, never 404.
    res = client.get("/omnichannel/contacts", headers=h, params={"teamId": "nope"})
    assert res.status_code == 200
    assert res.json()["data"] == []
    assert res.json()["total"] == 0


# ── AC-TEM-31: event payload ──────────────────────────────────────────────────
def test_assignment_event_payload_carries_team(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    member = _user(session_factory, "ev@foundryx.io")
    _add_workspace_member(session_factory, ws, member)
    team = _create_team(client, h, "Event Team", member_ids=[member])
    cid = _seed_contact(session_factory, ws)

    res = client.patch(
        f"/omnichannel/contacts/{cid}", headers=h, json={"assignedTeamId": team["id"]}
    )
    assert res.status_code == 200

    events = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["data"]
    assigned = next(e for e in events if e["eventType"] == "assigned")
    assert assigned["payload"]["teamId"] == team["id"]
    assert assigned["payload"]["teamName"] == "Event Team"
    assert assigned["payload"]["assignedVia"] == "team_strategy"
    assert assigned["payload"]["change"] == "both"

    before = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["total"]
    # Re-sending the SAME team + assignee writes nothing.
    picked_user = res.json()["assignedUserId"]
    res2 = client.patch(
        f"/omnichannel/contacts/{cid}",
        headers=h,
        json={"assignedTeamId": team["id"], "assignedUserId": picked_user},
    )
    assert res2.status_code == 200
    after = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["total"]
    assert after == before

    # Losing BOTH (explicit null on both sides) -> unassigned.
    client.patch(
        f"/omnichannel/contacts/{cid}",
        headers=h,
        json={"assignedTeamId": None, "assignedUserId": None},
    )
    events = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["data"]
    unassigned = next(e for e in events if e["eventType"] == "unassigned")
    assert unassigned["payload"]["teamId"] is None


def test_assignment_event_manual_via_carries_assigneekind(client, session_factory):
    """Backward compat with the plan-27 AC-IVE-06 test - a plain user assign
    with no team involved still carries `assigneeKind: "user"`."""
    h = _auth(client)
    ws = _workspace_id(client, h)
    db = session_factory()
    admin_id = db.query(User).filter(User.email == ACTIVE_EMAIL).first().id
    db.close()
    cid = _seed_contact(session_factory, ws)

    res = client.patch(
        f"/omnichannel/contacts/{cid}", headers=h, json={"assignedUserId": admin_id}
    )
    assert res.status_code == 200
    events = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["data"]
    assigned = next(e for e in events if e["eventType"] == "assigned")
    assert assigned["payload"]["assigneeKind"] == "user"
    assert assigned["payload"]["assignedVia"] == "manual"
    assert assigned["payload"]["change"] == "user"


# ── AC-TEM-15 (module half): capability-absent degrade ───────────────────────
def test_capability_absent_degrades_never_500s(client, session_factory, monkeypatch):
    from modules.omnichannel.models import Contact
    from modules.omnichannel.services import team_directory

    h = _auth(client)
    ws = _workspace_id(client, h)
    team = _create_team(client, h, "Vanishing Team")
    cid = _seed_contact(session_factory, ws)

    # A thread already carrying a team id (set before the capability
    # disappeared) still round-trips its id with a NULL name - never a 500.
    stale_cid = _seed_contact(session_factory, ws, assigned_team_id=team["id"])

    monkeypatch.setattr(team_directory, "resolve_capability", lambda *a, **k: None)
    monkeypatch.setattr(team_directory, "resolve_soft_ref", lambda *a, **k: None)

    res = client.patch(
        f"/omnichannel/contacts/{cid}", headers=h, json={"assignedTeamId": team["id"]}
    )
    assert res.status_code == 422, res.text

    res = client.get(f"/omnichannel/contacts/{stale_cid}", headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["assignedTeamId"] == team["id"]
    assert res.json()["assignedTeamName"] is None

    db = session_factory()
    c = db.query(Contact).filter(Contact.id == cid).first()
    assert c.assigned_team_id is None
    db.close()


# ── AC-TEM-16: reference guard, exercised through the REAL checker ───────────
def test_core_team_delete_blocked_by_real_conversations_guard(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    team = _create_team(client, h, "Guarded Team")
    cid = _seed_contact(session_factory, ws)

    client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"assignedTeamId": team["id"]})

    res = client.delete(f"/teams/{team['id']}", headers=h)
    assert res.status_code == 409, res.text
    body = res.json()["detail"]
    assert body["error"] == "team_in_use"
    assert body["counts"]["conversations"] == 1

    client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"assignedTeamId": None})
    res = client.delete(f"/teams/{team['id']}", headers=h)
    assert res.status_code == 204, res.text


# ── plan 28 S3: the workflow action `omnichannel.assign_conversation` ────────
# AC-TEM-32..35. `omnichannel_get_contact`/`omnichannel_send_message` are
# unit-tested the SAME way in `test_omnichannel_workflow_triggers.py` (direct
# `(db, tenant_id, config, ctx)` calls) - this action follows the same shape.


def _wf_ctx(workflow_id="wf_1", run_id="run_1") -> dict:
    return {"_workflow.workflowId": workflow_id, "_workflow.runId": run_id}


# ── AC-TEM-32: registration ───────────────────────────────────────────────────
def test_assign_conversation_action_registered_with_fields():
    from app.workflow_engine.registry import get_action

    action = get_action("omnichannel.assign_conversation")
    assert action is not None
    assert action.module == "omnichannel"
    by_key = {f.key: f for f in action.fields}

    assert by_key["contactId"].required and by_key["contactId"].mergeable
    assert by_key["mode"].required
    assert {o["value"] for o in by_key["mode"].options} == {"user", "team", "unassign"}

    assert by_key["userId"].show_when == ("mode", "user")
    assert by_key["userId"].mergeable

    assert by_key["teamId"].type == "team"
    assert by_key["teamId"].show_when == ("mode", "team")

    assert by_key["strategy"].show_when == ("mode", "team")
    assert not by_key["strategy"].required
    assert {o["value"] for o in by_key["strategy"].options} == {
        "default",
        "round_robin",
        "least_open",
    }

    output_keys = {o.key for o in action.outputs}
    assert {"assignedUserId", "assignedTeamId", "assigned"} <= output_keys


# ── AC-TEM-33: module-inactive + cross-tenant rejection ──────────────────────
def test_assign_conversation_module_inactive_rejected(session_factory):
    from app.services.app_store_service import AppStoreService
    from modules.omnichannel.services.workflow_actions import (
        ActionError,
        omnichannel_assign_conversation,
    )

    db = session_factory()
    try:
        ws = db.query(__import__("modules.omnichannel.models", fromlist=["Workspace"]).Workspace).first()
        cid = _seed_contact(session_factory, ws.id)
        AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "omnichannel")
        with pytest.raises(ActionError, match="not active"):
            omnichannel_assign_conversation(
                db, DEFAULT_TENANT_ID, {"contactId": cid, "mode": "unassign"}, _wf_ctx()
            )
    finally:
        db.close()


def test_assign_conversation_cross_tenant_rejected(session_factory):
    from modules.omnichannel.services.workflow_actions import (
        ActionError,
        omnichannel_assign_conversation,
    )

    db = session_factory()
    ws = db.query(__import__("modules.omnichannel.models", fromlist=["Workspace"]).Workspace).first()
    cid = _seed_contact(session_factory, ws.id)
    db.close()

    db2 = session_factory()
    try:
        with pytest.raises(ActionError):
            omnichannel_assign_conversation(
                db2, "some-other-tenant", {"contactId": cid, "mode": "unassign"}, _wf_ctx()
            )
    finally:
        db2.close()


# ── mode=user / mode=team / mode=unassign, assigned_via=workflow attribution ─
def test_assign_conversation_mode_user_sets_assignee_and_workflow_attribution(
    client, session_factory
):
    from modules.omnichannel.services.workflow_actions import omnichannel_assign_conversation

    h = _auth(client)
    ws = _workspace_id(client, h)
    member = _user(session_factory, "wf-user@foundryx.io")
    cid = _seed_contact(session_factory, ws)

    db = session_factory()
    try:
        out = omnichannel_assign_conversation(
            db,
            DEFAULT_TENANT_ID,
            {"contactId": cid, "mode": "user", "userId": member},
            _wf_ctx(workflow_id="wf_42", run_id="run_99"),
        )
        db.commit()
    finally:
        db.close()

    assert out == {"assignedUserId": member, "assignedTeamId": None, "assigned": True}

    events = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["data"]
    assigned = next(e for e in events if e["eventType"] == "assigned")
    assert assigned["payload"]["assignedVia"] == "workflow"
    assert assigned["payload"]["workflowId"] == "wf_42"
    assert assigned["payload"]["runId"] == "run_99"
    assert assigned["actorUserId"] is None  # D-A8 pinned: no human actor


def test_assign_conversation_mode_user_unknown_user_is_action_error(session_factory):
    from modules.omnichannel.services.workflow_actions import (
        ActionError,
        omnichannel_assign_conversation,
    )
    from modules.omnichannel.models import Workspace

    db = session_factory()
    try:
        ws = db.query(Workspace).first()
        cid = _seed_contact(session_factory, ws.id)
        with pytest.raises(ActionError) as exc:
            omnichannel_assign_conversation(
                db, DEFAULT_TENANT_ID, {"contactId": cid, "mode": "user", "userId": "nope"}, _wf_ctx()
            )
        # D-A8-5 pinned wording - no raw id embedded in the message.
        assert "nope" not in str(exc.value)
    finally:
        db.close()


# ── AC-TEM-35: team mode, no eligible member -> SUCCESS, assigned=false ─────
def test_assign_conversation_mode_team_no_eligible_member_succeeds(client, session_factory):
    from modules.omnichannel.services.workflow_actions import omnichannel_assign_conversation

    h = _auth(client)
    ws = _workspace_id(client, h)
    team = _create_team(client, h, "Empty Roster Team")  # no members
    cid = _seed_contact(session_factory, ws)

    db = session_factory()
    try:
        out = omnichannel_assign_conversation(
            db,
            DEFAULT_TENANT_ID,
            {"contactId": cid, "mode": "team", "teamId": team["id"]},
            _wf_ctx(),
        )
        db.commit()
    finally:
        db.close()

    assert out["assigned"] is False
    assert out["assignedTeamId"] == team["id"]
    assert out["assignedUserId"] is None

    thread = client.get(f"/omnichannel/contacts/{cid}", headers=h).json()
    assert thread["assignedTeamId"] == team["id"]
    assert thread["assignedUserId"] is None


def test_assign_conversation_mode_team_picks_eligible_member_with_strategy_override(
    client, session_factory
):
    from modules.omnichannel.services.workflow_actions import omnichannel_assign_conversation

    h = _auth(client)
    ws = _workspace_id(client, h)
    m1 = _user(session_factory, "wf-team-a@foundryx.io")
    m2 = _user(session_factory, "wf-team-b@foundryx.io")
    _add_workspace_member(session_factory, ws, m1)
    _add_workspace_member(session_factory, ws, m2)
    team = _create_team(client, h, "Strategy Team", member_ids=[m1, m2])
    cid = _seed_contact(session_factory, ws)

    db = session_factory()
    try:
        out = omnichannel_assign_conversation(
            db,
            DEFAULT_TENANT_ID,
            {
                "contactId": cid,
                "mode": "team",
                "teamId": team["id"],
                "strategy": "round_robin",
            },
            _wf_ctx(),
        )
        db.commit()
    finally:
        db.close()

    assert out["assigned"] is True
    assert out["assignedTeamId"] == team["id"]
    assert out["assignedUserId"] in {m1, m2}


def test_assign_conversation_foreign_team_is_action_error(session_factory):
    from modules.omnichannel.services.workflow_actions import (
        ActionError,
        omnichannel_assign_conversation,
    )
    from modules.omnichannel.models import Workspace

    db = session_factory()
    try:
        ws = db.query(Workspace).first()
        cid = _seed_contact(session_factory, ws.id)
        with pytest.raises(ActionError) as exc:
            omnichannel_assign_conversation(
                db,
                DEFAULT_TENANT_ID,
                {"contactId": cid, "mode": "team", "teamId": "does-not-exist"},
                _wf_ctx(),
            )
        assert "does-not-exist" not in str(exc.value)
    finally:
        db.close()


def test_assign_conversation_mode_unassign_clears_both(client, session_factory):
    from modules.omnichannel.services.workflow_actions import omnichannel_assign_conversation

    h = _auth(client)
    ws = _workspace_id(client, h)
    member = _user(session_factory, "wf-unassign@foundryx.io")
    cid = _seed_contact(session_factory, ws, assigned_user_id=member)

    db = session_factory()
    try:
        out = omnichannel_assign_conversation(
            db, DEFAULT_TENANT_ID, {"contactId": cid, "mode": "unassign"}, _wf_ctx()
        )
        db.commit()
    finally:
        db.close()

    assert out == {"assignedUserId": None, "assignedTeamId": None, "assigned": False}

    events = client.get(f"/omnichannel/contacts/{cid}/events", headers=h).json()["data"]
    unassigned = next(e for e in events if e["eventType"] == "unassigned")
    assert unassigned["payload"]["assignedVia"] == "workflow"
