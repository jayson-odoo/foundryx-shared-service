"""Ideation round 2 (#94) - merge and unmerge: data + API (AC-94-01..20).

TEST-FIRST (PRINCIPLES.md): written BEFORE `IdeaMergeService`, the merge/
unmerge/merged-listing routes and the `Idea.merged_into_id`/`merged_at` /
`IdeaVote.origin_idea_id` columns exist (plan section 3, slices S2/S3).
Every test here is expected to fail - a missing route (404, generic
Starlette shape), a missing response key (`KeyError`), or a missing ORM
column/attribute - until those slices land.

`documentation/plans/ideation/PLAN-ideation-round-2-merge-unmerge.md` section 3
+ `documentation/plans/ideation/ideation-round-2-merge-unmerge-acceptance-criteria.md`
group A.
"""
import csv
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.sql import func

from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from app.security import hash_password
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

MODULE_ROOT = Path(__file__).resolve().parents[1] / "modules" / "ideation"
VERSIONS_DIR = MODULE_ROOT / "alembic" / "versions"

# The framework's bare "route does not exist" 404 body - distinct from a real,
# business-logic 404 the merge/unmerge routes raise once they exist
# (`HTTPException(404, "...")`). Asserting `!= ROUTING_404` alongside a 404
# status keeps a "cross-tenant -> 404" assertion honestly red today (the route
# is simply missing) instead of accidentally passing for the wrong reason.
ROUTING_404 = {"detail": "Not Found"}


# ── fixtures / helpers ────────────────────────────────────────────────────────


@pytest.fixture
def ideation_client(ideation_session_factory):
    def override_get_db():
        db = ideation_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c._factory = ideation_session_factory
        yield c
    app.dependency_overrides.clear()


def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD) -> str:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _create_software_product(client, h, name="Sorento CRM") -> str:
    res = client.post("/products", headers=h, json={"name": name, "kind": "software"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _make_user(factory, email, password, perm_keys):
    from app.models import Role, User, UserStatus
    from app.models.permission import Permission

    db = factory()
    try:
        perms = db.query(Permission).filter(Permission.key.in_(list(perm_keys))).all()
        role = Role(
            tenant_id=DEFAULT_TENANT_ID,
            name=f"Role-{email}",
            description="Test role",
            is_system=False,
        )
        role.permissions = perms
        db.add(role)
        db.flush()
        user = User(
            tenant_id=DEFAULT_TENANT_ID,
            email=email,
            password=hash_password(password),
            name="Test User",
            status=UserStatus.ACTIVE.value,
            email_verified_at=func.now(),
        )
        user.roles = [role]
        db.add(user)
        db.commit()
    finally:
        db.close()


def _insert_idea(
    factory,
    product_id,
    *,
    problem="Let CS export orders to Excel",
    status_key="captured",
    tenant_id=DEFAULT_TENANT_ID,
    is_test=False,
    priority=0,
    idea_number=None,
    status_token=None,
    submitter_contact_id=None,
    submitter_name=None,
    created_at=None,
) -> str:
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import idea_status_id

    db = factory()
    try:
        kwargs = dict(
            tenant_id=tenant_id,
            product_id=product_id,
            status_id=idea_status_id(db, status_key, tenant_id),
            intake_definition_key="ideation",
            problem=problem,
            raw_text=problem,
            source="whatsapp",
            is_test=is_test,
            priority=priority,
            idea_number=idea_number,
            status_token=status_token,
            submitter_contact_id=submitter_contact_id,
            submitter_name=submitter_name,
            captured_json={"problem": problem},
        )
        if created_at is not None:
            kwargs["created_at"] = created_at
        idea = Idea(**kwargs)
        db.add(idea)
        db.commit()
        return idea.id
    finally:
        db.close()


def _idea_row(factory, idea_id):
    from modules.ideation.models import Idea

    db = factory()
    try:
        return db.query(Idea).filter(Idea.id == idea_id).first()
    finally:
        db.close()


def _vote(factory, idea_id, voter_id, dir="up"):
    from modules.ideation.models import IdeaVote

    db = factory()
    try:
        db.add(
            IdeaVote(tenant_id=DEFAULT_TENANT_ID, idea_id=idea_id, voter_id=voter_id, dir=dir)
        )
        db.commit()
    finally:
        db.close()


def _merge(client, h, survivor_id, idea_ids):
    return client.post(
        "/ideation/ideas/merge", headers=h, json={"survivorId": survivor_id, "ideaIds": idea_ids}
    )


def _unmerge(client, h, idea_id):
    return client.post(f"/ideation/ideas/{idea_id}/unmerge", headers=h)


# ── AC-94-01 ───────────────────────────────────────────────────────────────


def test_merge_sets_pointer_and_count(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, problem="A")
    b = _insert_idea(ideation_client._factory, pid, problem="B")
    c = _insert_idea(ideation_client._factory, pid, problem="C")

    res = _merge(ideation_client, h, a, [a, b, c])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == a
    assert body["mergedCount"] == 2

    row_a = _idea_row(ideation_client._factory, a)
    row_b = _idea_row(ideation_client._factory, b)
    row_c = _idea_row(ideation_client._factory, c)
    assert row_a.merged_into_id is None
    assert row_b.merged_into_id == a and row_b.merged_at is not None
    assert row_c.merged_into_id == a and row_c.merged_at is not None


# ── AC-94-02 ───────────────────────────────────────────────────────────────


def test_list_and_board_hide_merged_children(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, problem="A")
    b = _insert_idea(ideation_client._factory, pid, problem="B")
    c = _insert_idea(ideation_client._factory, pid, problem="C")
    assert _merge(ideation_client, h, a, [a, b, c]).status_code == 200

    for filter_ in ("active", "archived", "all"):
        listed = ideation_client.get("/ideation/ideas", headers=h, params={"filter": filter_})
        assert listed.status_code == 200, listed.text
        rows = listed.json()
        ids = {r["id"] for r in rows}
        assert b not in ids and c not in ids
        if filter_ in ("active", "all"):
            assert a in ids
            row = next(r for r in rows if r["id"] == a)
            assert row["mergedCount"] == 2

    board = ideation_client.get("/ideation/ideas/board", headers=h)
    assert board.status_code == 200, board.text
    all_ids = {i["id"] for col in board.json()["columns"] for i in col["ideas"]}
    assert b not in all_ids and c not in all_ids


# ── AC-94-03 ───────────────────────────────────────────────────────────────


def test_child_detail_and_merged_listing(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, problem="A")
    b = _insert_idea(ideation_client._factory, pid, problem="B")
    c = _insert_idea(ideation_client._factory, pid, problem="C")
    assert _merge(ideation_client, h, a, [a, b, c]).status_code == 200

    got_b = ideation_client.get(f"/ideation/ideas/{b}", headers=h)
    assert got_b.status_code == 200, got_b.text
    body_b = got_b.json()
    assert body_b["mergedIntoId"] == a
    assert body_b["mergedInto"]["id"] == a
    assert "ideaNumber" in body_b["mergedInto"]
    assert "title" in body_b["mergedInto"]

    merged = ideation_client.get(f"/ideation/ideas/{a}/merged", headers=h)
    assert merged.status_code == 200, merged.text
    assert [r["id"] for r in merged.json()] == [b, c]  # oldest merge first


# ── AC-94-04 (parametrized, 7 cases) ─────────────────────────────────────────


def _snapshot(factory, ids):
    from modules.ideation.models import Idea

    db = factory()
    try:
        rows = db.query(Idea).filter(Idea.id.in_(ids)).all()
        return {r.id: (r.merged_into_id, r.merged_at) for r in rows}
    finally:
        db.close()


def _case_too_few(client, h, factory, pid):
    a = _insert_idea(factory, pid, problem="only one")
    return a, [a], 422


def _case_survivor_not_in_list(client, h, factory, pid):
    a = _insert_idea(factory, pid, problem="a")
    b = _insert_idea(factory, pid, problem="b")
    d = _insert_idea(factory, pid, problem="d")
    return d, [a, b], 422


def _case_mixed_product(client, h, factory, pid):
    other_pid = _create_software_product(client, h, name="Other Product")
    a = _insert_idea(factory, pid, problem="a")
    b = _insert_idea(factory, other_pid, problem="b")
    return a, [a, b], 422


def _case_mixed_test_real(client, h, factory, pid):
    a = _insert_idea(factory, pid, problem="a", is_test=False)
    b = _insert_idea(factory, pid, problem="b", is_test=True)
    return a, [a, b], 422


def _case_archived_member(client, h, factory, pid):
    a = _insert_idea(factory, pid, problem="a")
    b = _insert_idea(factory, pid, problem="b", status_key="archived")
    return a, [a, b], 422


def _case_already_merged_member(client, h, factory, pid):
    a = _insert_idea(factory, pid, problem="a")
    b = _insert_idea(factory, pid, problem="b")
    res = _merge(client, h, a, [a, b])
    assert res.status_code == 200, res.text
    d = _insert_idea(factory, pid, problem="d")
    return d, [d, b], 422  # b is already a merged child


def _case_other_tenant(client, h, factory, pid):
    a = _insert_idea(factory, pid, problem="a")
    other = _insert_idea(factory, pid, problem="other tenant", tenant_id="tenant-x")
    return a, [a, other], 404


MERGE_INVALID_CASES = [
    ("too_few", _case_too_few),
    ("survivor_not_in_list", _case_survivor_not_in_list),
    ("mixed_product", _case_mixed_product),
    ("mixed_test_real", _case_mixed_test_real),
    ("archived_member", _case_archived_member),
    ("already_merged_member", _case_already_merged_member),
    ("other_tenant", _case_other_tenant),
]


@pytest.mark.parametrize("name, build", MERGE_INVALID_CASES)
def test_merge_rejects_invalid_selection(ideation_client, name, build):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    survivor_id, idea_ids, expected_status = build(ideation_client, h, ideation_client._factory, pid)
    before = _snapshot(ideation_client._factory, idea_ids)

    res = _merge(ideation_client, h, survivor_id, idea_ids)
    assert res.status_code == expected_status, f"{name}: {res.text}"
    if expected_status == 404:
        assert res.json() != ROUTING_404, f"{name}: got the bare routing 404, not a real one"
    after = _snapshot(ideation_client._factory, idea_ids)
    assert before == after, f"{name}: a row was written on a rejected merge"


# ── AC-94-05 ───────────────────────────────────────────────────────────────


def test_merge_flattens_existing_group(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, problem="a")
    b = _insert_idea(ideation_client._factory, pid, problem="b")
    d = _insert_idea(ideation_client._factory, pid, problem="d")

    assert _merge(ideation_client, h, a, [a, b]).status_code == 200
    res2 = _merge(ideation_client, h, d, [a, d])
    assert res2.status_code == 200, res2.text

    row_a = _idea_row(ideation_client._factory, a)
    row_b = _idea_row(ideation_client._factory, b)
    assert row_a.merged_into_id == d
    assert row_b.merged_into_id == d  # flattened - no chain (b never points at a)


# ── AC-94-06 ───────────────────────────────────────────────────────────────


def test_votes_move_and_return(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, problem="a")
    b = _insert_idea(ideation_client._factory, pid, problem="b")
    _vote(ideation_client._factory, b, "voter-1", "up")
    _vote(ideation_client._factory, a, "voter-2", "up")
    _vote(ideation_client._factory, b, "voter-2", "up")

    res = _merge(ideation_client, h, a, [a, b])
    assert res.status_code == 200, res.text
    assert res.json()["upvotes"] == 2  # voter-1 (moved) + voter-2 (already on A)

    from modules.ideation.models import IdeaVote

    db = ideation_client._factory()
    try:
        v1 = (
            db.query(IdeaVote)
            .filter(IdeaVote.idea_id == a, IdeaVote.voter_id == "voter-1")
            .first()
        )
        assert v1 is not None and v1.origin_idea_id == b
        shadowed = (
            db.query(IdeaVote)
            .filter(IdeaVote.idea_id == b, IdeaVote.voter_id == "voter-2")
            .first()
        )
        assert shadowed is not None  # left in place, shadowed
    finally:
        db.close()

    unres = _unmerge(ideation_client, h, b)
    assert unres.status_code == 200, unres.text
    db = ideation_client._factory()
    try:
        v1_after = (
            db.query(IdeaVote)
            .filter(IdeaVote.idea_id == b, IdeaVote.voter_id == "voter-1")
            .first()
        )
        assert v1_after is not None and v1_after.origin_idea_id is None
    finally:
        db.close()
    row_a = _idea_row(ideation_client._factory, a)
    row_b = _idea_row(ideation_client._factory, b)
    assert row_a.upvotes == 1
    assert row_b.upvotes == 2  # voter-1 returned + voter-2 shadow kept (D4 lossless)


def test_votes_survive_flatten_and_full_unmerge(ideation_client):
    """Review round 1 #3 (D4 lossless under flatten): C merged into M stamps
    V's vote origin=C on M; M then merges into S, which ALREADY has V - the
    OLD code left V's origin=C row stranded on M (a node nobody inspects
    again once M itself becomes a frozen child): M would wrongly keep
    counting it forever, and unmerging C would never find it. The fix
    relocates it straight back to its TRUE origin (C) when a survivor
    collision blocks the normal move. Also exercises the ordinary
    (non-inherited) path: W's own direct vote on M moves normally onto S."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    m = _insert_idea(ideation_client._factory, pid, problem="m")
    c = _insert_idea(ideation_client._factory, pid, problem="c")
    s = _insert_idea(ideation_client._factory, pid, problem="s")

    _vote(ideation_client._factory, c, "voter-v", "up")
    assert _merge(ideation_client, h, m, [m, c]).status_code == 200

    _vote(ideation_client._factory, s, "voter-v", "up")  # S already has V
    _vote(ideation_client._factory, m, "voter-w", "up")  # M's own direct voter

    res = _merge(ideation_client, h, s, [s, m])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["upvotes"] == 2  # voter-v (direct) + voter-w (moved, origin=m)
    assert body["mergedCount"] == 2  # m + c (flattened onto s directly)

    row_s = _idea_row(ideation_client._factory, s)
    row_m = _idea_row(ideation_client._factory, m)
    row_c = _idea_row(ideation_client._factory, c)
    assert row_s.upvotes == 2
    assert row_m.upvotes == 0  # V's inherited vote relocated away, nothing left
    assert row_c.upvotes == 1  # V's vote correctly resident back on C
    assert row_c.merged_into_id == s  # flattened straight onto S, not M

    from modules.ideation.models import IdeaVote

    db = ideation_client._factory()
    try:
        v_on_c = (
            db.query(IdeaVote)
            .filter(IdeaVote.idea_id == c, IdeaVote.voter_id == "voter-v")
            .first()
        )
        assert v_on_c is not None and v_on_c.origin_idea_id is None
    finally:
        db.close()

    # Unmerge C: nothing to move (V's vote was never stamped at S), tallies
    # unaffected.
    unres_c = _unmerge(ideation_client, h, c)
    assert unres_c.status_code == 200, unres_c.text
    row_s = _idea_row(ideation_client._factory, s)
    row_c = _idea_row(ideation_client._factory, c)
    assert row_c.upvotes == 1
    assert row_s.upvotes == 2
    assert row_c.merged_into_id is None

    # Unmerge M: W's moved vote returns.
    unres_m = _unmerge(ideation_client, h, m)
    assert unres_m.status_code == 200, unres_m.text
    row_s = _idea_row(ideation_client._factory, s)
    row_m = _idea_row(ideation_client._factory, m)
    assert row_m.upvotes == 1  # voter-w returned
    assert row_s.upvotes == 1  # only voter-v's own direct vote left
    assert row_m.merged_into_id is None


# ── AC-94-07 ───────────────────────────────────────────────────────────────


def test_unmerge_child(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, problem="a")
    b = _insert_idea(ideation_client._factory, pid, problem="b", status_key="triaged")
    assert _merge(ideation_client, h, a, [a, b]).status_code == 200

    res = _unmerge(ideation_client, h, b)
    assert res.status_code == 200, res.text
    restored = res.json()
    assert [r["id"] for r in restored] == [b]
    assert restored[0]["status"] == "triaged"  # pre-merge status preserved

    row_b = _idea_row(ideation_client._factory, b)
    assert row_b.merged_into_id is None and row_b.merged_at is None

    got_a = ideation_client.get(f"/ideation/ideas/{a}", headers=h).json()
    assert got_a["mergedCount"] == 0

    listed = ideation_client.get("/ideation/ideas", headers=h).json()
    assert b in {r["id"] for r in listed}


# ── AC-94-08 ───────────────────────────────────────────────────────────────


def test_unmerge_survivor_dissolves_group(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, problem="a")
    b = _insert_idea(ideation_client._factory, pid, problem="b")
    c = _insert_idea(ideation_client._factory, pid, problem="c")
    assert _merge(ideation_client, h, a, [a, b, c]).status_code == 200

    res = _unmerge(ideation_client, h, a)
    assert res.status_code == 200, res.text
    ids = {r["id"] for r in res.json()}
    assert ids == {b, c}

    got_a = ideation_client.get(f"/ideation/ideas/{a}", headers=h).json()
    assert got_a["mergedCount"] == 0


def test_unmerge_plain_idea_422(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, problem="a")
    res = _unmerge(ideation_client, h, a)
    assert res.status_code == 422, res.text
    row_a = _idea_row(ideation_client._factory, a)
    assert row_a.merged_into_id is None


# ── AC-94-09 ───────────────────────────────────────────────────────────────


def test_merged_child_is_frozen(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, problem="a")
    b = _insert_idea(ideation_client._factory, pid, problem="b")
    assert _merge(ideation_client, h, a, [a, b]).status_code == 200

    status_res = ideation_client.post(
        f"/ideation/ideas/{b}/status", headers=h, json={"status": "triaged"}
    )
    assert status_res.status_code == 409, status_res.text

    vote_res = ideation_client.post(f"/ideation/ideas/{b}/vote", headers=h, json={"dir": "up"})
    assert vote_res.status_code == 409, vote_res.text

    br_res = ideation_client.post(
        "/ideation/business-requirements", headers=h, json={"productId": pid, "title": "BR"}
    )
    assert br_res.status_code == 201, br_res.text
    br_id = br_res.json()["id"]
    link_res = ideation_client.post(
        f"/ideation/business-requirements/{br_id}/ideas", headers=h, json={"ideaIds": [b]}
    )
    assert link_res.status_code == 422, link_res.text

    patch_res = ideation_client.patch(
        f"/ideation/ideas/{b}", headers=h, json={"problem": "still editable"}
    )
    assert patch_res.status_code == 200, patch_res.text
    assert patch_res.json()["problem"] == "still editable"


# ── AC-94-10 ───────────────────────────────────────────────────────────────


def test_delete_survivor_restores_children(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, problem="a")
    b = _insert_idea(ideation_client._factory, pid, problem="b")
    c = _insert_idea(ideation_client._factory, pid, problem="c")
    assert _merge(ideation_client, h, a, [a, b, c]).status_code == 200

    res = ideation_client.delete(f"/ideation/ideas/{a}", headers=h)
    assert res.status_code in (200, 204), res.text

    row_b = _idea_row(ideation_client._factory, b)
    row_c = _idea_row(ideation_client._factory, c)
    assert row_b.merged_into_id is None
    assert row_c.merged_into_id is None

    listed = ideation_client.get("/ideation/ideas", headers=h).json()
    ids = {r["id"] for r in listed}
    assert a not in ids
    assert b in ids and c in ids


def test_delete_merged_child_removes_its_stamped_votes_from_survivor(ideation_client):
    """Review round 1 NIT #11: hard-deleting a merged CHILD (not the
    survivor) also removes its stamped vote rows still resident on the
    survivor (``origin_idea_id == the deleted child``) and recounts the
    survivor - a deleted idea can never be un-merged again, so a vote
    stamped with its id must not silently keep counting forever."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, problem="a")
    b = _insert_idea(ideation_client._factory, pid, problem="b")
    _vote(ideation_client._factory, a, "voter-1", "up")
    _vote(ideation_client._factory, b, "voter-2", "up")
    res = _merge(ideation_client, h, a, [a, b])
    assert res.status_code == 200, res.text
    assert res.json()["upvotes"] == 2

    del_res = ideation_client.delete(f"/ideation/ideas/{b}", headers=h)
    assert del_res.status_code in (200, 204), del_res.text

    row_a = _idea_row(ideation_client._factory, a)
    assert row_a.upvotes == 1  # voter-2's stamped vote is gone with b

    from modules.ideation.models import IdeaVote

    db = ideation_client._factory()
    try:
        stray = (
            db.query(IdeaVote)
            .filter(IdeaVote.idea_id == a, IdeaVote.origin_idea_id == b)
            .first()
        )
        assert stray is None
    finally:
        db.close()


# ── AC-94-11 ───────────────────────────────────────────────────────────────


def test_dedup_and_clusters_skip_merged(ideation_client):
    from modules.ideation.services.dedup import DedupService

    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, problem="Export orders to excel for CS")
    b = _insert_idea(ideation_client._factory, pid, problem="Export orders to excel for CS team")
    assert _merge(ideation_client, h, a, [a, b]).status_code == 200

    db = ideation_client._factory()
    try:
        found = DedupService(db).find_duplicate(
            DEFAULT_TENANT_ID, pid, "Export orders to excel for CS team"
        )
        assert found != b
    finally:
        db.close()

    clusters = ideation_client.get(
        "/ideation/ideas/clusters", headers=h, params={"productId": pid}
    )
    assert clusters.status_code == 200, clusters.text
    all_ids = {i["id"] for cluster in clusters.json()["clusters"] for i in cluster["ideas"]}
    assert b not in all_ids


# ── AC-94-12 ───────────────────────────────────────────────────────────────


def test_merge_mints_survivor_identity(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    create_res = ideation_client.post(
        "/ideation/ideas",
        headers=h,
        json={"productId": pid, "problem": "operator authored survivor"},
    )
    assert create_res.status_code == 201, create_res.text
    a = create_res.json()["id"]
    assert create_res.json()["ideaNumber"] is None  # BL-SS-280: no number yet

    b = _insert_idea(ideation_client._factory, pid, problem="b")
    res = _merge(ideation_client, h, a, [a, b])
    assert res.status_code == 200, res.text
    assert res.json()["ideaNumber"] is not None

    row_a = _idea_row(ideation_client._factory, a)
    assert row_a.idea_number is not None
    assert row_a.status_token is not None


# ── AC-94-13 / AC-94-14: see tests/test_ideation_public_status.py ───────────
# ── AC-94-15 ───────────────────────────────────────────────────────────────


def test_merge_tenant_isolation(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, problem="a")
    other = _insert_idea(
        ideation_client._factory, pid, problem="other tenant idea", tenant_id="tenant-x"
    )

    res = _merge(ideation_client, h, a, [a, other])
    assert res.status_code == 404, res.text
    assert res.json() != ROUTING_404
    row_other = _idea_row(ideation_client._factory, other)
    assert row_other.merged_into_id is None

    res2 = _merge(ideation_client, h, other, [a, other])
    assert res2.status_code == 404, res2.text
    row_a = _idea_row(ideation_client._factory, a)
    assert row_a.merged_into_id is None


def test_merged_into_never_resolves_a_foreign_tenant_row(ideation_client):
    """Review round 1 BLOCKER #2: ``_merge_maps`` resolved ``merged_into_id``
    and the grouped ``mergedCount`` with unscoped queries - a stored
    ``merged_into_id`` is a polymorphic stored id (the notification_recipients
    lesson) and must be resolved tenant-scoped even when the pointer is
    forged/corrupted, never trusted unscoped. Forge idea A's pointer to a
    REAL row that lives in another tenant (never reachable through the real
    ``merge()`` path - this simulates a corrupted stored id to prove the read
    side never resolves it unscoped)."""
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, problem="a")
    foreign = _insert_idea(
        ideation_client._factory, pid, problem="foreign tenant idea", tenant_id="tenant-x"
    )

    from modules.ideation.models import Idea

    db = ideation_client._factory()
    try:
        row = db.query(Idea).filter(Idea.id == a).first()
        row.merged_into_id = foreign
        db.commit()
    finally:
        db.close()

    got = ideation_client.get(f"/ideation/ideas/{a}", headers=h)
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["mergedIntoId"] == foreign  # the raw stored pointer is not hidden
    assert body["mergedInto"] is None  # but it never resolves the foreign row

    # The foreign tenant's own read of its row must not show a bogus
    # mergedCount either (the grouped count is tenant scoped on both sides).
    db = ideation_client._factory()
    try:
        from modules.ideation.services.ideas import IdeaReadService

        foreign_out = IdeaReadService(db).get("tenant-x", foreign)
        assert foreign_out.mergedCount == 0
    finally:
        db.close()


# ── AC-94-16: see tests/test_ideation_embed_writes.py ───────────────────────
# ── AC-94-17 ───────────────────────────────────────────────────────────────


def test_merge_requires_triage_manage(ideation_client):
    _make_user(
        ideation_client._factory, "notriage@example.com", "notriage1234", {"ideation.ideas.view"}
    )
    h_admin = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h_admin)
    a = _insert_idea(ideation_client._factory, pid, problem="a")
    b = _insert_idea(ideation_client._factory, pid, problem="b")
    h = _auth(ideation_client, email="notriage@example.com", password="notriage1234")

    res = _merge(ideation_client, h, a, [a, b])
    assert res.status_code == 403, res.text

    unres = _unmerge(ideation_client, h, a)
    assert unres.status_code == 403, unres.text

    # No new permission key added for merge/unmerge (D7).
    csv_path = MODULE_ROOT / "permissions" / "permissions.csv"
    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))
    assert not any("merge" in (row.get("key") or "").lower() for row in rows)


# ── AC-94-18 ───────────────────────────────────────────────────────────────


def test_migration_0012_head_and_revision_length():
    import importlib.util

    path = VERSIONS_DIR / "0012_ideation_merge_rank_events.py"
    assert path.exists(), f"missing migration file: {path}"
    spec = importlib.util.spec_from_file_location("_ideation_rev_0012", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "0011_ideation_br_is_test"
    assert len(module.revision) <= 32

    # Single head, derived from the code (never a hardcoded id): no other
    # version file also names its own down_revision equal to a revision no
    # one else points at except one - i.e. exactly one revision is nobody's
    # down_revision.
    all_revisions = set()
    down_revisions = set()
    for f in VERSIONS_DIR.glob("*.py"):
        spec2 = importlib.util.spec_from_file_location(f"_ideation_rev_{f.stem}", f)
        mod2 = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(mod2)
        all_revisions.add(mod2.revision)
        if mod2.down_revision:
            down_revisions.add(mod2.down_revision)
    true_heads = all_revisions - down_revisions
    assert len(true_heads) == 1, f"expected a single ideation migration head, found {true_heads}"
    # 0013 (attachment upload) is now the head by design; 0012 stays in the chain.
    assert true_heads == {"0013_ideation_attachment_upload"}
    assert len(next(iter(true_heads))) <= 32
    assert module.revision in all_revisions


# ── AC-94-19 ───────────────────────────────────────────────────────────────


def test_reorder_skips_merged_children(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, problem="a", priority=0)
    b = _insert_idea(ideation_client._factory, pid, problem="b", priority=1)
    c = _insert_idea(ideation_client._factory, pid, problem="c", priority=2)
    assert _merge(ideation_client, h, a, [a, b]).status_code == 200

    before_b = _idea_row(ideation_client._factory, b).priority
    res = ideation_client.put(
        "/ideation/ideas/reorder", headers=h, json={"orderedIds": [c, b, a]}
    )
    assert res.status_code == 200, res.text
    after_b = _idea_row(ideation_client._factory, b).priority
    assert after_b == before_b  # untouched - b is a merged child


# ── AC-94-20 ───────────────────────────────────────────────────────────────


def test_unmerge_restores_position(ideation_client):
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    a = _insert_idea(ideation_client._factory, pid, problem="a", priority=0)
    _insert_idea(ideation_client._factory, pid, problem="b", priority=1)
    c = _insert_idea(ideation_client._factory, pid, problem="c", priority=2)
    _insert_idea(ideation_client._factory, pid, problem="d", priority=3)

    before_c = _idea_row(ideation_client._factory, c).priority
    assert _merge(ideation_client, h, a, [a, c]).status_code == 200
    res = _unmerge(ideation_client, h, c)
    assert res.status_code == 200, res.text
    after_c = _idea_row(ideation_client._factory, c).priority
    assert after_c == before_c  # no forced append - back at its stored priority
