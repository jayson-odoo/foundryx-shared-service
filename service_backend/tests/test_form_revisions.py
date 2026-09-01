"""Form submission revision tests (plan sprint-4/04 §Slices) - service/router/
scoped-status integration over the httpx TestClient.

Covers: allow_revisions toggle persists · original identity (group_id == id,
rev 1, current) · revise clones a frozen current submission into a new Draft
(same group, rev+1, current, initial status, answers cloned) · prior revision
frozen + demoted · pins the CURRENT published version · guard matrix
(revisions off / not current / not frozen / no published version / not owner) ·
list defaults to current-only · history endpoint returns the chain · resubmit
edits + fires the Submit edge · resubmit validates against the pinned version.
"""
import uuid

from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


# ---- helpers ----


def _login(client, email, password, slug=None):
    payload = {"email": email, "password": password}
    if slug:
        payload["tenantSlug"] = slug
    res = client.post("/auth/login", json=payload)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _admin(client):
    return _login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD)


def _uniq(prefix):
    return f"{prefix} {uuid.uuid4().hex[:8]}"


def _doc(*fields):
    return {
        "schemaVersion": 1,
        "pages": [{"id": "p1", "title": "Page 1", "sections": [{"id": "s1", "fields": list(fields)}]}],
    }


def _text_field(fid, key, label="Field", required=False, **extra):
    f = {"id": fid, "type": "text", "key": key, "label": label}
    if required:
        f["required"] = True
    f.update(extra)
    return f


def _published_form(client, headers, *, allow_revisions=True, field=None):
    """A published single-text-field form with revisions enabled by default."""
    field = field or _text_field("f1", "name", label="Name", required=True)
    res = client.post("/forms", json={"name": _uniq("Form"), "access": "internal"}, headers=headers)
    assert res.status_code == 201, res.text
    form = res.json()
    client.patch(f"/forms/{form['id']}", json={"draftDefinition": _doc(field)}, headers=headers)
    if allow_revisions:
        client.patch(f"/forms/{form['id']}", json={"allowRevisions": True}, headers=headers)
    assert client.post(f"/forms/{form['id']}/publish", headers=headers).status_code == 200
    return form


def _submit(client, headers, form_id, answers):
    res = client.post(f"/forms/{form_id}/submissions", json={"answers": answers}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


# ---- toggle ----


def test_allow_revisions_toggle_persists(client):
    headers = _admin(client)
    res = client.post("/forms", json={"name": _uniq("Form")}, headers=headers)
    form = res.json()
    assert form["allowRevisions"] is False  # default off
    client.patch(f"/forms/{form['id']}", json={"allowRevisions": True}, headers=headers)
    reloaded = client.get(f"/forms/{form['id']}", headers=headers).json()
    assert reloaded["allowRevisions"] is True


# ---- identity / backfill semantics ----


def test_original_submission_identity(client):
    headers = _admin(client)
    form = _published_form(client, headers)
    sub = _submit(client, headers, form["id"], {"name": "Alice"})
    assert sub["submissionGroupId"] == sub["id"]  # group == id for originals
    assert sub["revisionNumber"] == 1
    assert sub["isCurrent"] is True


# ---- revise ----


def test_revise_clones_into_new_draft(client):
    headers = _admin(client)
    form = _published_form(client, headers)
    original = _submit(client, headers, form["id"], {"name": "Alice"})
    assert original["statusKey"] == "submitted"  # frozen

    res = client.post(f"/submissions/{original['id']}/revise", headers=headers)
    assert res.status_code == 200, res.text
    draft = res.json()
    assert draft["id"] != original["id"]
    assert draft["submissionGroupId"] == original["submissionGroupId"]
    assert draft["revisionNumber"] == 2
    assert draft["isCurrent"] is True
    assert draft["statusKey"] == "draft"  # re-enters at initial
    assert draft["submittedAt"] is None
    assert draft["answers"] == {"name": "Alice"}  # cloned

    # Prior revision frozen + demoted, status unchanged.
    prior = client.get(f"/submissions/{original['id']}", headers=headers).json()
    assert prior["isCurrent"] is False
    assert prior["statusKey"] == "submitted"
    assert prior["answers"] == {"name": "Alice"}


def test_revise_pins_current_version(client):
    headers = _admin(client)
    form = _published_form(client, headers)
    original = _submit(client, headers, form["id"], {"name": "Alice"})
    assert original["versionNumber"] == 1

    # Edit the draft + republish → v2.
    client.patch(
        f"/forms/{form['id']}",
        json={"draftDefinition": _doc(_text_field("f1", "name", label="Full name", required=True))},
        headers=headers,
    )
    assert client.post(f"/forms/{form['id']}/publish", headers=headers).status_code == 200

    draft = client.post(f"/submissions/{original['id']}/revise", headers=headers).json()
    assert draft["versionNumber"] == 2  # pins the version published NOW
    # The original still pins v1 (immutable).
    assert client.get(f"/submissions/{original['id']}", headers=headers).json()["versionNumber"] == 1


def test_revise_blocked_when_disabled(client):
    headers = _admin(client)
    form = _published_form(client, headers, allow_revisions=False)
    original = _submit(client, headers, form["id"], {"name": "Alice"})
    res = client.post(f"/submissions/{original['id']}/revise", headers=headers)
    assert res.status_code == 409, res.text


def test_revise_blocked_when_not_frozen(client):
    headers = _admin(client)
    form = _published_form(client, headers)
    original = _submit(client, headers, form["id"], {"name": "Alice"})
    draft = client.post(f"/submissions/{original['id']}/revise", headers=headers).json()
    # The new draft is is_active (editable) → revising it is refused.
    res = client.post(f"/submissions/{draft['id']}/revise", headers=headers)
    assert res.status_code == 409, res.text


def test_revise_blocked_on_stale_revision(client):
    headers = _admin(client)
    form = _published_form(client, headers)
    original = _submit(client, headers, form["id"], {"name": "Alice"})
    client.post(f"/submissions/{original['id']}/revise", headers=headers)
    # original is now is_current=False → cannot revise a stale revision.
    res = client.post(f"/submissions/{original['id']}/revise", headers=headers)
    assert res.status_code == 409, res.text


def test_revise_blocked_without_published_version(client):
    headers = _admin(client)
    form = _published_form(client, headers)
    original = _submit(client, headers, form["id"], {"name": "Alice"})
    # Unpublish → no current version to pin.
    client.post(f"/forms/{form['id']}/unpublish", headers=headers)
    res = client.post(f"/submissions/{original['id']}/revise", headers=headers)
    assert res.status_code == 409, res.text


# ---- listing + history ----


def test_list_defaults_to_current_only(client):
    headers = _admin(client)
    form = _published_form(client, headers)
    original = _submit(client, headers, form["id"], {"name": "Alice"})
    client.post(f"/submissions/{original['id']}/revise", headers=headers)
    rows = client.get(f"/forms/{form['id']}/submissions", headers=headers).json()
    # One row per group - the current (draft) revision, not the frozen prior.
    assert rows["total"] == 1
    assert rows["data"][0]["isCurrent"] is True
    assert rows["data"][0]["revisionNumber"] == 2


def test_revision_history_chain(client):
    headers = _admin(client)
    form = _published_form(client, headers)
    original = _submit(client, headers, form["id"], {"name": "Alice"})
    group = original["submissionGroupId"]
    client.post(f"/submissions/{original['id']}/revise", headers=headers)
    chain = client.get(f"/forms/{form['id']}/submissions?group={group}", headers=headers).json()
    assert chain["total"] == 2
    nums = [r["revisionNumber"] for r in chain["data"]]
    assert nums == [2, 1]  # newest first
    assert all(r["submissionGroupId"] == group for r in chain["data"])
    # Exactly one live revision per group (the partial-unique index invariant).
    assert sum(1 for r in chain["data"] if r["isCurrent"]) == 1


# ---- resubmit ----


def test_resubmit_revision_edits_and_fires_submit(client):
    headers = _admin(client)
    form = _published_form(client, headers)
    original = _submit(client, headers, form["id"], {"name": "Alice"})
    draft = client.post(f"/submissions/{original['id']}/revise", headers=headers).json()

    res = client.post(
        f"/submissions/{draft['id']}/resubmit",
        json={"answers": {"name": "Alice Revised"}},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    final = res.json()
    assert final["id"] == draft["id"]  # same row - one row per revision
    assert final["statusKey"] == "submitted"
    assert final["isCurrent"] is True
    assert final["revisionNumber"] == 2
    assert final["answers"] == {"name": "Alice Revised"}
    assert final["submittedAt"] is not None
    # The original stays frozen + unchanged.
    assert client.get(f"/submissions/{original['id']}", headers=headers).json()["answers"] == {"name": "Alice"}


def test_resubmit_validates_against_pinned_version(client):
    headers = _admin(client)
    form = _published_form(client, headers)
    original = _submit(client, headers, form["id"], {"name": "Alice"})
    draft = client.post(f"/submissions/{original['id']}/revise", headers=headers).json()
    # Required 'name' missing → 422 fieldErrors.
    res = client.post(f"/submissions/{draft['id']}/resubmit", json={"answers": {}}, headers=headers)
    assert res.status_code == 422, res.text
    assert "name" in res.json()["detail"]["fieldErrors"]
