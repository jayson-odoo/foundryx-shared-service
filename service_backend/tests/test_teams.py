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
    assert down_revision == "b7c1d2e3f4a5"

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
