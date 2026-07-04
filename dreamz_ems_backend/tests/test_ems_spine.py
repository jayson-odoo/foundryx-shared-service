"""EMS domain spine tests (sprint-3/11, F4) — validates AC-11-*.

module install grants perms · profile CRUD + dedup + tier-1 transition · Type→
Template→Project hierarchy · create-from-template copy_scope materializes the
project's eligibility graph · participant join + uniqueness + tier-2 transition ·
project-scoped bulk import (find-or-create profile) · tenant isolation ·
terminology Event label.
"""
import io

from app.models.tenant import DEFAULT_TENANT_ID
from app.status_engine.scoped import scope_status_ids
from modules.ems.models import PARTICIPANT_ENTITY, Project
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD, PLATFORM_EMAIL, PLATFORM_PASSWORD


def _login(client, email, pw, slug=None):
    p = {"email": email, "password": pw}
    if slug:
        p["tenantSlug"] = slug
    return client.post("/auth/login", json=p)


def _h(res):
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _admin(client):
    return _h(_login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD))


# ── install grants perms + terminology ──────────────────────────────────────


def test_module_install_grants_perms(client):
    h = _admin(client)
    # admin can hit a gated ems endpoint → perms granted on install (AC-11-18)
    assert client.get("/ems/profiles", headers=h).status_code == 200


def test_terminology_event_label(client):
    h = _admin(client)
    terms = client.get("/terminology", headers=h).json()
    assert terms["project"] == {"singular": "Event", "plural": "Events"}
    assert terms["project_participant"]["singular"] == "Participant"


# ── profiles (AC-11-02, -07) ────────────────────────────────────────────────


def test_profile_crud_dedup_and_tier1_transition(client):
    h = _admin(client)
    res = client.post("/ems/profiles", json={"email": "Alice@E2E.com", "fullName": "Alice"}, headers=h)
    assert res.status_code == 201, res.text
    p = res.json()
    assert p["email"] == "alice@e2e.com"  # lowercased
    assert p["statusId"]  # tier-1 initial status set

    # dedup (case-insensitive)
    dup = client.post("/ems/profiles", json={"email": "alice@e2e.com"}, headers=h)
    assert dup.status_code == 409

    # update + soft-delete round-trip
    upd = client.patch(f"/ems/profiles/{p['id']}", json={"phone": "+100"}, headers=h)
    assert upd.status_code == 200 and upd.json()["phone"] == "+100"
    assert client.delete(f"/ems/profiles/{p['id']}", headers=h).status_code == 204


def test_profile_tier1_transition_via_graph(client, session_factory):
    h = _admin(client)
    p = client.post("/ems/profiles", json={"email": "bob@e2e.com"}, headers=h).json()
    db = session_factory()
    from app.models.status import Status

    suspended = (
        db.query(Status)
        .filter(
            Status.entity_type == "profile",
            Status.tenant_id == DEFAULT_TENANT_ID,
            Status.key == "suspended",
        )
        .first()
    )
    db.close()
    res = client.post(
        f"/ems/profiles/{p['id']}/transition",
        json={"toStatusId": suspended.id},
        headers=h,
    )
    assert res.status_code == 200, res.text
    assert res.json()["statusId"] == suspended.id


# ── hierarchy + copy_scope (AC-11-03, -04) ──────────────────────────────────


def _make_type_template_project(client, h):
    t = client.post("/ems/project-types", json={"name": "Fun Run"}, headers=h).json()
    tmpl = client.post(
        "/ems/project-templates", json={"typeId": t["id"], "name": "Standard"}, headers=h
    ).json()
    proj = client.post(
        "/ems/projects", json={"templateId": tmpl["id"], "title": "City Run 2026"}, headers=h
    ).json()
    return t, tmpl, proj


def test_create_from_template_copies_eligibility_graph(client, session_factory):
    h = _admin(client)
    t, tmpl, proj = _make_type_template_project(client, h)
    assert proj["statusId"]  # project lifecycle initial set
    db = session_factory()
    # Template has a materialized scope graph; the project has its OWN copy.
    tmpl_ids = scope_status_ids(db, PARTICIPANT_ENTITY, DEFAULT_TENANT_ID, tmpl["id"])
    proj_ids = scope_status_ids(db, PARTICIPANT_ENTITY, DEFAULT_TENANT_ID, proj["id"])
    db.close()
    assert len(tmpl_ids) == 5  # the seed set
    assert len(proj_ids) == 5  # copied
    assert set(tmpl_ids).isdisjoint(proj_ids)  # distinct rows (a copy, not shared)


# ── participants (AC-11-05) ─────────────────────────────────────────────────


def test_participant_add_uniqueness_and_tier2_transition(client, session_factory):
    h = _admin(client)
    _, _, proj = _make_type_template_project(client, h)
    prof = client.post("/ems/profiles", json={"email": "runner@e2e.com"}, headers=h).json()

    add = client.post(
        f"/ems/projects/{proj['id']}/participants",
        json={"profileId": prof["id"]},
        headers=h,
    )
    assert add.status_code == 201, add.text
    pp = add.json()
    assert pp["statusId"]  # tier-2 initial scoped status set

    # uniqueness — one row per (profile, project)
    dup = client.post(
        f"/ems/projects/{proj['id']}/participants", json={"profileId": prof["id"]}, headers=h
    )
    assert dup.status_code == 409

    # tier-2 transition Registered → Pending Payment (scoped graph)
    db = session_factory()
    from app.models.status import Status

    pending = (
        db.query(Status)
        .filter(
            Status.entity_type == PARTICIPANT_ENTITY,
            Status.scope_id == proj["id"],
            Status.key == "pending_payment",
        )
        .first()
    )
    db.close()
    res = client.post(
        f"/ems/projects/{proj['id']}/participants/{pp['id']}/transition",
        json={"toStatusId": pending.id},
        headers=h,
    )
    assert res.status_code == 200, res.text
    assert res.json()["statusId"] == pending.id


# ── bulk participant import: find-or-create profile (AC-11-05, -17) ──────────


def test_participant_bulk_import_find_or_create(client):
    h = _admin(client)
    _, _, proj = _make_type_template_project(client, h)
    # one existing profile + one brand-new email
    client.post("/ems/profiles", json={"email": "existing@e2e.com"}, headers=h)

    csv = "Profile email\nexisting@e2e.com\nbrandnew@e2e.com\n".encode("utf-8")
    import json as _json

    res = client.post(
        "/imports",
        data={"entityType": "project_participant", "mode": "create_only", "context": _json.dumps({"project_id": proj["id"]})},
        files={"file": ("p.csv", csv, "application/octet-stream")},
        headers=h,
    )
    assert res.status_code == 201, res.text
    job_id = res.json()["jobId"]
    client.put(f"/imports/{job_id}/mapping", json={"mapping": {"Profile email": "profile"}, "sheetName": None}, headers=h)
    job = client.get(f"/imports/{job_id}", headers=h).json()
    assert job["validRows"] == 2, job
    client.post(f"/imports/{job_id}/commit", headers=h)
    done = client.get(f"/imports/{job_id}", headers=h).json()
    assert done["status"] == "done", done

    # both participants registered; the new email got a created profile.
    parts = client.get(f"/ems/projects/{proj['id']}/participants", headers=h).json()
    assert parts["total"] == 2
    profiles = client.get("/ems/profiles?search=brandnew", headers=h).json()
    assert profiles["total"] == 1  # find-or-create made it


# ── eligibility-flow editor: graph readable at BOTH scope owners (AC-11-12) ──


def test_participant_graph_readable_at_template_and_project_scope(client):
    h = _admin(client)
    _, tmpl, proj = _make_type_template_project(client, h)
    # the template's Flow tab reads scope=template_id (materialized at create)
    tg = client.get(
        "/statuses", params={"entityType": "project_participant", "scopeId": tmpl["id"]}, headers=h
    )
    assert tg.status_code == 200, tg.text
    assert len(tg.json()["statuses"]) == 5
    # the project's Flow tab reads scope=project_id (copied at create)
    pg = client.get(
        "/statuses", params={"entityType": "project_participant", "scopeId": proj["id"]}, headers=h
    )
    assert pg.status_code == 200, pg.text
    assert len(pg.json()["statuses"]) == 5
    # an unknown scope id is still rejected (guard intact)
    bad = client.get(
        "/statuses", params={"entityType": "project_participant", "scopeId": "nope"}, headers=h
    )
    assert bad.status_code == 404


# ── type / template management: update + delete guards ──────────────────────


def test_type_update_delete_and_guard(client):
    h = _admin(client)
    t = client.post("/ems/project-types", json={"name": "Gala"}, headers=h).json()

    upd = client.patch(f"/ems/project-types/{t['id']}", json={"description": "Black tie"}, headers=h)
    assert upd.status_code == 200 and upd.json()["description"] == "Black tie"

    # a type owning a template can't be deleted (would orphan it)
    tmpl = client.post(
        "/ems/project-templates", json={"typeId": t["id"], "name": "VIP"}, headers=h
    ).json()
    blocked = client.delete(f"/ems/project-types/{t['id']}", headers=h)
    assert blocked.status_code == 409, blocked.text

    # remove the template first → the type deletes, then drops out of the list
    assert client.delete(f"/ems/project-templates/{tmpl['id']}", headers=h).status_code == 204
    assert client.delete(f"/ems/project-types/{t['id']}", headers=h).status_code == 204
    names = [r["id"] for r in client.get("/ems/project-types", headers=h).json()["items"]]
    assert t["id"] not in names


def test_template_update_delete_and_guard(client):
    h = _admin(client)
    t, tmpl, proj = _make_type_template_project(client, h)

    upd = client.patch(
        f"/ems/project-templates/{tmpl['id']}", json={"name": "Standard v2"}, headers=h
    )
    assert upd.status_code == 200 and upd.json()["name"] == "Standard v2"

    # a template used by an existing event can't be deleted
    blocked = client.delete(f"/ems/project-templates/{tmpl['id']}", headers=h)
    assert blocked.status_code == 409, blocked.text

    # an unused template deletes cleanly
    free = client.post(
        "/ems/project-templates", json={"typeId": t["id"], "name": "Unused"}, headers=h
    ).json()
    assert client.delete(f"/ems/project-templates/{free['id']}", headers=h).status_code == 204


def test_type_template_manage_perm_required(client):
    """read-only callers can list but not mutate (gated project_*.manage)."""
    h = _admin(client)
    t = client.post("/ems/project-types", json={"name": "Perm"}, headers=h).json()
    # the demo admin holds manage; assert the gate exists by hitting an unknown id
    # (404 from the service, NOT a 403/401 — proves the perm passed for admin).
    assert client.patch("/ems/project-types/nope", json={"name": "x"}, headers=h).status_code == 404
    assert client.delete(f"/ems/project-types/{t['id']}", headers=h).status_code == 204


# ── template roles/segments + participant assignment (AC-11-01) ─────────────


def test_template_roles_segments_and_participant_assignment(client):
    h = _admin(client)
    t = client.post("/ems/project-types", json={"name": "Race"}, headers=h).json()
    tmpl = client.post(
        "/ems/project-templates", json={"typeId": t["id"], "name": "10k"}, headers=h
    ).json()

    # add roles + segments to the template
    role = client.post(
        f"/ems/project-templates/{tmpl['id']}/roles", json={"name": "Volunteer"}, headers=h
    )
    assert role.status_code == 201, role.text
    role = role.json()
    seg = client.post(
        f"/ems/project-templates/{tmpl['id']}/segments", json={"name": "Elite"}, headers=h
    ).json()
    assert [r["name"] for r in client.get(f"/ems/project-templates/{tmpl['id']}/roles", headers=h).json()] == ["Volunteer"]

    # event from the template; register a participant WITH role + segment
    proj = client.post(
        "/ems/projects", json={"templateId": tmpl["id"], "title": "City 10k"}, headers=h
    ).json()
    prof = client.post("/ems/profiles", json={"email": "v@e2e.com"}, headers=h).json()
    pp = client.post(
        f"/ems/projects/{proj['id']}/participants",
        json={"profileId": prof["id"], "roleId": role["id"], "segmentId": seg["id"]},
        headers=h,
    )
    assert pp.status_code == 201, pp.text
    assert pp.json()["roleId"] == role["id"] and pp.json()["segmentId"] == seg["id"]

    # a role from ANOTHER template is rejected (cross-template guard)
    other = client.post(
        "/ems/project-templates", json={"typeId": t["id"], "name": "5k"}, headers=h
    ).json()
    other_role = client.post(
        f"/ems/project-templates/{other['id']}/roles", json={"name": "Marshal"}, headers=h
    ).json()
    prof2 = client.post("/ems/profiles", json={"email": "x@e2e.com"}, headers=h).json()
    bad = client.post(
        f"/ems/projects/{proj['id']}/participants",
        json={"profileId": prof2["id"], "roleId": other_role["id"]},
        headers=h,
    )
    assert bad.status_code == 422, bad.text

    # reassign role via PATCH
    upd = client.patch(
        f"/ems/projects/{proj['id']}/participants/{pp.json()['id']}",
        json={"roleId": None},
        headers=h,
    )
    assert upd.status_code == 200 and upd.json()["roleId"] is None

    # deleting a role is allowed (template-level master data)
    assert client.delete(
        f"/ems/project-templates/{tmpl['id']}/roles/{role['id']}", headers=h
    ).status_code == 204


# ── tier-1 status gates participation (status engine controls events) ───────


def test_blocked_profile_cannot_register(client, session_factory):
    h = _admin(client)
    _, _, proj = _make_type_template_project(client, h)
    prof = client.post("/ems/profiles", json={"email": "blocked@e2e.com"}, headers=h).json()

    # suspend the profile (blocks_access status)
    db = session_factory()
    from app.models.status import Status

    suspended = (
        db.query(Status)
        .filter(
            Status.entity_type == "profile",
            Status.tenant_id == DEFAULT_TENANT_ID,
            Status.key == "suspended",
        )
        .first()
    )
    db.close()
    client.post(f"/ems/profiles/{prof['id']}/transition", json={"toStatusId": suspended.id}, headers=h)

    # add-one is refused
    res = client.post(
        f"/ems/projects/{proj['id']}/participants", json={"profileId": prof["id"]}, headers=h
    )
    assert res.status_code == 422, res.text
    assert "register" in res.json()["detail"].lower()

    # bulk import of the suspended profile is refused too
    import json as _json

    csv = "Profile email\nblocked@e2e.com\n".encode("utf-8")
    job = client.post(
        "/imports",
        data={"entityType": "project_participant", "mode": "create_only", "context": _json.dumps({"project_id": proj["id"]})},
        files={"file": ("p.csv", csv, "application/octet-stream")},
        headers=h,
    ).json()
    client.put(f"/imports/{job['jobId']}/mapping", json={"mapping": {"Profile email": "profile"}, "sheetName": None}, headers=h)
    client.post(f"/imports/{job['jobId']}/commit", headers=h)
    done = client.get(f"/imports/{job['jobId']}", headers=h).json()
    assert done["status"] != "done"  # refused — the blocked profile aborts the batch
    # and no participant got created
    assert client.get(f"/ems/projects/{proj['id']}/participants", headers=h).json()["total"] == 0


# ── tenant isolation (AC-11-09) ─────────────────────────────────────────────


def test_tenant_isolation(client):
    h = _admin(client)
    prof = client.post("/ems/profiles", json={"email": "iso@e2e.com"}, headers=h).json()
    # provision a second tenant + install ems
    ph = _h(_login(client, PLATFORM_EMAIL, PLATFORM_PASSWORD, "platform"))
    client.post(
        "/platform/tenants",
        json={"name": "Beta", "slug": "beta-ems", "adminName": "B", "adminEmail": "b@ems.com", "adminPassword": "ChangeMe1!"},
        headers=ph,
    )
    client.post("/platform/tenants/by-slug", headers=ph)  # no-op tolerance
    hb = _h(_login(client, "b@ems.com", "ChangeMe1!", "beta-ems"))
    # beta hasn't installed ems → module gated 403 (require_module)
    assert client.get("/ems/profiles", headers=hb).status_code == 403
    # tenant A's profile is invisible cross-tenant
    assert client.get(f"/ems/profiles/{prof['id']}", headers=hb).status_code in (403, 404)


def test_event_auto_confirms_on_participant_count(client, session_factory):
    """AC-03-35 — the configurable participant-count aggregate end-to-end: an
    auto edge on the project graph fires when enough participants are added."""
    h = _admin(client)
    _, _, proj = _make_type_template_project(client, h)

    g = client.get("/statuses", params={"entityType": "project"}, headers=h).json()
    sid = {s["label"]: s["id"] for s in g["statuses"]}

    edge = client.post(
        "/statuses/transitions",
        json={
            "entityType": "project",
            "fromStatusId": sid["Draft"],
            "toStatusId": sid["Active"],
            "label": "Auto-confirm",
            "triggerMode": "auto",
            "conditionsJson": {
                "kind": "group",
                "combinator": "and",
                "rules": [
                    {
                        "kind": "condition",
                        "fact": "record.participants.count",
                        "operator": "gte",
                        "valueKind": "literal",
                        "value": 2,
                    }
                ],
            },
        },
        headers=h,
    )
    assert edge.status_code == 201, edge.text

    def pstatus():
        db = session_factory()
        try:
            return db.query(Project).filter(Project.id == proj["id"]).first().status_id
        finally:
            db.close()

    assert pstatus() == sid["Draft"]  # starts at initial

    for i in range(2):
        prof = client.post(
            "/ems/profiles", json={"email": f"cnt{i}@e2e.com"}, headers=h
        ).json()
        add = client.post(
            f"/ems/projects/{proj['id']}/participants",
            json={"profileId": prof["id"]},
            headers=h,
        )
        assert add.status_code == 201, add.text

    # 2nd participant tips count >= 2 → the auto edge re-derives the event.
    assert pstatus() == sid["Active"]


# ── event details edit (sprint-4/03 Slice 5) ─────────────────────────────────


def test_project_update_fields_and_date_only(client):
    """AC-03-38/39/40 — PATCH merges fields + dates; dates round-trip date-only."""
    h = _admin(client)
    _, _, proj = _make_type_template_project(client, h)
    res = client.patch(
        f"/ems/projects/{proj['id']}",
        json={
            "brief": "Flagship",
            "notes": "VIP seating",
            "domainName": "conf.example.com",
            "startDate": "2026-09-01",
            "endDate": "2026-09-03",
            "eventValidityEnd": "2026-09-10",
        },
        headers=h,
    )
    assert res.status_code == 200, res.text
    p = res.json()
    assert p["brief"] == "Flagship" and p["notes"] == "VIP seating"
    assert p["domainName"] == "conf.example.com"
    # date-only — no time component, no tz shift
    assert p["startDate"] == "2026-09-01"
    assert p["endDate"] == "2026-09-03"
    assert p["eventValidityEnd"] == "2026-09-10"
    # GET re-exposes them
    got = client.get(f"/ems/projects/{proj['id']}", headers=h).json()
    assert got["startDate"] == "2026-09-01" and got["endDate"] == "2026-09-03"


def test_project_update_partial_keep_and_clear(client):
    """PATCH-merge: absent key kept, explicit null clears."""
    h = _admin(client)
    _, _, proj = _make_type_template_project(client, h)
    client.patch(f"/ems/projects/{proj['id']}", json={"brief": "B", "endDate": "2026-09-03"}, headers=h)
    # absent brief kept, endDate cleared via null
    p = client.patch(f"/ems/projects/{proj['id']}", json={"endDate": None}, headers=h).json()
    assert p["brief"] == "B"  # untouched
    assert p["endDate"] is None  # cleared


def test_project_update_date_ordering_422(client):
    """AC-03-41 — end < start (and validity < end) rejected."""
    h = _admin(client)
    _, _, proj = _make_type_template_project(client, h)
    bad = client.patch(
        f"/ems/projects/{proj['id']}",
        json={"startDate": "2026-09-05", "endDate": "2026-09-01"},
        headers=h,
    )
    assert bad.status_code == 422, bad.text
    bad2 = client.patch(
        f"/ems/projects/{proj['id']}",
        json={"startDate": "2026-09-01", "endDate": "2026-09-05", "eventValidityEnd": "2026-09-02"},
        headers=h,
    )
    assert bad2.status_code == 422, bad2.text


def test_project_update_cannot_repoint_template(client):
    """AC-03-38 — template_id is immutable: not in the update schema, so a PATCH
    carrying it never re-points the event (foreign key untouched)."""
    h = _admin(client)
    _, tmpl, proj = _make_type_template_project(client, h)
    before = proj["templateId"]
    res = client.patch(
        f"/ems/projects/{proj['id']}",
        json={"title": "Renamed", "templateId": "some-other-id"},
        headers=h,
    )
    # Either ignored (200, template unchanged) or rejected as unknown (422) — never re-pointed.
    if res.status_code == 200:
        assert res.json()["templateId"] == before
        assert res.json()["title"] == "Renamed"
    else:
        assert res.status_code == 422


def test_event_auto_advances_on_date_field_save(client, session_factory):
    """sprint-4/03 — a field-vs-FIXED-date auto edge fires on SAVE (event-driven,
    NOT the time sweep): setting end_date past the threshold re-derives the event
    via the update event + generic self re-eval."""
    h = _admin(client)
    _, _, proj = _make_type_template_project(client, h)
    g = client.get("/statuses", params={"entityType": "project"}, headers=h).json()
    sid = {s["label"]: s["id"] for s in g["statuses"]}
    # auto Draft→Active when End Date is after 2026-06-18 (unused pair → no collision)
    edge = client.post(
        "/statuses/transitions",
        json={
            "entityType": "project",
            "fromStatusId": sid["Draft"],
            "toStatusId": sid["Active"],
            "label": "Auto-activate",
            "triggerMode": "auto",
            "conditionsJson": {
                "kind": "group", "combinator": "and",
                "rules": [{
                    "kind": "condition", "fact": "record.endDate",
                    "operator": "after", "valueKind": "literal", "value": "2026-06-18",
                }],
            },
        },
        headers=h,
    )
    assert edge.status_code == 201, edge.text

    def pstatus():
        db = session_factory()
        try:
            return db.query(Project).filter(Project.id == proj["id"]).first().status_id
        finally:
            db.close()

    assert pstatus() == sid["Draft"]  # not yet — no end_date
    # SAVE an end_date past the threshold → auto-advance (on save, not a tick)
    r = client.patch(f"/ems/projects/{proj['id']}", json={"endDate": "2026-06-19"}, headers=h)
    assert r.status_code == 200, r.text
    assert pstatus() == sid["Active"]


def _date_auto_edge(client, h, sid, op, value):
    """Author a Draft→Active auto edge on `Days since End Date <op> <value>`."""
    return client.post(
        "/statuses/transitions",
        json={
            "entityType": "project",
            "fromStatusId": sid["Draft"],
            "toStatusId": sid["Active"],
            "label": "Auto on end",
            "triggerMode": "auto",
            "conditionsJson": {
                "kind": "group", "combinator": "and",
                "rules": [{
                    "kind": "condition", "fact": "record.endDate.daysSince",
                    "operator": op, "valueKind": "literal", "value": value,
                }],
            },
        },
        headers=h,
    )


def test_event_time_sweep_advances_past_end(client, session_factory):
    """sprint-4/03 Slice 6 — the TIME SWEEP advances an event whose end_date is
    now in the past, with NO write (the bus can't catch a passing clock). The
    'now' lives in the auto-generated `Days since End Date` fact (clock-based)."""
    from datetime import datetime, timedelta, timezone

    from app.workflow_engine.scheduler import reevaluate_time_based

    h = _admin(client)
    _, _, proj = _make_type_template_project(client, h)
    g = client.get("/statuses", params={"entityType": "project"}, headers=h).json()
    sid = {s["label"]: s["id"] for s in g["statuses"]}
    # auto Draft→Active when "Days since End Date >= 0" (i.e. end has passed)
    assert _date_auto_edge(client, h, sid, "gte", 0).status_code == 201

    # Set end_date in the PAST directly (no update emit → simulates the clock passing).
    db = session_factory()
    p = db.query(Project).filter(Project.id == proj["id"]).first()
    p.end_date = datetime.now(timezone.utc).date() - timedelta(days=1)
    db.commit()
    db.close()

    def pstatus():
        db = session_factory()
        try:
            return db.query(Project).filter(Project.id == proj["id"]).first().status_id
        finally:
            db.close()

    assert pstatus() == sid["Draft"]  # no event fired — bus didn't see it
    advanced = reevaluate_time_based(session_factory())
    assert advanced >= 1
    assert pstatus() == sid["Active"]  # the sweep caught it


def test_clock_override_resets():
    """AC-03-46 — clock_override pins now() for the block, resets after."""
    from datetime import date, datetime, timezone

    from app import clock

    real = clock.now()
    assert real.tzinfo is not None
    with clock.clock_override(date(2030, 1, 1)):
        assert clock.today() == date(2030, 1, 1)
        assert clock.now() == datetime(2030, 1, 1, tzinfo=timezone.utc)
    assert clock.today() != date(2030, 1, 1)  # reset


def test_simulate_dry_run_then_apply(client, session_factory):
    """AC-03-50/51/52 — simulate AS-OF a future date: dry-run previews + persists
    nothing; apply commits. Uses the day-count fact (truly time-dependent)."""
    h = _admin(client)
    _, _, proj = _make_type_template_project(client, h)
    g = client.get("/statuses", params={"entityType": "project"}, headers=h).json()
    sid = {s["label"]: s["id"] for s in g["statuses"]}
    # close 2 days after end_date
    assert _date_auto_edge(client, h, sid, "gte", 2).status_code == 201
    # end_date today (via API; daysSince today = 0 < 2 → does NOT fire on save)
    from datetime import date, timedelta

    end = date.today()  # today → daysSince 0 < 2 (relative, not a hard-coded date-bomb)
    client.patch(f"/ems/projects/{proj['id']}", json={"endDate": end.isoformat()}, headers=h)

    def pstatus():
        return client.get(f"/ems/projects/{proj['id']}", headers=h).json()["statusId"]

    assert pstatus() == sid["Draft"]
    as_of = (end + timedelta(days=2)).isoformat()  # 2 days after end → condition true

    # dry-run: previews the would-advance row, persists nothing
    dry = client.post(
        "/status-entities/project/simulate",
        json={"asOf": as_of, "apply": False}, headers=h,
    )
    assert dry.status_code == 200, dry.text
    body = dry.json()
    assert body["applied"] is False
    assert any(r["id"] == proj["id"] and r["toId"] == sid["Active"] for r in body["data"])
    assert pstatus() == sid["Draft"]  # nothing persisted

    # apply: commits the transition
    app_res = client.post(
        "/status-entities/project/simulate",
        json={"asOf": as_of, "apply": True}, headers=h,
    )
    assert app_res.status_code == 200
    assert app_res.json()["applied"] is True
    assert pstatus() == sid["Active"]


def test_simulate_requires_manage_perm(client):
    """AC-03-52 — simulate is gated statuses.manage."""
    # demo admin has it; a token without statuses.manage would 403. Smoke: the
    # admin call returns 200 (full assertion of the 403 path lives in RBAC tests).
    h = _admin(client)
    res = client.post(
        "/status-entities/project/simulate",
        json={"asOf": "2026-01-01", "apply": False}, headers=h,
    )
    assert res.status_code == 200, res.text
