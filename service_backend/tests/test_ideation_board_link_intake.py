"""SS-FEEDBACK-BOARD-LINK - the one-shot + own-similar intake APIs hand the
submitter's personal board link back to the host ONLY when the host states it
replies to the submitter themself (``reply_to_submitter: true``). Pairs the
Sorento CRM lane FEEDBACK-PUBLIC-LINK-CRM. RED first.

Owner rulings (16 Nov): Q2 a - board link only when the reply goes to the
submitter themself (never to an operator filing for someone else = security
review #1/B1); Q3 a - test items get no board link.
"""
from app.models import DEFAULT_TENANT_ID
from tests.test_ideation_create_idea import _key_auth, _make_contact
from tests.test_ideation_own import (  # noqa: F401 - fixture re-export
    PHONE,
    _insert_idea,
    _one_shot,
    _similar,
    ctx,
    ideation_client,
)


def _live_token(factory, contact_id):
    from modules.ideation.models import IdeaContactLink

    db = factory()
    try:
        rows = (
            db.query(IdeaContactLink)
            .filter(
                IdeaContactLink.tenant_id == DEFAULT_TENANT_ID,
                IdeaContactLink.contact_id == contact_id,
                IdeaContactLink.revoked_at.is_(None),
            )
            .all()
        )
        assert len(rows) <= 1
        return rows[0].token if rows else None
    finally:
        db.close()


def _n(idea_number):
    # The URL carries the number as users read it (FB-0001), the wire field
    # stays IDEA-0001 (lane FEEDBACK-RENAME).
    return idea_number.replace("IDEA-", "FB-")


def _board_base():
    from app.config import settings

    return f"{settings.frontend_url.rstrip('/')}/public/feedback/board"


# ── 1. one-shot create ───────────────────────────────────────────────────────


def test_one_shot_reply_to_submitter_returns_board_url(ctx):
    client, _h, product_id, key = ctx
    cid = _make_contact(client._factory, first_name="CUSTOMER", last_name="A", phone=PHONE)
    res = _one_shot(client, key, product_id, reply_to_submitter=True)
    assert res.status_code == 201, res.text
    body = res.json()
    token = _live_token(client._factory, cid)
    assert token, "minted link must be committed"
    assert body["board_url"] == f"{_board_base()}/{token}/{_n(body['idea_number'])}"
    # the per-idea track link is unchanged
    assert body["link"] and "/public/feedback/board/" not in body["link"]


def test_one_shot_without_flag_has_no_board_url_and_mints_nothing(ctx):
    client, _h, product_id, key = ctx
    cid = _make_contact(client._factory, first_name="CUSTOMER", last_name="A", phone=PHONE)
    for extra in ({}, {"reply_to_submitter": False}):
        res = _one_shot(client, key, product_id, **extra)
        assert res.status_code == 201, res.text
        body = res.json()
        # an old client gets today's exact key set
        assert set(body) == {"idea_id", "idea_number", "status", "title", "type", "link"}
    assert _live_token(client._factory, cid) is None


def test_one_shot_test_idea_gets_null_board_url(ctx):
    client, _h, product_id, key = ctx
    cid = _make_contact(client._factory, first_name="CUSTOMER", last_name="A", phone=PHONE)
    res = _one_shot(client, key, product_id, reply_to_submitter=True, is_test=True)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["board_url"] is None
    assert body["link"]
    assert _live_token(client._factory, cid) is None


def test_one_shot_no_contact_gets_null_board_url(ctx):
    client, _h, product_id, key = ctx
    res = _one_shot(client, key, product_id, reply_to_submitter=True, submitter_phone=None)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["board_url"] is None
    assert body["link"]


def test_one_shot_two_calls_same_token_and_replay_same_board_url(ctx):
    client, _h, product_id, key = ctx
    _make_contact(client._factory, first_name="CUSTOMER", last_name="A", phone=PHONE)
    first = _one_shot(client, key, product_id, reply_to_submitter=True, intake_ref="r-1").json()
    replay = _one_shot(client, key, product_id, reply_to_submitter=True, intake_ref="r-1").json()
    assert replay == first
    second = _one_shot(
        client, key, product_id, reply_to_submitter=True, problem="Bulk-print delivery orders"
    ).json()
    tok1 = first["board_url"].split("/")[-2]
    tok2 = second["board_url"].split("/")[-2]
    assert tok1 == tok2
    assert second["board_url"].endswith(f"/{_n(second['idea_number'])}")
    # a replay without the flag is the old shape, still the same idea
    old = _one_shot(client, key, product_id, intake_ref="r-1").json()
    assert "board_url" not in old
    assert old["idea_id"] == first["idea_id"] and old["link"] == first["link"]


def test_one_shot_board_url_on_crm_template_base(ctx, monkeypatch):
    from modules.ideation.services import feedback_links

    client, _h, product_id, key = ctx
    cid = _make_contact(client._factory, first_name="CUSTOMER", last_name="A", phone=PHONE)
    monkeypatch.setattr(
        feedback_links,
        "tenant_public_link_base",
        lambda db, tid: "https://crm.example.test/portal/ideas/{token}",
    )
    body = _one_shot(client, key, product_id, reply_to_submitter=True).json()
    token = _live_token(client._factory, cid)
    assert body["board_url"] == f"https://crm.example.test/feedback/board/{token}/{_n(body['idea_number'])}"


# ── 2. own-similar ───────────────────────────────────────────────────────────


def test_similar_own_reply_to_submitter_carries_board_url_per_match(ctx):
    client, _h, product_id, key = ctx
    cid = _make_contact(client._factory, first_name="CUSTOMER", last_name="A", phone=PHONE)
    own_id = _insert_idea(client._factory, product_id, problem="Export orders to Excel", contact_id=cid)

    plain = _similar(client, key, product_id, "export orders to excel", submitter_phone=PHONE)
    assert plain.status_code == 200, plain.text
    (m,) = plain.json()["matches"]
    assert "board_url" not in m
    assert _live_token(client._factory, cid) is None

    res = client.post(
        "/ideation/intake/ideas/similar-own",
        headers=_key_auth(key),
        json={
            "product_id": product_id,
            "text": "export orders to excel",
            "submitter_phone": PHONE,
            "reply_to_submitter": True,
        },
    )
    assert res.status_code == 200, res.text
    (m,) = res.json()["matches"]
    assert m["idea_id"] == own_id
    token = _live_token(client._factory, cid)
    assert token
    expected = f"{_board_base()}/{token}"
    if m["idea_number"]:
        expected = f"{expected}/{_n(m['idea_number'])}"
    assert m["board_url"] == expected
    assert m["link"] == plain.json()["matches"][0]["link"]


def test_similar_own_match_without_contact_gets_null_board_url(ctx):

    client, _h, product_id, key = ctx
    _insert_idea(client._factory, product_id, problem="Export orders to Excel", crm_user_id="crm-1")
    res = client.post(
        "/ideation/intake/ideas/similar-own",
        headers=_key_auth(key),
        json={
            "product_id": product_id,
            "text": "export orders to excel",
            "submitter_crm_user_id": "crm-1",
            "reply_to_submitter": True,
        },
    )
    assert res.status_code == 200, res.text
    (m,) = res.json()["matches"]
    assert m["board_url"] is None


def test_similar_own_test_lane_gets_null_board_url(ctx):
    from modules.ideation.models import Idea
    client, _h, product_id, key = ctx
    cid = _make_contact(client._factory, first_name="CUSTOMER", last_name="A", phone=PHONE)
    iid = _insert_idea(client._factory, product_id, problem="Export orders to Excel", contact_id=cid)
    db = client._factory()
    try:
        db.query(Idea).filter(Idea.id == iid).update({"is_test": True})
        db.commit()
    finally:
        db.close()
    res = client.post(
        "/ideation/intake/ideas/similar-own",
        headers=_key_auth(key),
        json={
            "product_id": product_id,
            "text": "export orders to excel",
            "submitter_phone": PHONE,
            "is_test": True,
            "reply_to_submitter": True,
        },
    )
    assert res.status_code == 200, res.text
    (m,) = res.json()["matches"]
    assert m["board_url"] is None
    assert _live_token(client._factory, cid) is None


def test_similar_own_crm_match_filed_for_another_contact_gets_null(ctx):
    """Review B1: CRM user crm-1 (an operator) filed an idea FOR a customer
    contact. A later similar-own by crm-1 matches it on the CRM id, but the
    idea's contact is the customer, not the caller - never hand crm-1's host
    the customer's personal link."""
    client, _h, product_id, key = ctx
    customer = _make_contact(client._factory, first_name="CUSTOMER", last_name="B", phone="+60100000009")
    _insert_idea(
        client._factory,
        product_id,
        problem="Export orders to Excel",
        crm_user_id="crm-1",
        contact_id=customer,
    )
    for ident in ({"submitter_crm_user_id": "crm-1"}, {"submitter_crm_user_id": "crm-1", "submitter_phone": PHONE}):
        res = client.post(
            "/ideation/intake/ideas/similar-own",
            headers=_key_auth(key),
            json={
                "product_id": product_id,
                "text": "export orders to excel",
                "reply_to_submitter": True,
                **ident,
            },
        )
        assert res.status_code == 200, res.text
        (m,) = res.json()["matches"]
        assert m["board_url"] is None
    assert _live_token(client._factory, customer) is None


def test_similar_own_same_phone_sibling_contact_gets_its_own_link(ctx):
    """The caller's phone resolves to the idea's contact (formatted differently):
    that is the caller themself, so the link is returned."""
    client, _h, product_id, key = ctx
    cid = _make_contact(client._factory, first_name="CUSTOMER", last_name="A", phone="60100000001")
    _insert_idea(client._factory, product_id, problem="Export orders to Excel", contact_id=cid)
    res = client.post(
        "/ideation/intake/ideas/similar-own",
        headers=_key_auth(key),
        json={
            "product_id": product_id,
            "text": "export orders to excel",
            "submitter_phone": PHONE,
            "reply_to_submitter": True,
        },
    )
    (m,) = res.json()["matches"]
    assert m["board_url"] and _live_token(client._factory, cid) in m["board_url"]
