"""Core Teams tests (plan 28 S1, roadmap A8) - AC-TEM-01..17 + the S1 share of
AC-TEM-49.

CRUD + ci-unique name + member validation rollback + member tenant_id
derivation, delete 204/409 via the reference guard (fake checker), mine
without teams.read, tenant isolation, permission 403 matrix + implied-read,
migration id/parent sanity, capability resolution (API boot AND
boot_module_hooks), foreign-tenant capability calls returning None, the
capability-absent degrade path, and the terminology key.
"""
import re

from sqlalchemy.sql import func

from app.models import DEFAULT_TENANT_ID, Role, User, UserStatus
from app.models.tenant import PLATFORM_TENANT_ID
from app.module_platform import register_reference_guard, resolve_capability
from app.security import hash_password
from app.services.team_capabilities import ensure_team_capabilities
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD, tenant_slug=None) -> str:
    payload = {"email": email, "password": password}
    if tenant_slug:
        payload["tenantSlug"] = tenant_slug
    res = client.post("/auth/login", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _user(session_factory, email, *, tenant_id=DEFAULT_TENANT_ID, role_names=None, password="pw12345678"):
    db = session_factory()
    user = User(
        tenant_id=tenant_id,
        email=email,
        password=hash_password(password),
        name=email.split("@")[0],
        status=UserStatus.ACTIVE.value,
        email_verified_at=func.now(),
    )
    if role_names:
        roles = db.query(Role).filter(Role.tenant_id == tenant_id, Role.name.in_(role_names)).all()
        user.roles = roles
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    return user.id


def _no_perm_user(session_factory, email="noperm@foundryx.io", password="pw12345678"):
    _user(session_factory, email, role_names=[])
    return email, password


def _grant_only(client, session_factory, email, password, *, keys):
    """A fresh user whose ONLY role holds exactly `keys` (implied-read applied
    server-side by RoleService, exactly like every other resource)."""
    admin = _auth(client)
    role = client.post(
        "/roles", headers=admin, json={"name": f"Custom {email}", "permissionKeys": keys}
    ).json()
    uid = _user(session_factory, email, role_names=[], password=password)
    db = session_factory()
    user = db.query(User).filter(User.id == uid).first()
    role_row = db.query(Role).filter(Role.id == role["id"]).first()
    user.roles = [role_row]
    db.add(user)
    db.commit()
    db.close()
    return {"Authorization": f"Bearer {_token(client, email=email, password=password)}"}


# ── CRUD + validation ────────────────────────────────────────────────────────


def test_create_list_get_team_with_members(client, session_factory):
    h = _auth(client)
    demo = client.get("/auth/me", headers=h).json()
    lead_id = _user(session_factory, "lead1@foundryx.io")
    member_id = _user(session_factory, "member1@foundryx.io")

    created = client.post(
        "/teams",
        headers=h,
        json={
            "name": "Support",
            "description": "Post-sale support",
            "members": [
                {"userId": lead_id, "role": "lead"},
                {"userId": member_id, "role": "member"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Support"
    assert body["memberCount"] == 2
    assert body["isActive"] is True
    assert {m["role"] for m in body["members"]} == {"lead", "member"}

    listed = client.get("/teams", headers=h).json()
    assert any(t["name"] == "Support" for t in listed["data"])

    fetched = client.get(f"/teams/{body['id']}", headers=h).json()
    assert fetched["id"] == body["id"]
    assert fetched["memberCount"] == 2

    # team_members.tenant_id is copied from the TEAM, never the payload.
    db = session_factory()
    from app.models.team import TeamMember

    rows = db.query(TeamMember).filter(TeamMember.team_id == body["id"]).all()
    assert rows and all(r.tenant_id == demo["tenantId"] for r in rows)
    db.close()


def test_name_blank_too_long_and_duplicate_ci_rejected(client):
    h = _auth(client)
    assert client.post("/teams", headers=h, json={"name": "  ", "members": []}).status_code == 422
    long_name = "x" * 121
    res = client.post("/teams", headers=h, json={"name": long_name, "members": []})
    assert res.status_code == 422
    assert "name" in res.json()["detail"]["fieldErrors"]

    ok = client.post("/teams", headers=h, json={"name": "Sales", "members": []})
    assert ok.status_code == 201
    dup = client.post("/teams", headers=h, json={"name": "sales", "members": []})
    assert dup.status_code == 422
    assert "name" in dup.json()["detail"]["fieldErrors"]

    # Two tenants may hold the same team name (checked further down too).
    listed = client.get("/teams", headers=h).json()
    assert len([t for t in listed["data"] if t["name"] == "Sales"]) == 1


def test_members_unknown_or_foreign_or_platform_user_rejects_whole_write(
    client, session_factory
):
    h = _auth(client)

    # unknown id
    res = client.post(
        "/teams", headers=h, json={"name": "Ghost", "members": [{"userId": "nope", "role": "member"}]}
    )
    assert res.status_code == 422
    assert "members" in res.json()["detail"]["fieldErrors"]

    # NOTHING written - no partial team
    listed = client.get("/teams?search=Ghost", headers=h).json()
    assert listed["total"] == 0

    # platform-tenant user id (belongs to a different, special tenant)
    platform_admin = (
        session_factory().query(User).filter(User.tenant_id == PLATFORM_TENANT_ID).first()
    )
    assert platform_admin is not None
    res2 = client.post(
        "/teams",
        headers=h,
        json={"name": "Ghost2", "members": [{"userId": platform_admin.id, "role": "member"}]},
    )
    assert res2.status_code == 422
    assert "members" in res2.json()["detail"]["fieldErrors"]


def test_member_role_must_be_member_or_lead(client, session_factory):
    h = _auth(client)
    uid = _user(session_factory, "roletest@foundryx.io")
    res = client.post(
        "/teams", headers=h, json={"name": "BadRole", "members": [{"userId": uid, "role": "owner"}]}
    )
    assert res.status_code == 422
    assert "members" in res.json()["detail"]["fieldErrors"]


def test_duplicate_member_in_payload_rejected(client, session_factory):
    h = _auth(client)
    uid = _user(session_factory, "duptest@foundryx.io")
    res = client.post(
        "/teams",
        headers=h,
        json={
            "name": "DupTeam",
            "members": [
                {"userId": uid, "role": "member"},
                {"userId": uid, "role": "lead"},
            ],
        },
    )
    assert res.status_code == 422
    assert "members" in res.json()["detail"]["fieldErrors"]


def test_update_replaces_membership_set_atomically_and_rolls_back_on_bad_member(
    client, session_factory
):
    h = _auth(client)
    u1 = _user(session_factory, "u1@foundryx.io")
    u2 = _user(session_factory, "u2@foundryx.io")
    team = client.post(
        "/teams",
        headers=h,
        json={"name": "Onboarding", "members": [{"userId": u1, "role": "member"}]},
    ).json()

    updated = client.patch(
        f"/teams/{team['id']}",
        headers=h,
        json={"members": [{"userId": u2, "role": "lead"}]},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["memberCount"] == 1
    assert body["members"][0]["userId"] == u2
    assert body["members"][0]["role"] == "lead"

    # A foreign user id in the new set rolls back the WHOLE patch - the
    # previous (valid) membership stays exactly as it was.
    bad = client.patch(
        f"/teams/{team['id']}", headers=h, json={"members": [{"userId": "ghost-id", "role": "member"}]}
    )
    assert bad.status_code == 422
    unchanged = client.get(f"/teams/{team['id']}", headers=h).json()
    assert unchanged["memberCount"] == 1
    assert unchanged["members"][0]["userId"] == u2


def test_patch_diffs_members_retain_plus_role_change_plus_add_plus_remove(
    client, session_factory
):
    """The bug repro (S5 wire coder): a PATCH that RETAINS an existing
    `(team_id, user_id)` pair used to blind delete-all + insert the whole
    membership set, tripping `uq_team_members_team_user` on the retained
    pair and mis-reporting it as a 422 name collision. One PATCH that keeps
    one member (role changed), adds a new one, and drops a third must 200
    with exactly the final set."""
    h = _auth(client)
    keep = _user(session_factory, "keep@foundryx.io")
    drop = _user(session_factory, "drop@foundryx.io")
    add = _user(session_factory, "add@foundryx.io")

    team = client.post(
        "/teams",
        headers=h,
        json={
            "name": "DiffTeam",
            "members": [
                {"userId": keep, "role": "member"},
                {"userId": drop, "role": "member"},
            ],
        },
    ).json()

    updated = client.patch(
        f"/teams/{team['id']}",
        headers=h,
        json={
            "members": [
                {"userId": keep, "role": "lead"},
                {"userId": add, "role": "member"},
            ]
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["memberCount"] == 2
    by_user = {m["userId"]: m["role"] for m in body["members"]}
    assert by_user == {keep: "lead", add: "member"}
    assert drop not in by_user

    # Persisted, not just returned - re-fetch confirms.
    fetched = client.get(f"/teams/{team['id']}", headers=h).json()
    assert {m["userId"]: m["role"] for m in fetched["members"]} == {keep: "lead", add: "member"}


def test_patch_duplicate_member_in_payload_still_rejects_with_members_field_error(
    client, session_factory
):
    h = _auth(client)
    uid = _user(session_factory, "patchdup@foundryx.io")
    team = client.post(
        "/teams", headers=h, json={"name": "PatchDupTeam", "members": [{"userId": uid, "role": "member"}]}
    ).json()

    res = client.patch(
        f"/teams/{team['id']}",
        headers=h,
        json={
            "members": [
                {"userId": uid, "role": "member"},
                {"userId": uid, "role": "lead"},
            ]
        },
    )
    assert res.status_code == 422
    assert "members" in res.json()["detail"]["fieldErrors"]


def test_patch_name_collision_still_reports_name_field_error(client, session_factory):
    h = _auth(client)
    _user(session_factory, "namecollision@foundryx.io")
    client.post("/teams", headers=h, json={"name": "TakenName", "members": []})
    team = client.post("/teams", headers=h, json={"name": "RenameMe", "members": []}).json()

    res = client.patch(f"/teams/{team['id']}", headers=h, json={"name": "takenname"})
    assert res.status_code == 422
    assert "name" in res.json()["detail"]["fieldErrors"]


def test_is_active_false_still_readable_and_editable(client):
    h = _auth(client)
    team = client.post(
        "/teams", headers=h, json={"name": "Billing", "isActive": False, "members": []}
    ).json()
    assert team["isActive"] is False
    fetched = client.get(f"/teams/{team['id']}", headers=h).json()
    assert fetched["isActive"] is False
    updated = client.patch(f"/teams/{team['id']}", headers=h, json={"isActive": True}).json()
    assert updated["isActive"] is True


# ── list: search / sort / pagination / tenant scope ─────────────────────────


def test_list_search_sort_pagination(client):
    h = _auth(client)
    for i, name in enumerate(["Zeta", "Alpha", "Mid"]):
        client.post("/teams", headers=h, json={"name": name, "sortOrder": i, "members": []})

    res = client.get("/teams?sort_by=name&sort_dir=asc&page_size=200", headers=h).json()
    names = [t["name"] for t in res["data"]]
    assert names.index("Alpha") < names.index("Mid") < names.index("Zeta")

    searched = client.get("/teams?search=Alp", headers=h).json()
    assert all("Alp" in t["name"] for t in searched["data"])

    page0 = client.get("/teams?page=0&page_size=1", headers=h).json()
    assert len(page0["data"]) == 1
    assert page0["total"] >= 3
    assert page0["page"] == 0


# ── review round 1, blocker 1: server-side filter over the whitelisted
# {name, description, isActive} column map ─────────────────────────────────


def _filter_condition(field, operator, value):
    return {"kind": "condition", "field": field, "operator": operator, "value": value}


def test_list_filter_by_name_contains(client):
    import json

    h = _auth(client)
    client.post("/teams", headers=h, json={"name": "FilterAlpha", "members": []})
    client.post("/teams", headers=h, json={"name": "FilterBeta", "members": []})

    tree = {
        "kind": "group",
        "combinator": "and",
        "rules": [_filter_condition("name", "contains", "Alpha")],
    }
    res = client.get(f"/teams?filter={json.dumps(tree)}", headers=h)
    assert res.status_code == 200
    names = [t["name"] for t in res.json()["data"]]
    assert "FilterAlpha" in names
    assert "FilterBeta" not in names


def test_list_filter_by_description_and_is_active(client):
    import json

    h = _auth(client)
    client.post(
        "/teams",
        headers=h,
        json={"name": "FilterDescActive", "description": "billing team", "isActive": True, "members": []},
    )
    client.post(
        "/teams",
        headers=h,
        json={"name": "FilterDescInactive", "description": "billing team", "isActive": False, "members": []},
    )

    desc_tree = {
        "kind": "group",
        "combinator": "and",
        "rules": [_filter_condition("description", "contains", "billing")],
    }
    res = client.get(f"/teams?filter={json.dumps(desc_tree)}", headers=h).json()
    names = {t["name"] for t in res["data"]}
    assert {"FilterDescActive", "FilterDescInactive"} <= names

    active_tree = {
        "kind": "group",
        "combinator": "and",
        "rules": [_filter_condition("isActive", "is_true", None)],
    }
    active_res = client.get(f"/teams?filter={json.dumps(active_tree)}", headers=h).json()
    active_names = {t["name"] for t in active_res["data"]}
    assert "FilterDescActive" in active_names
    assert "FilterDescInactive" not in active_names


def test_list_filter_unknown_field_is_422(client):
    import json

    h = _auth(client)
    tree = {
        "kind": "group",
        "combinator": "and",
        "rules": [_filter_condition("email", "eq", "x")],
    }
    res = client.get(f"/teams?filter={json.dumps(tree)}", headers=h)
    assert res.status_code == 422


def test_list_filter_malformed_json_is_422(client):
    h = _auth(client)
    res = client.get("/teams?filter=not-json", headers=h)
    assert res.status_code == 422


# ── review round 1, blocker 2: a trashed user can never be ADDED as a member
# (`_validate_members` no longer resolves with `include_trashed=True`) ───────


def test_trashed_user_cannot_be_added_as_a_new_member(client, session_factory):
    h = _auth(client)
    uid = _user(session_factory, "trashee@foundryx.io")
    db = session_factory()
    user = db.query(User).filter(User.id == uid).first()
    user.is_trashed = True
    db.commit()
    db.close()

    res = client.post(
        "/teams", headers=h, json={"name": "TrashedMemberTeam", "members": [{"userId": uid, "role": "member"}]}
    )
    assert res.status_code == 422
    assert "members" in res.json()["detail"]["fieldErrors"]


def test_retained_trashed_member_survives_rename_but_new_trashed_add_is_422(client, session_factory):
    """Review round 1 design note (accepted, narrowed): the trashed guard
    applies ONLY to newly added ids. A PATCH that renames a team and
    re-submits its unchanged roster - one member trashed AFTER joining -
    must return 200 (the retained id passes); a PATCH that ADDS a trashed
    user must 422 with `fieldErrors.members`."""
    h = _auth(client)
    keeper = _user(session_factory, "keeper-later-trashed@foundryx.io")
    newcomer = _user(session_factory, "newcomer-trashed@foundryx.io")
    team = client.post(
        "/teams", headers=h, json={"name": "RosterTeam", "members": [{"userId": keeper, "role": "member"}]}
    ).json()
    assert client.get(f"/teams/{team['id']}", headers=h).status_code == 200

    db = session_factory()
    for uid in (keeper, newcomer):
        db.query(User).filter(User.id == uid).first().is_trashed = True
    db.commit()
    db.close()

    # Rename + unchanged roster (keeper now trashed) -> 200, roster intact.
    res = client.patch(
        f"/teams/{team['id']}",
        headers=h,
        json={"name": "RosterTeam Renamed", "members": [{"userId": keeper, "role": "lead"}]},
    )
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "RosterTeam Renamed"
    assert [m["userId"] for m in res.json()["members"]] == [keeper]
    assert res.json()["members"][0]["role"] == "lead"

    # Adding a trashed NEW user -> 422 on members, nothing written.
    res2 = client.patch(
        f"/teams/{team['id']}",
        headers=h,
        json={"members": [{"userId": keeper, "role": "member"}, {"userId": newcomer, "role": "member"}]},
    )
    assert res2.status_code == 422
    assert "members" in res2.json()["detail"]["fieldErrors"]
    after = client.get(f"/teams/{team['id']}", headers=h).json()
    assert [m["userId"] for m in after["members"]] == [keeper]


# ── mine / tenant isolation ──────────────────────────────────────────────────


def test_mine_returns_only_callers_teams_no_teams_read_needed(client, session_factory):
    h = _auth(client)
    me = client.get("/auth/me", headers=h).json()
    team = client.post(
        "/teams", headers=h, json={"name": "MineTeam", "members": [{"userId": me["id"], "role": "member"}]}
    ).json()
    other_team = client.post("/teams", headers=h, json={"name": "NotMine", "members": []}).json()

    mine = client.get("/teams/mine", headers=h).json()
    ids = {t["id"] for t in mine}
    assert team["id"] in ids
    assert other_team["id"] not in ids

    # No `teams.read` required - a user with neither key still sees /mine.
    email, password = _no_perm_user(session_factory, "agent1@foundryx.io")
    db = session_factory()
    user = db.query(User).filter(User.email == email).first()
    user.tenant_id = DEFAULT_TENANT_ID
    db.commit()
    db.close()
    h2 = _auth(client, email=email, password=password)
    assert client.get("/teams/mine", headers=h2).status_code == 200
    assert client.get("/teams", headers=h2).status_code == 403


def test_mine_response_has_no_member_emails(client, session_factory):
    """Review round 1, finding 7 - `/teams/mine` is authenticated-only (no
    `teams.read`), so its member rows must never carry `email` even though
    the admin `GET /teams` shape does."""
    h = _auth(client)
    me = client.get("/auth/me", headers=h).json()
    other = _user(session_factory, "trimmedmate@foundryx.io")
    team = client.post(
        "/teams",
        headers=h,
        json={
            "name": "TrimmedMineTeam",
            "members": [
                {"userId": me["id"], "role": "lead"},
                {"userId": other, "role": "member"},
            ],
        },
    ).json()
    assert any("email" in m for m in team["members"])  # admin shape still has it

    mine = client.get("/teams/mine", headers=h).json()
    mine_team = next(t for t in mine if t["id"] == team["id"])
    assert mine_team["memberCount"] == 2
    assert mine_team["isActive"] is True
    assert "description" not in mine_team
    for m in mine_team["members"]:
        assert "email" not in m
        assert set(m.keys()) == {"userId", "name", "role"}


def _provision_other_tenant(session_factory, slug="other-teams"):
    from app.services.tenant_service import TenantService

    db = session_factory()
    tenant = TenantService(db).provision(
        name="Other Teams",
        slug=slug,
        admin_email=f"admin-{slug}@example.com",
        admin_password="Password123!",
        admin_name="Admin",
    )
    db.commit()
    tenant_id = tenant.id  # read before close - the row expires on commit
    db.close()
    return tenant_id, f"admin-{slug}@example.com", "Password123!"


def test_tenant_isolation_uniform_404(client, session_factory):
    h = _auth(client)
    team = client.post("/teams", headers=h, json={"name": "IsoTeam", "members": []}).json()

    _unused_tenant_id, email, password = _provision_other_tenant(session_factory)
    h2 = _auth(client, email=email, password=password, tenant_slug="other-teams")

    assert client.get(f"/teams/{team['id']}", headers=h2).status_code == 404
    assert client.patch(f"/teams/{team['id']}", headers=h2, json={"name": "Hacked"}).status_code == 404
    assert client.delete(f"/teams/{team['id']}", headers=h2).status_code == 404
    # Never an existence oracle via a different verb either.
    assert client.get("/teams", headers=h2).json()["data"] == [] or all(
        t["id"] != team["id"] for t in client.get("/teams", headers=h2).json()["data"]
    )


# ── permission matrix + implied-read ────────────────────────────────────────


def test_permission_403_matrix(client, session_factory):
    email, password = _no_perm_user(session_factory, "bare@foundryx.io")
    h = _auth(client, email=email, password=password)
    assert client.get("/teams", headers=h).status_code == 403
    assert client.post("/teams", headers=h, json={"name": "X", "members": []}).status_code == 403


def test_teams_manage_alone_implies_teams_read(client, session_factory):
    h = _grant_only(client, session_factory, "manageonly@foundryx.io", "pw12345678", keys=["teams.manage"])
    assert client.get("/teams", headers=h).status_code == 200
    assert client.post("/teams", headers=h, json={"name": "ImpliedRead", "members": []}).status_code == 201


def test_teams_read_only_cannot_write(client, session_factory):
    h = _grant_only(client, session_factory, "readonly@foundryx.io", "pw12345678", keys=["teams.read"])
    assert client.get("/teams", headers=h).status_code == 200
    assert client.post("/teams", headers=h, json={"name": "ReadOnlyTeam", "members": []}).status_code == 403


# ── delete + reference guard ─────────────────────────────────────────────────


def test_delete_succeeds_with_no_guard_registered(client):
    h = _auth(client)
    team = client.post("/teams", headers=h, json={"name": "DeleteMe", "members": []}).json()
    assert client.delete(f"/teams/{team['id']}", headers=h).status_code == 204
    assert client.get(f"/teams/{team['id']}", headers=h).status_code == 404


def test_delete_blocked_by_reference_guard_returns_409_with_counts(client):
    h = _auth(client)
    team = client.post("/teams", headers=h, json={"name": "InUseTeam", "members": []}).json()

    def _fake_checker(db, tenant_id, entity_id):
        return 3 if entity_id == team["id"] else 0

    register_reference_guard("team", "conversations", _fake_checker)
    try:
        res = client.delete(f"/teams/{team['id']}", headers=h)
        assert res.status_code == 409
        body = res.json()["detail"]
        assert body["error"] == "team_in_use"
        assert body["counts"] == {"conversations": 3}
        # Nothing deleted on 409.
        assert client.get(f"/teams/{team['id']}", headers=h).status_code == 200
    finally:
        register_reference_guard("team", "conversations", lambda db, t, i: 0)


def test_broken_reference_guard_never_wedges_the_delete_decision(client):
    h = _auth(client)
    team = client.post("/teams", headers=h, json={"name": "BrokenGuardTeam", "members": []}).json()

    def _broken_checker(db, tenant_id, entity_id):
        raise RuntimeError("boom")

    register_reference_guard("team", "flaky_source", _broken_checker)
    try:
        assert client.delete(f"/teams/{team['id']}", headers=h).status_code == 204
    finally:
        register_reference_guard("team", "flaky_source", lambda db, t, i: 0)


# ── capability seam (AC-TEM-13/14/15) ───────────────────────────────────────


def test_capabilities_registered_and_resolve_tenant_scoped(client, session_factory):
    h = _auth(client)
    demo = client.get("/auth/me", headers=h).json()
    uid = _user(session_factory, "capmember@foundryx.io")
    team = client.post(
        "/teams",
        headers=h,
        json={"name": "CapTeam", "members": [{"userId": uid, "role": "lead"}]},
    ).json()

    db = session_factory()
    resolved = resolve_capability(db, demo["tenantId"], "team.resolve", 1)
    assert resolved is not None
    out = resolved(db, demo["tenantId"], {"id": team["id"]})
    assert out == {"id": team["id"], "name": "CapTeam", "isActive": True}

    members_handler = resolve_capability(db, demo["tenantId"], "teams.members", 1)
    members = members_handler(db, demo["tenantId"], {"id": team["id"]})
    assert members == [{"userId": uid, "role": "lead", "name": "capmember"}]

    of_user_handler = resolve_capability(db, demo["tenantId"], "teams.of_user", 1)
    teams_of_user = of_user_handler(db, demo["tenantId"], {"userId": uid})
    assert any(t["id"] == team["id"] for t in teams_of_user)

    list_handler = resolve_capability(db, demo["tenantId"], "teams.list", 1)
    inactive_team = _make_inactive_team(db, demo["tenantId"])
    all_teams = list_handler(db, demo["tenantId"], {})
    active_only = list_handler(db, demo["tenantId"], {"activeOnly": True})
    assert all(t["isActive"] for t in active_only)
    assert any(t["id"] == inactive_team.id for t in all_teams)
    assert all(t["id"] != inactive_team.id for t in active_only)
    db.close()


def _make_inactive_team(db, tenant_id):
    """Test helper - an inactive team via the service so the capability
    list-filter assertion has something to exclude."""
    from app.services.team_service import TeamService

    return TeamService(db).create(tenant_id, name="InactiveCapTeam", is_active=False, members=[])


def test_foreign_tenant_capability_calls_return_none_never_cross_tenant(
    client, session_factory
):
    h = _auth(client)
    team = client.post("/teams", headers=h, json={"name": "PrivateTeam", "members": []}).json()

    other_tenant_id, _email, _password = _provision_other_tenant(
        session_factory, slug="other-teams-cap"
    )
    db = session_factory()

    resolved = resolve_capability(db, other_tenant_id, "team.resolve", 1)
    assert resolved(db, other_tenant_id, {"id": team["id"]}) is None

    members_handler = resolve_capability(db, other_tenant_id, "teams.members", 1)
    assert members_handler(db, other_tenant_id, {"id": team["id"]}) is None

    # unknown id
    assert resolved(db, other_tenant_id, {"id": "does-not-exist"}) is None
    db.close()


def test_capability_registration_idempotent(client):
    # Calling ensure_team_capabilities() repeatedly (like every boot does)
    # must never raise DuplicateCapability.
    ensure_team_capabilities()
    ensure_team_capabilities()
    ensure_team_capabilities()


def test_capabilities_registered_via_boot_module_hooks(session_factory):
    """AC-TEM-13 - a worker process boots via `boot_module_hooks()` (never
    `load_modules`); the teams capabilities must still land."""
    from app.module_platform.capabilities import _CAPS

    saved = dict(_CAPS)
    try:
        for key in list(_CAPS):
            if key[0] in ("team.resolve", "teams.list", "teams.members", "teams.of_user"):
                del _CAPS[key]
        assert ("team.resolve", 1) not in _CAPS

        from app import module_loader

        module_loader.boot_module_hooks()

        assert ("team.resolve", 1) in _CAPS
        assert ("teams.list", 1) in _CAPS
        assert ("teams.members", 1) in _CAPS
        assert ("teams.of_user", 1) in _CAPS
    finally:
        _CAPS.clear()
        _CAPS.update(saved)


def test_capability_absent_degrades_instead_of_raising(client, session_factory):
    """AC-TEM-15 - simulate a boot path that never registered the teams
    capabilities: resolution returns None (never a 500), the caller degrades."""
    from app.module_platform.capabilities import _CAPS

    saved = dict(_CAPS)
    try:
        for key in list(_CAPS):
            if key[0] in ("team.resolve", "teams.list", "teams.members", "teams.of_user"):
                del _CAPS[key]

        h = _auth(client)
        demo = client.get("/auth/me", headers=h).json()
        db = session_factory()
        assert resolve_capability(db, demo["tenantId"], "team.resolve", 1) is None
        db.close()

        # Core itself (create/list/get/delete) is NOT gated by the capability
        # registry - only a MODULE consuming it would degrade (S2). Prove core
        # still works fine with the registry emptied.
        assert client.post(
            "/teams", headers=h, json={"name": "StillWorks", "members": []}
        ).status_code == 201
    finally:
        _CAPS.clear()
        _CAPS.update(saved)
        ensure_team_capabilities()


# ── terminology ──────────────────────────────────────────────────────────────


def test_terminology_team_key_registered_with_defaults(client):
    h = _auth(client)
    body = client.get("/terminology", headers=h).json()
    assert body["team"] == {"singular": "Team", "plural": "Teams"}


def test_terminology_override_relabels_team(client):
    h = _auth(client)
    res = client.put(
        "/terminology/team", headers=h, json={"singular": "Squad", "plural": "Squads"}
    )
    assert res.status_code == 200
    body = client.get("/terminology", headers=h).json()
    assert body["team"] == {"singular": "Squad", "plural": "Squads"}


# ── grant path (existing tenant + bootstrap sweep) ──────────────────────────


def test_bootstrap_sync_and_sweep_grants_teams_keys_to_existing_admin(session_factory):
    """AC-TEM-11 - a tenant provisioned BEFORE this slice still gets both keys
    once the standard bootstrap (sync_core + sweep_tenant_admin_grants) runs,
    and re-running it is a no-op."""
    from app.services.permission_service import PermissionService
    from app.seed import sweep_tenant_admin_grants

    db = session_factory()
    # Simulate "provisioned before the slice": strip the Admin role's teams
    # grants (as if the CSV/sweep had never run for this tenant).
    admin = db.query(Role).filter(Role.tenant_id == DEFAULT_TENANT_ID, Role.name == "Admin").first()
    admin.permissions = [p for p in admin.permissions if p.resource != "teams"]
    db.commit()
    keys_before = {p.key for p in admin.permissions}
    assert "teams.read" not in keys_before and "teams.manage" not in keys_before

    PermissionService(db).sync_core()
    sweep_tenant_admin_grants(db)
    db.commit()

    db.refresh(admin)
    keys_after = {p.key for p in admin.permissions}
    assert {"teams.read", "teams.manage"} <= keys_after

    # Re-running is a no-op (idempotent).
    PermissionService(db).sync_core()
    sweep_tenant_admin_grants(db)
    db.commit()
    db.refresh(admin)
    assert {"teams.read", "teams.manage"} <= {p.key for p in admin.permissions}
    db.close()


# ── migration sanity ─────────────────────────────────────────────────────────


def test_migration_revision_id_and_parent_and_no_collision():
    import pathlib

    versions_dir = pathlib.Path(__file__).resolve().parent.parent / "alembic" / "versions"
    teams_file = versions_dir / "teams_core_s428_teams_core.py"
    assert teams_file.exists()
    text = teams_file.read_text()

    rev_match = re.search(r'^revision\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    down_match = re.search(r'^down_revision\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    assert rev_match and down_match
    revision = rev_match.group(1)
    down_revision = down_match.group(1)

    assert len(revision) <= 32
    # Re-parented onto main's 82497a2fcea3 at the 215d94cc merge (plan 28 landed after A9/A4).
    assert down_revision == "82497a2fcea3"

    # Collision grep - every OTHER migration file's revision id must differ,
    # including files that spell it `revision: str = "..."`.
    collisions = 0
    for other in versions_dir.glob("*.py"):
        if other == teams_file:
            continue
        other_text = other.read_text()
        for match in re.finditer(r'revision(?:\s*:\s*\w+)?\s*=\s*["\']([^"\']+)["\']', other_text):
            if match.group(1) == revision:
                collisions += 1
    assert collisions == 0

    # Verify it's still the single head reachable from the tip: no OTHER file
    # declares down_revision == "b7c1d2e3f4a5" (else two heads would exist).
    other_children = 0
    for other in versions_dir.glob("*.py"):
        if other == teams_file:
            continue
        other_text = other.read_text()
        for match in re.finditer(r'down_revision(?:\s*:\s*[\w\[\], ."]+)?\s*=\s*["\']([^"\']+)["\']', other_text):
            if match.group(1) == "b7c1d2e3f4a5":
                other_children += 1
    assert other_children == 0


# ── AC-TEM-34: GET /workflows/metadata exposes `teams` ───────────────────────
# The generic `NodeField(type="team")` option-provider seam (plan 28 S3,
# `registry.register_option_provider`) - registered by `team_capabilities.py`,
# resolved by `WorkflowService._team_options`, gated by `teams.read` in the
# router. Never another tenant's teams, never a 500 without the capability.


def test_workflow_service_metadata_includes_teams_when_requested(client, session_factory):
    from app.services.workflow_service import WorkflowService

    h = _auth(client)
    created = client.post(
        "/teams", headers=h, json={"name": "Metadata Team", "members": []}
    )
    assert created.status_code == 201, created.text
    team = created.json()

    db = session_factory()
    meta = WorkflowService(db).metadata(DEFAULT_TENANT_ID, include_teams=True)
    db.close()

    assert {"id": team["id"], "name": "Metadata Team"} in meta["teams"]


def test_workflow_service_metadata_teams_empty_when_not_requested(client, session_factory):
    from app.services.workflow_service import WorkflowService

    h = _auth(client)
    client.post("/teams", headers=h, json={"name": "Hidden Team", "members": []})

    db = session_factory()
    meta = WorkflowService(db).metadata(DEFAULT_TENANT_ID, include_teams=False)
    db.close()

    assert meta["teams"] == []


def test_workflow_metadata_endpoint_gates_teams_on_permission(client, session_factory):
    h = _auth(client)
    created = client.post(
        "/teams", headers=h, json={"name": "Endpoint Team", "members": []}
    )
    assert created.status_code == 201, created.text

    # workflows.read alone (no teams.read) - the editor still loads, the
    # picker is just empty (AC-TEM-34 - never a 403, never a peek at names).
    limited = _grant_only(
        client, session_factory, "wf-no-teams@foundryx.io", "pw12345678", keys=["workflows.read"]
    )
    res = client.get("/workflows/metadata", headers=limited)
    assert res.status_code == 200, res.text
    assert res.json()["teams"] == []

    full = _grant_only(
        client,
        session_factory,
        "wf-with-teams@foundryx.io",
        "pw12345678",
        keys=["workflows.read", "teams.read"],
    )
    res2 = client.get("/workflows/metadata", headers=full)
    assert res2.status_code == 200, res2.text
    assert any(t["name"] == "Endpoint Team" for t in res2.json()["teams"])


def test_workflow_metadata_teams_tenant_scoped(client, session_factory):
    """A caller never sees another tenant's teams via the metadata picker -
    mirrors `test_workflow_metadata_ai_agents_is_tenant_scoped`."""
    from app.services.workflow_service import WorkflowService

    h = _auth(client)
    client.post("/teams", headers=h, json={"name": "Own Team", "members": []})

    other_tenant_id, _, _ = _provision_other_tenant(session_factory, slug="other-metadata-teams")

    db = session_factory()
    meta = WorkflowService(db).metadata(other_tenant_id, include_teams=True)
    db.close()

    assert meta["teams"] == []
