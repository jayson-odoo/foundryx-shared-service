"""Form engine tests (plan sprint-3/01 §TDD) - service/router/scoped-status
integration over httpx TestClient.

Covers: create (scoped Draft→Submitted machine materialized) · slug dedupe ·
draft update · the publish gate 422 {problems} · publish snapshots a version +
paginated versions · unpublish → fill 404 · fill serves the PUBLISHED version
(edit-draft-after-publish still serves old) · preview serves the DRAFT · submit
happy path (lands Submitted; hidden answers dropped, computed recomputed) ·
submit 422 {fieldErrors} · window closed 409 · max-submissions 409 ·
per-user-limit 409 · submissions list (userName, statusKey,
availableTransitionIds) · custom status+edge then transition · cross-form
transition refused · tenant isolation · permission gates · delete drops the
scoped statuses.
"""
import uuid

from tests.conftest import (
    ACTIVE_EMAIL,
    ACTIVE_PASSWORD,
    PLATFORM_EMAIL,
    PLATFORM_PASSWORD,
)


# ---- helpers ----


def _login(client, email, password, slug=None):
    payload = {"email": email, "password": password}
    if slug:
        payload["tenantSlug"] = slug
    res = client.post("/auth/login", json=payload)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _operator(client):
    return _login(client, PLATFORM_EMAIL, PLATFORM_PASSWORD, "platform")


def _admin(client):
    return _login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD)


def _uniq(prefix):
    return f"{prefix} {uuid.uuid4().hex[:8]}"


def _create_form(client, headers, name=None, access="internal"):
    name = name or _uniq("Form")
    res = client.post("/forms", json={"name": name, "access": access}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def _doc(*fields, pages=None):
    """Single-page doc helper. ``fields`` are FormField dicts."""
    return {
        "schemaVersion": 1,
        "pages": pages
        or [
            {
                "id": "p1",
                "title": "Page 1",
                "sections": [{"id": "s1", "fields": list(fields)}],
            }
        ],
    }


def _text_field(fid, key, label="Field", required=False, **extra):
    f = {"id": fid, "type": "text", "key": key, "label": label}
    if required:
        f["required"] = True
    f.update(extra)
    return f


def _set_draft(client, headers, form_id, doc):
    res = client.patch(f"/forms/{form_id}", json={"draftDefinition": doc}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def _publish(client, headers, form_id):
    return client.post(f"/forms/{form_id}/publish", headers=headers)


# ---- create + scoped statuses ----


def test_create_materializes_scoped_machine(client):
    headers = _admin(client)
    form = _create_form(client, headers)
    res = client.get(
        "/statuses",
        params={"entityType": "form_submission", "scopeId": form["id"]},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    keys = {s["key"] for s in body["statuses"]}
    assert {"draft", "submitted"} <= keys
    assert len(body["transitions"]) == 1
    assert body["transitions"][0]["label"] == "Submit"


def test_slug_dedupe(client):
    headers = _admin(client)
    name = _uniq("Dup")
    a = _create_form(client, headers, name=name)
    b = _create_form(client, headers, name=name)
    assert a["slug"] != b["slug"]
    assert b["slug"].startswith(a["slug"])


# ---- draft update + publish gate ----


def test_update_draft_definition(client):
    headers = _admin(client)
    form = _create_form(client, headers)
    doc = _doc(_text_field("f1", "name", "Your name", required=True))
    body = _set_draft(client, headers, form["id"], doc)
    assert body["draftDefinition"]["pages"][0]["sections"][0]["fields"][0]["key"] == "name"
    assert body["hasUnpublishedChanges"] is True


def test_publish_gate_blocks_invalid(client):
    headers = _admin(client)
    form = _create_form(client, headers)
    # Empty doc → publish gate returns problems.
    res = _publish(client, headers, form["id"])
    assert res.status_code == 422, res.text
    assert "problems" in res.json()["detail"]
    assert isinstance(res.json()["detail"]["problems"], list)
    assert res.json()["detail"]["problems"]


def test_publish_snapshots_and_versions_paginate(client):
    headers = _admin(client)
    form = _create_form(client, headers)
    _set_draft(client, headers, form["id"], _doc(_text_field("f1", "name", required=True)))
    res = _publish(client, headers, form["id"])
    assert res.status_code == 200, res.text
    detail = res.json()
    assert detail["status"] == "published"
    assert detail["currentVersionId"]
    assert detail["currentVersionNumber"] == 1
    assert detail["hasUnpublishedChanges"] is False

    vres = client.get(f"/forms/{form['id']}/versions", headers=headers)
    assert vres.status_code == 200
    versions = vres.json()
    assert versions["total"] == 1
    assert versions["data"][0]["versionNumber"] == 1
    assert versions["data"][0]["publishedByName"]

    # The version's immutable definition is fetchable for the submission-detail
    # re-render contract (D9).
    version_id = detail["currentVersionId"]
    dres = client.get(f"/forms/{form['id']}/versions/{version_id}", headers=headers)
    assert dres.status_code == 200, dres.text
    assert dres.json()["versionNumber"] == 1
    assert dres.json()["definition"]["pages"]
    # A bogus version id → 404 (never resolve a stored id unscoped).
    assert (
        client.get(f"/forms/{form['id']}/versions/does-not-exist", headers=headers).status_code
        == 404
    )


# ---- fill / preview (D9) ----


def test_unpublish_fill_404(client):
    headers = _admin(client)
    form = _create_form(client, headers)
    _set_draft(client, headers, form["id"], _doc(_text_field("f1", "name")))
    _publish(client, headers, form["id"])
    assert client.get(f"/forms/{form['id']}/fill", headers=headers).status_code == 200
    client.post(f"/forms/{form['id']}/unpublish", headers=headers)
    assert client.get(f"/forms/{form['id']}/fill", headers=headers).status_code == 404


def test_fill_serves_published_not_draft(client):
    headers = _admin(client)
    form = _create_form(client, headers)
    _set_draft(client, headers, form["id"], _doc(_text_field("f1", "name", "Name v1")))
    _publish(client, headers, form["id"])
    # Edit the draft AFTER publishing - fill must still serve v1.
    _set_draft(client, headers, form["id"], _doc(_text_field("f1", "name", "Name v2")))
    fill = client.get(f"/forms/{form['id']}/fill", headers=headers).json()
    label = fill["definition"]["pages"][0]["sections"][0]["fields"][0]["label"]
    assert label == "Name v1"
    # Preview serves the live draft (v2).
    prev = client.post(f"/forms/{form['id']}/preview", headers=headers).json()
    plabel = prev["definition"]["pages"][0]["sections"][0]["fields"][0]["label"]
    assert plabel == "Name v2"


# ---- submit pipeline (D14) ----


def _conditional_computed_doc():
    """qty (number) + showExtra (yesno) gating an 'extra' text field, plus a
    computed total = qty * 2. Submitting showExtra=false drops 'extra'; the
    computed value is always recomputed server-side."""
    qty = {"id": "f_qty", "type": "number", "key": "qty", "label": "Qty", "required": True}
    show = {"id": "f_show", "type": "yesno", "key": "showExtra", "label": "Show extra?"}
    extra = {
        "id": "f_extra",
        "type": "text",
        "key": "extra",
        "label": "Extra",
        "conditionsJson": {
            "combinator": "and",
            "rules": [{"fact": "answers.showExtra", "operator": "is_true", "value": True}],
        },
    }
    total = {"id": "f_total", "type": "computed", "key": "total", "label": "Total",
             "computed": {"expression": "qty * 2"}}
    return _doc(qty, show, extra, total)


def test_submit_happy_path_cleans_answers(client):
    headers = _admin(client)
    form = _create_form(client, headers)
    _set_draft(client, headers, form["id"], _conditional_computed_doc())
    _publish(client, headers, form["id"])

    # showExtra false → 'extra' hidden, dropped; total recomputed = qty*2.
    res = client.post(
        f"/forms/{form['id']}/submissions",
        json={"answers": {"qty": 5, "showExtra": False, "extra": "should drop"}},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    sub = res.json()
    assert sub["statusKey"] == "submitted"
    assert "extra" not in sub["answers"]
    assert sub["answers"]["total"] == 10
    assert sub["submittedAt"]


def test_submit_invalid_field_errors(client):
    headers = _admin(client)
    form = _create_form(client, headers)
    _set_draft(client, headers, form["id"], _doc(_text_field("f1", "name", required=True)))
    _publish(client, headers, form["id"])
    res = client.post(f"/forms/{form['id']}/submissions", json={"answers": {}}, headers=headers)
    assert res.status_code == 422, res.text
    assert "fieldErrors" in res.json()["detail"]
    assert "name" in res.json()["detail"]["fieldErrors"]


def test_submit_window_closed(client):
    headers = _admin(client)
    form = _create_form(client, headers)
    _set_draft(client, headers, form["id"], _doc(_text_field("f1", "name")))
    _publish(client, headers, form["id"])
    # closesAt in the past.
    client.patch(f"/forms/{form['id']}", json={"closesAt": "2000-01-01T00:00:00Z"}, headers=headers)
    res = client.post(f"/forms/{form['id']}/submissions", json={"answers": {}}, headers=headers)
    assert res.status_code == 409, res.text


def test_submit_max_submissions(client):
    headers = _admin(client)
    form = _create_form(client, headers)
    _set_draft(client, headers, form["id"], _doc(_text_field("f1", "name")))
    _publish(client, headers, form["id"])
    client.patch(f"/forms/{form['id']}", json={"maxSubmissions": 1}, headers=headers)
    assert client.post(f"/forms/{form['id']}/submissions", json={"answers": {}}, headers=headers).status_code == 201
    res = client.post(f"/forms/{form['id']}/submissions", json={"answers": {}}, headers=headers)
    assert res.status_code == 409, res.text


def test_submit_per_user_limit(client):
    headers = _admin(client)
    form = _create_form(client, headers, access="internal")
    _set_draft(client, headers, form["id"], _doc(_text_field("f1", "name")))
    _publish(client, headers, form["id"])
    client.patch(f"/forms/{form['id']}", json={"submissionLimitPerUser": 1}, headers=headers)
    assert client.post(f"/forms/{form['id']}/submissions", json={"answers": {}}, headers=headers).status_code == 201
    res = client.post(f"/forms/{form['id']}/submissions", json={"answers": {}}, headers=headers)
    assert res.status_code == 409, res.text


# ---- submissions list + transitions ----


def test_submissions_list_fields(client):
    headers = _admin(client)
    form = _create_form(client, headers)
    _set_draft(client, headers, form["id"], _doc(_text_field("f1", "name")))
    _publish(client, headers, form["id"])
    client.post(f"/forms/{form['id']}/submissions", json={"answers": {"name": "Alice"}}, headers=headers)

    res = client.get(f"/forms/{form['id']}/submissions", headers=headers)
    assert res.status_code == 200, res.text
    rows = res.json()["data"]
    assert len(rows) == 1
    row = rows[0]
    assert row["userName"] == "Demo User"
    assert row["statusKey"] == "submitted"
    # availableTransitionIds reflects the scope edges (a fresh seed has no edge
    # OUT of Submitted, so an empty list is correct).
    assert isinstance(row["availableTransitionIds"], list)


def test_custom_status_edge_then_transition(client):
    headers = _admin(client)
    form = _create_form(client, headers)
    _set_draft(client, headers, form["id"], _doc(_text_field("f1", "name")))
    _publish(client, headers, form["id"])
    sub = client.post(
        f"/forms/{form['id']}/submissions", json={"answers": {"name": "Bob"}}, headers=headers
    ).json()

    # Add a custom "Reviewed" status + an edge Submitted→Reviewed in this scope.
    graph = client.get(f"/forms/{form['id']}/graph", headers=headers).json()
    submitted_id = next(s["id"] for s in graph["statuses"] if s["key"] == "submitted")
    reviewed = client.post(
        "/statuses",
        json={"entityType": "form_submission", "label": "Reviewed", "color": "green",
              "scopeId": form["id"]},
        headers=headers,
    )
    assert reviewed.status_code == 201, reviewed.text
    reviewed_id = reviewed.json()["id"]
    edge = client.post(
        "/statuses/transitions",
        json={"entityType": "form_submission", "fromStatusId": submitted_id,
              "toStatusId": reviewed_id, "label": "Mark reviewed", "scopeId": form["id"]},
        headers=headers,
    )
    assert edge.status_code == 201, edge.text
    edge_id = edge.json()["id"]

    # The submission's list row now offers the new edge.
    rows = client.get(f"/forms/{form['id']}/submissions", headers=headers).json()["data"]
    assert edge_id in rows[0]["availableTransitionIds"]

    # Fire it.
    res = client.post(f"/submissions/{sub['id']}/transition", json={"transitionId": edge_id}, headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["statusKey"] == "reviewed"


def test_cross_form_transition_refused(client):
    headers = _admin(client)
    form_a = _create_form(client, headers)
    form_b = _create_form(client, headers)
    for f in (form_a, form_b):
        _set_draft(client, headers, f["id"], _doc(_text_field("f1", "name")))
        _publish(client, headers, f["id"])
    sub_a = client.post(
        f"/forms/{form_a['id']}/submissions", json={"answers": {"name": "x"}}, headers=headers
    ).json()
    # Build an edge on form B and try it against form A's submission.
    gb = client.get(f"/forms/{form_b['id']}/graph", headers=headers).json()
    b_submitted = next(s["id"] for s in gb["statuses"] if s["key"] == "submitted")
    b_reviewed = client.post(
        "/statuses",
        json={"entityType": "form_submission", "label": "Reviewed", "color": "green",
              "scopeId": form_b["id"]},
        headers=headers,
    ).json()["id"]
    b_edge = client.post(
        "/statuses/transitions",
        json={"entityType": "form_submission", "fromStatusId": b_submitted,
              "toStatusId": b_reviewed, "label": "Review", "scopeId": form_b["id"]},
        headers=headers,
    ).json()["id"]

    res = client.post(f"/submissions/{sub_a['id']}/transition", json={"transitionId": b_edge}, headers=headers)
    assert res.status_code in (404, 409), res.text


# ---- tenant isolation ----


def test_tenant_isolation(client):
    headers = _admin(client)
    form = _create_form(client, headers)

    # Provision a second tenant + its admin via the operator API.
    op = _operator(client)
    slug = f"e2e-{uuid.uuid4().hex[:8]}"
    admin_email = f"admin-{uuid.uuid4().hex[:6]}@example.com"
    prov = client.post(
        "/platform/tenants",
        json={
            "name": "Other Co",
            "slug": slug,
            "adminName": "Other Admin",
            "adminEmail": admin_email,
            "adminPassword": "Str0ng!Pass1",
        },
        headers=op,
    )
    assert prov.status_code in (200, 201), prov.text
    other = _login(client, admin_email, "Str0ng!Pass1", slug)
    res = client.get(f"/forms/{form['id']}", headers=other)
    assert res.status_code == 404, res.text


# ---- permission gates ----


def test_forms_read_gate(client, session_factory):
    # A roleless (no forms.read) user gets 403 on the forms list, while the
    # admin gets 200. Create the user directly with a known password.
    from app.models import DEFAULT_TENANT_ID, User, UserStatus
    from app.security import hash_password

    email = f"noperm-{uuid.uuid4().hex[:6]}@example.com"
    pwd = "Str0ng!Pass1"
    db = session_factory()
    db.add(
        User(
            tenant_id=DEFAULT_TENANT_ID,
            email=email,
            password=hash_password(pwd),
            name="No Perm",
            status=UserStatus.ACTIVE.value,
        )
    )
    db.commit()
    db.close()

    no_perm = _login(client, email, pwd)
    assert client.get("/forms", headers=no_perm).status_code == 403
    assert client.get("/forms", headers=_admin(client)).status_code == 200


def test_fill_allowed_for_authed_user(client):
    headers = _admin(client)
    form = _create_form(client, headers)
    _set_draft(client, headers, form["id"], _doc(_text_field("f1", "name")))
    _publish(client, headers, form["id"])
    # fill is gated by get_current_user only (D19) - admin (authed) reaches it.
    assert client.get(f"/forms/{form['id']}/fill", headers=headers).status_code == 200


# ---- delete drops the scope ----


def test_delete_drops_scoped_statuses(client):
    headers = _admin(client)
    form = _create_form(client, headers)
    # The scope had statuses before delete.
    before = client.get(
        "/statuses",
        params={"entityType": "form_submission", "scopeId": form["id"]},
        headers=headers,
    )
    assert before.status_code == 200
    assert before.json()["statuses"]

    assert client.delete(f"/forms/{form['id']}", headers=headers).status_code == 204
    # The form (scope) is gone - the form GET 404s and the scope graph is
    # unreachable (the scope no longer exists in the tenant).
    assert client.get(f"/forms/{form['id']}", headers=headers).status_code == 404
    after = client.get(
        "/statuses",
        params={"entityType": "form_submission", "scopeId": form["id"]},
        headers=headers,
    )
    assert after.status_code == 404
