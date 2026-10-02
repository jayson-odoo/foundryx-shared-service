"""SS-IDEATION-OWN - the own-idea contract for the sorento chatbot (IDEATION-CAPTURE).

Covers (red-first):

- One-shot intake create ``POST /ideation/intake/ideas`` returns the idea id AND
  its ``idea_number`` (``IDEA-0001``…, minted by the same completion sink the
  turn flow uses). The sender must be a CRM user (``submitter_crm_user_id``).
- Own-similar lookup ``POST /ideation/intake/ideas/similar-own``: ideas of the SAME
  submitter only (phone or CRM user id, NEVER name), live ideas only, top 3,
  pg_trgm / difflib similarity at the existing dedup threshold.
- Embed ``GET /embed/ideas?mine=true`` + an ``isMine`` flag on every embed idea,
  computed for the viewing CRM user (assertion ``sub`` + optional ``phone`` claim).
- Optional ``ideas_manage`` assertion claim: when explicitly ``false`` the embed
  refuses edits/status/delete/reorder on ideas that are not the viewer's own.
"""
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from tests.test_ideation_create_idea import (
    _key_auth,
    _make_contact,
    _mint_key,
)
from tests.test_ideation_embed import (  # noqa: F401 - fixture re-export
    AUD,
    CONNECTION_ID,
    SIGNING_SECRET,
    _auth,
    _create_software_product,
    ideation_client,
)

PHONE = "+60123456789"
OTHER_PHONE = "+60198765432"


# ── helpers ───────────────────────────────────────────────────────────────────
def _seed_connection(factory, product_id=None, tenant_id=DEFAULT_TENANT_ID):
    from modules.ideation.services.embed import upsert_connection

    db = factory()
    try:
        upsert_connection(
            db,
            connection_id=CONNECTION_ID,
            tenant_id=tenant_id,
            signing_secret=SIGNING_SECRET,
            allowed_origins=["https://fe-sorento.foundryx.my"],
            product_id=product_id,
        )
    finally:
        db.close()


def _assertion(sub="crm-1", phone=None, ideas_manage=None, name="Alice"):
    now = datetime.now(timezone.utc)
    payload = {
        "typ": "assertion",
        "aud": AUD,
        "iss": "sorento",
        "sub": sub,
        "email": "a@sorento.my",
        "name": name,
        "connection_id": CONNECTION_ID,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=120)).timestamp()),
    }
    if phone is not None:
        payload["phone"] = phone
    if ideas_manage is not None:
        payload["ideas_manage"] = ideas_manage
    return jwt.encode(payload, SIGNING_SECRET, algorithm=settings.jwt_algorithm)


def _embed_h(client, **kw) -> dict:
    res = client.post(
        "/embed/session",
        json={"connection_id": CONNECTION_ID, "assertion": _assertion(**kw)},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _one_shot(client, key, product_id, **over):
    body = {
        "product_id": product_id,
        "problem": "Let CS export orders to Excel",
        "title": "Excel export",
        "proposed_solution": "Export button on the orders list",
        "impact": "Saves 30 minutes a day",
        "department": "Customer Service",
        "submitter_phone": PHONE,
        "submitter_crm_user_id": "crm-1",
        "submitter_name": "Jayson Tan",
    }
    body.update(over)
    body = {k: v for k, v in body.items() if v is not None}
    return client.post("/ideation/intake/ideas", headers=_key_auth(key), json=body)


def _similar(client, key, product_id, text, **ident):
    body = {"product_id": product_id, "text": text}
    body.update(ident)
    return client.post(
        "/ideation/intake/ideas/similar-own", headers=_key_auth(key), json=body
    )


def _insert_idea(
    factory,
    product_id,
    *,
    problem,
    status_key="captured",
    crm_user_id=None,
    contact_id=None,
    submitter_name=None,
    created_at=None,
    tenant_id=DEFAULT_TENANT_ID,
):
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import idea_status_id

    db = factory()
    try:
        idea = Idea(
            tenant_id=tenant_id,
            product_id=product_id,
            status_id=idea_status_id(db, status_key),
            intake_definition_key="ideation",
            problem=problem,
            raw_text=problem,
            source="whatsapp",
            submitter_crm_user_id=crm_user_id,
            submitter_contact_id=contact_id,
            submitter_name=submitter_name,
        )
        if created_at is not None:
            idea.created_at = created_at
        db.add(idea)
        db.commit()
        return idea.id
    finally:
        db.close()


def _contact(factory, phone, tenant_id=DEFAULT_TENANT_ID, digits=None):
    """A contact row, optionally with ``phone_digits`` stamped (None = legacy)."""
    from modules.omnichannel.models import Contact, Workspace

    db = factory()
    try:
        ws = db.query(Workspace).filter(Workspace.tenant_id == DEFAULT_TENANT_ID).first()
        c = Contact(
            tenant_id=tenant_id,
            workspace_id=ws.id,
            first_name="X",
            phone=phone,
            phone_digits=digits,
        )
        db.add(c)
        db.commit()
        return c.id
    finally:
        db.close()


@pytest.fixture
def ctx(ideation_client):
    h = _auth(ideation_client)
    product_id = _create_software_product(ideation_client, h)
    key = _mint_key(ideation_client._factory)
    return ideation_client, h, product_id, key


# ── 1. one-shot create ───────────────────────────────────────────────────────
def test_one_shot_create_returns_id_and_number(ctx):
    client, h, product_id, key = ctx
    res = _one_shot(client, key, product_id)
    assert res.status_code == 201, res.text
    body = res.json()
    assert set(body) == {"idea_id", "idea_number", "status", "title", "link"}
    assert body["idea_id"]
    assert body["idea_number"] == "IDEA-0001"
    assert body["status"] == "captured"
    assert body["title"] == "Excel export"
    assert body["link"]  # public status link (status_token minted by the sink)

    res2 = _one_shot(client, key, product_id, problem="Bulk-print delivery orders")
    assert res2.json()["idea_number"] == "IDEA-0002"

    detail = client.get(f"/ideation/ideas/{body['idea_id']}", headers=h).json()
    assert detail["ideaNumber"] == "IDEA-0001"
    assert detail["status"] == "captured"
    assert detail["submitterName"] == "Jayson Tan"
    assert detail["proposedSolution"] == "Export button on the orders list"


def test_one_shot_create_links_submitter_contact_and_crm_user(ctx):
    client, _h, product_id, key = ctx
    contact_id = _make_contact(client._factory, phone=PHONE)
    idea_id = _one_shot(client, key, product_id).json()["idea_id"]

    from modules.ideation.models import Idea

    db = client._factory()
    try:
        idea = db.query(Idea).filter(Idea.id == idea_id).one()
        assert idea.submitter_contact_id == contact_id
        assert idea.submitter_crm_user_id == "crm-1"
    finally:
        db.close()


def test_one_shot_create_requires_crm_user(ctx):
    client, _h, product_id, key = ctx
    res = _one_shot(client, key, product_id, submitter_crm_user_id=None)
    assert res.status_code == 422
    res = _one_shot(client, key, product_id, submitter_crm_user_id="   ")
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "submitter_required"


def test_one_shot_create_rejects_blank_problem(ctx):
    client, _h, product_id, key = ctx
    res = _one_shot(client, key, product_id, problem="   ")
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "problem_required"


def test_one_shot_create_rejects_long_title_and_junk_phone(ctx):
    client, _h, product_id, key = ctx
    res = _one_shot(client, key, product_id, title="one two three four five six seven eight nine")
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "title_too_long"
    res = _one_shot(client, key, product_id, submitter_phone="12")
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "invalid_phone"


def test_one_shot_create_is_idempotent_on_intake_ref(ctx):
    client, _h, product_id, key = ctx
    first = _one_shot(client, key, product_id, intake_ref="msg-1")
    again = _one_shot(client, key, product_id, intake_ref="msg-1", problem="retry body")
    assert first.status_code == 201 and again.status_code == 201
    assert again.json() == first.json()
    # the retry did not burn a number
    assert _one_shot(client, key, product_id, intake_ref="msg-2").json()["idea_number"] == "IDEA-0002"
    # the same key from a different submitter is refused, never replayed
    clash = _one_shot(client, key, product_id, intake_ref="msg-1", submitter_crm_user_id="crm-2")
    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "intake_ref_conflict"


def test_one_shot_create_matches_formatted_stored_phone(ctx):
    client, _h, product_id, key = ctx
    legacy = _contact(client._factory, "+60 12-345 6789")  # phone_digits not stamped
    idea_id = _one_shot(client, key, product_id).json()["idea_id"]

    from modules.ideation.models import Idea

    db = client._factory()
    try:
        assert db.query(Idea).filter(Idea.id == idea_id).one().submitter_contact_id == legacy
    finally:
        db.close()


def test_one_shot_create_new_contact_is_stamped(ctx):
    client, _h, product_id, key = ctx
    idea_id = _one_shot(client, key, product_id, submitter_phone="+60 19-999 8888").json()["idea_id"]

    from modules.ideation.models import Idea
    from modules.omnichannel.models import Contact

    db = client._factory()
    try:
        cid = db.query(Idea).filter(Idea.id == idea_id).one().submitter_contact_id
        contact = db.query(Contact).filter(Contact.id == cid).one()
        assert contact.phone == "+60199998888"
        assert contact.phone_digits == "60199998888"
    finally:
        db.close()


def test_one_shot_create_unknown_product_and_auth(ctx):
    client, _h, _product_id, key = ctx
    assert _one_shot(client, key, "nope").status_code == 404
    res = client.post("/ideation/intake/ideas", json={"product_id": "x", "problem": "y"})
    assert res.status_code == 401


def test_one_shot_create_persists_attachments(ctx):
    client, h, product_id, key = ctx
    res = _one_shot(
        client,
        key,
        product_id,
        attachments=[
            {"type": "image", "url": "https://r2.example/a.png", "source_msg_id": "m1"}
        ],
    )
    detail = client.get(f"/ideation/ideas/{res.json()['idea_id']}", headers=h).json()
    assert [a["url"] for a in detail["attachments"]] == ["https://r2.example/a.png"]


# ── 3. own-similar lookup ────────────────────────────────────────────────────
def test_similar_own_matches_same_phone_only(ctx):
    client, _h, product_id, key = ctx
    mine = _make_contact(client._factory, phone=PHONE)
    other = _make_contact(client._factory, first_name="Bob", phone=OTHER_PHONE)
    own_id = _insert_idea(
        client._factory, product_id, problem="Export orders to Excel", contact_id=mine
    )
    _insert_idea(
        client._factory, product_id, problem="Export orders to Excel file", contact_id=other
    )

    res = _similar(client, key, product_id, "export orders to excel", submitter_phone=PHONE)
    assert res.status_code == 200, res.text
    matches = res.json()["matches"]
    assert [m["idea_id"] for m in matches] == [own_id]
    m = matches[0]
    assert set(m) == {
        "idea_id", "idea_number", "title", "problem", "status",
        "status_label", "similarity", "created_at", "link",
    }
    assert m["status"] == "captured"
    assert m["created_at"].endswith("Z")


def test_similar_own_phone_format_tolerant(ctx):
    client, _h, product_id, key = ctx
    mine = _make_contact(client._factory, phone="60123456789")
    own_id = _insert_idea(
        client._factory, product_id, problem="Export orders to Excel", contact_id=mine
    )
    res = _similar(client, key, product_id, "export orders to excel", submitter_phone="+60 12-345 6789")
    assert [m["idea_id"] for m in res.json()["matches"]] == [own_id]


def test_similar_own_matches_stamped_digits(ctx):
    client, _h, product_id, key = ctx
    mine = _contact(client._factory, "+60 12 345 6789", digits="60123456789")
    own_id = _insert_idea(
        client._factory, product_id, problem="Export orders to Excel", contact_id=mine
    )
    res = _similar(client, key, product_id, "export orders to excel", submitter_phone="60123456789")
    assert [m["idea_id"] for m in res.json()["matches"]] == [own_id]


def test_similar_own_and_mine_never_cross_tenants(ctx):
    client, _h, product_id, key = ctx
    _seed_connection(client._factory, product_id=product_id)
    foreign_contact = _contact(client._factory, PHONE, tenant_id="tenant-other", digits="60123456789")
    _insert_idea(
        client._factory,
        product_id,
        problem="Export orders to Excel",
        crm_user_id="crm-1",
        contact_id=foreign_contact,
        tenant_id="tenant-other",
    )
    res = _similar(
        client, key, product_id, "export orders to excel",
        submitter_crm_user_id="crm-1", submitter_phone=PHONE,
    )
    assert res.json()["matches"] == []
    h = _embed_h(client, sub="crm-1", phone=PHONE)
    assert client.get("/embed/ideas?mine=true", headers=h).json() == []


def test_similar_own_matches_crm_user_id(ctx):
    client, _h, product_id, key = ctx
    own_id = _insert_idea(
        client._factory, product_id, problem="Export orders to Excel", crm_user_id="crm-1"
    )
    _insert_idea(
        client._factory, product_id, problem="Export orders to Excel", crm_user_id="crm-2"
    )
    res = _similar(
        client, key, product_id, "export orders to excel", submitter_crm_user_id="crm-1"
    )
    assert [m["idea_id"] for m in res.json()["matches"]] == [own_id]


def test_similar_own_never_matches_by_name(ctx):
    client, _h, product_id, key = ctx
    _insert_idea(
        client._factory,
        product_id,
        problem="Export orders to Excel",
        submitter_name="Jayson Tan",
        crm_user_id="crm-9",
    )
    res = _similar(
        client,
        key,
        product_id,
        "export orders to excel",
        submitter_crm_user_id="crm-1",
        submitter_name="Jayson Tan",
    )
    assert res.json()["matches"] == []


def test_similar_own_requires_an_identity(ctx):
    client, _h, product_id, key = ctx
    _insert_idea(client._factory, product_id, problem="Export orders to Excel")
    res = _similar(client, key, product_id, "export orders to excel")
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "submitter_required"
    # a junk phone (too few digits) is not an identity either
    for junk in ("+", "0", "1234567"):  # fewer than 8 digits is not an identity
        res = _similar(client, key, product_id, "export orders to excel", submitter_phone=junk)
        assert res.status_code == 422, junk


def test_similar_own_live_only_top_three(ctx):
    client, _h, product_id, key = ctx
    base = datetime.now(timezone.utc) - timedelta(days=1)
    live = [
        _insert_idea(
            client._factory,
            product_id,
            problem=f"Export orders to Excel {suffix}",
            crm_user_id="crm-1",
            created_at=base + timedelta(minutes=i),
        )
        for i, suffix in enumerate(["now", "today", "please", "asap"])
    ]
    for key_ in ("draft", "rejected", "duplicate", "archived"):
        _insert_idea(
            client._factory,
            product_id,
            problem="Export orders to Excel",
            crm_user_id="crm-1",
            status_key=key_,
        )
    res = _similar(
        client, key, product_id, "export orders to excel", submitter_crm_user_id="crm-1"
    )
    ids = [m["idea_id"] for m in res.json()["matches"]]
    assert len(ids) == 3
    assert set(ids) <= set(live)


def test_similar_own_scoped_to_product_and_threshold(ctx):
    client, h, product_id, key = ctx
    other_product = _create_software_product(client, h, name="Other product")
    _insert_idea(
        client._factory, other_product, problem="Export orders to Excel", crm_user_id="crm-1"
    )
    _insert_idea(
        client._factory, product_id, problem="Dark mode for the dashboard", crm_user_id="crm-1"
    )
    res = _similar(
        client, key, product_id, "export orders to excel", submitter_crm_user_id="crm-1"
    )
    assert res.json()["matches"] == []


# ── 4. embed mine / isMine ───────────────────────────────────────────────────
def _embed_fixture(ctx):
    client, _h, product_id, _key = ctx
    _seed_connection(client._factory, product_id=product_id)
    mine_contact = _make_contact(client._factory, phone=PHONE)
    other_contact = _make_contact(client._factory, first_name="Bob", phone=OTHER_PHONE)
    by_crm = _insert_idea(client._factory, product_id, problem="A by crm", crm_user_id="crm-1")
    by_phone = _insert_idea(
        client._factory, product_id, problem="B by phone", contact_id=mine_contact
    )
    others = _insert_idea(
        client._factory,
        product_id,
        problem="C other",
        contact_id=other_contact,
        crm_user_id="crm-2",
        submitter_name="Alice",  # same name as the viewer - must NOT count
    )
    return client, by_crm, by_phone, others


def test_embed_is_mine_flags(ctx):
    client, by_crm, by_phone, others = _embed_fixture(ctx)
    h = _embed_h(client, sub="crm-1", phone=PHONE)
    flags = {i["id"]: i["isMine"] for i in client.get("/embed/ideas", headers=h).json()}
    assert flags == {by_crm: True, by_phone: True, others: False}
    assert client.get(f"/embed/ideas/{by_phone}", headers=h).json()["isMine"] is True
    assert client.get(f"/embed/ideas/{others}", headers=h).json()["isMine"] is False
    board = client.get("/embed/board", headers=h).json()
    board_flags = {i["id"]: i["isMine"] for c in board["columns"] for i in c["ideas"]}
    assert board_flags == {by_crm: True, by_phone: True, others: False}


def test_embed_mine_filter(ctx):
    client, by_crm, by_phone, _others = _embed_fixture(ctx)
    h = _embed_h(client, sub="crm-1", phone=PHONE)
    ids = {i["id"] for i in client.get("/embed/ideas?mine=true", headers=h).json()}
    assert ids == {by_crm, by_phone}
    # Without a phone claim only the CRM-user link counts.
    h2 = _embed_h(client, sub="crm-1")
    ids2 = {i["id"] for i in client.get("/embed/ideas?mine=true", headers=h2).json()}
    assert ids2 == {by_crm}


def test_embed_mine_never_leaks_without_identity(ctx):
    client, _by_crm, _by_phone, _others = _embed_fixture(ctx)
    h = _embed_h(client, sub="", phone="+")
    res = client.get("/embed/ideas?mine=true", headers=h).json()
    assert res == []
    flags = [i["isMine"] for i in client.get("/embed/ideas", headers=h).json()]
    assert flags and not any(flags)


def test_embed_create_stamps_crm_user(ctx):
    client, *_ = ctx
    product_id = ctx[2]
    _seed_connection(client._factory, product_id=product_id)
    h = _embed_h(client, sub="crm-7")
    res = client.post("/embed/ideas", headers=h, json={"problem": "Keyboard shortcuts"})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["isMine"] is True
    other = _embed_h(client, sub="crm-8")
    assert client.get(f"/embed/ideas/{body['id']}", headers=other).json()["isMine"] is False


def test_embed_manage_claim_false_blocks_others_ideas(ctx):
    client, by_crm, _by_phone, others = _embed_fixture(ctx)
    h = _embed_h(client, sub="crm-1", phone=PHONE, ideas_manage=False)
    # own idea: editable
    res = client.patch(f"/embed/ideas/{by_crm}", headers=h, json={"impact": "big"})
    assert res.status_code == 200, res.text
    assert res.json()["isMine"] is True
    # someone else's: refused for edit / status / delete / reorder
    assert client.patch(f"/embed/ideas/{others}", headers=h, json={"impact": "x"}).status_code == 403
    assert (
        client.post(f"/embed/ideas/{others}/status", headers=h, json={"status": "triaged"}).status_code
        == 403
    )
    assert client.delete(f"/embed/ideas/{others}", headers=h).status_code == 403
    assert (
        client.put("/embed/ideas/reorder", headers=h, json={"orderedIds": [by_crm, others]}).status_code
        == 403
    )
    assert (
        client.post(
            "/embed/ideas/merge", headers=h, json={"survivorId": by_crm, "ideaIds": [by_crm, others]}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/embed/ideas/{others}/attachments",
            headers=h,
            files={"file": ("a.png", b"\x89PNG\r\n\x1a\n" + b"0" * 16, "image/png")},
        ).status_code
        == 403
    )
    assert client.post(f"/embed/ideas/{others}/unmerge", headers=h).status_code == 403
    # voting on others' ideas stays open
    assert client.post(f"/embed/ideas/{others}/vote", headers=h, json={"dir": "up"}).status_code == 200


def test_embed_manage_claim_false_unmerge_needs_whole_group(ctx):
    client, by_crm, by_phone, others = _embed_fixture(ctx)
    admin = _embed_h(client, sub="crm-admin")  # no claim = legacy manage access
    merged = client.post(
        "/embed/ideas/merge", headers=admin, json={"survivorId": by_crm, "ideaIds": [by_crm, others]}
    )
    assert merged.status_code == 200, merged.text
    h = _embed_h(client, sub="crm-1", phone=PHONE, ideas_manage=False)
    # by_crm is mine, but dissolving it would restore someone else's idea
    assert client.post(f"/embed/ideas/{by_crm}/unmerge", headers=h).status_code == 403
    # an all-mine group can be unmerged
    assert client.post(f"/embed/ideas/{others}/unmerge", headers=admin).status_code == 200
    merged = client.post(
        "/embed/ideas/merge", headers=h, json={"survivorId": by_crm, "ideaIds": [by_crm, by_phone]}
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["isMine"] is True
    assert client.post(f"/embed/ideas/{by_crm}/unmerge", headers=h).status_code == 200


def test_embed_manage_claim_true_or_absent_keeps_legacy_access(ctx):
    client, _by_crm, _by_phone, others = _embed_fixture(ctx)
    for kw in ({"ideas_manage": True}, {}):
        h = _embed_h(client, sub="crm-1", **kw)
        res = client.patch(f"/embed/ideas/{others}", headers=h, json={"impact": "ok"})
        assert res.status_code == 200, res.text
        assert res.json()["isMine"] is False
