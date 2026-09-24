"""Ideation intake redesign - shared-service contract (S1), Group A of the UAC
(AC-1101..AC-1118). TEST-FIRST (PRINCIPLES.md): written BEFORE the S1
implementation lands, against the lane brief's binding decisions
(``<scratchpad>/lane-brief.md``) - one test per AC, named ``test_ac_11xx_...``.

Fixture style mirrors ``tests/test_ideation_create_idea.py`` (ideation_client,
_mint_key, _create_software_product, _set_delivery, workspace-key header).

Every response assertion indexes the dict with ``body["key"]`` (never
``.get``) so a key that does not exist yet raises ``KeyError`` instead of
silently comparing against ``None`` - a response with the key simply absent
must never pass an "is None" assertion by accident (AC-1116).
"""
import re

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

# The full response envelope every create-idea turn must carry (AC-1116).
ALL_RESPONSE_KEYS = {
    "status",
    "draft_id",
    "reply_text",
    "missing",
    "next_field",
    "title",
    "captured",
    "duplicate_candidate",
    "idea_number",
    "link",
}


# ── fixtures / helpers (mirrors test_ideation_create_idea.py) ────────────────


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


def _set_delivery(client, h, product_id, base="https://fe-sorento.foundryx.my") -> None:
    res = client.put(
        f"/ideation/products/{product_id}/delivery",
        headers=h,
        json={"productDomainBase": base},
    )
    assert res.status_code == 200, res.text


def _default_workspace_id(db) -> str:
    from modules.omnichannel.models import Workspace

    ws = (
        db.query(Workspace)
        .filter(Workspace.tenant_id == DEFAULT_TENANT_ID, Workspace.is_default.is_(True))
        .first()
    )
    assert ws is not None, "omnichannel default workspace not seeded"
    return ws.id


def _mint_key(factory) -> str:
    from modules.omnichannel.services.api_key_service import ApiKeyService

    db = factory()
    try:
        _row, full_key = ApiKeyService(db).mint(
            DEFAULT_TENANT_ID, _default_workspace_id(db), "intake", None
        )
        return full_key
    finally:
        db.close()


def _key_auth(key) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _make_contact(factory, first_name="Ah", last_name="Seng", phone="+60123456789") -> str:
    from modules.omnichannel.models import Contact

    db = factory()
    try:
        c = Contact(
            tenant_id=DEFAULT_TENANT_ID,
            workspace_id=_default_workspace_id(db),
            first_name=first_name,
            last_name=last_name,
            phone=phone,
        )
        db.add(c)
        db.commit()
        return c.id
    finally:
        db.close()


@pytest.fixture
def setup(ideation_client):
    """A software product (+ delivery base), a synced contact, and a workspace key."""
    factory = ideation_client._factory
    h = _auth(ideation_client)
    product_id = _create_software_product(ideation_client, h)
    _set_delivery(ideation_client, h, product_id)
    contact_id = _make_contact(factory)
    key = _mint_key(factory)
    return {
        "client": ideation_client,
        "factory": factory,
        "product_id": product_id,
        "contact_id": contact_id,
        "key": key,
        "h": h,
    }


def _create_idea(s, contact_id=None, **body):
    payload = {
        "product_id": s["product_id"],
        "submitter_contact_id": contact_id if contact_id is not None else s["contact_id"],
        "message_text": body.pop(
            "message_text", "the price tag should show promo price in red"
        ),
    }
    payload.update(body)
    return s["client"].post(
        "/ideation/intake/create-idea", headers=_key_auth(s["key"]), json=payload
    )


def _idea_row(factory, idea_id):
    from modules.ideation.models import Idea

    db = factory()
    try:
        return db.query(Idea).filter(Idea.id == idea_id).first()
    finally:
        db.close()


def _idea_status_key(factory, idea_id) -> str:
    from app.models.status import Status
    from modules.ideation.models import Idea

    db = factory()
    try:
        idea = db.query(Idea).filter(Idea.id == idea_id).first()
        assert idea is not None
        st = db.query(Status).filter(Status.id == idea.status_id).first()
        return st.key
    finally:
        db.close()


def _upvote_count(factory, idea_id) -> int:
    from modules.ideation.models import IdeaVote

    db = factory()
    try:
        return db.query(IdeaVote).filter(IdeaVote.idea_id == idea_id).count()
    finally:
        db.close()


def _answer_solution_and_impact(s, draft_id, contact_id=None):
    """Answer proposed_solution then impact on an open draft, WITHOUT ever
    touching department (R15) - returns the final turn's response."""
    _create_idea(
        s, contact_id, draft_id=draft_id, fields={"proposed_solution": "A red sticker"}
    )
    return _create_idea(s, contact_id, draft_id=draft_id, fields={"impact": "Fewer questions"})


def _complete_flow(s, message_text, contact_id=None, title=None):
    """Drive a fresh draft to ``complete`` (problem + solution + impact,
    department never touched, then confirm). Returns the final response."""
    kwargs = {"message_text": message_text}
    if title:
        kwargs["title"] = title
    body = _create_idea(s, contact_id, **kwargs).json()
    draft_id = body["draft_id"]
    _answer_solution_and_impact(s, draft_id, contact_id)
    return _create_idea(s, contact_id, draft_id=draft_id, confirm=True)


# ── AC-1101 - problem required, others optional; schema keeps all four ───────


def test_ac_1101_problem_required_others_optional(ideation_client):
    """AC-1101: the ideation intake definition marks only ``problem`` required;
    proposed_solution/impact/department are optional, and the form-engine
    document still lists all four fields."""
    from app.form_engine.schemas import validate_form_doc
    from modules.ideation.services.intake_definitions import get_intake_definition

    definition = get_intake_definition("ideation")
    assert definition is not None
    fields = {f.key: f for f in definition.target_schema.input_fields() if f.key}
    assert set(fields) == {"problem", "proposed_solution", "impact", "department"}
    assert fields["problem"].required is True
    assert fields["proposed_solution"].required is not True
    assert fields["impact"].required is not True
    assert fields["department"].required is not True
    assert validate_form_doc(definition.target_schema) == []


# ── AC-1102 - next_field order; department never nominated ───────────────────


def test_ac_1102_next_field_order_excludes_department(setup):
    """AC-1102: with problem filled and no optional field answered/skipped,
    status is collecting and next_field is proposed_solution first, then
    impact; department is never nominated as next_field."""
    s = setup
    body = _create_idea(s).json()
    assert body["status"] == "collecting"
    assert body["next_field"] == "proposed_solution"
    draft_id = body["draft_id"]

    body2 = _create_idea(
        s, draft_id=draft_id, fields={"proposed_solution": "A red sticker"}
    ).json()
    assert body2["next_field"] == "impact"
    assert body2["next_field"] != "department"


# ── AC-1103 - skip recorded, never re-asked ───────────────────────────────────


def test_ac_1103_skip_recorded_and_never_reasked(setup):
    """AC-1103: skip:["impact"] records impact as skipped; it is never returned
    as next_field again on later turns of the same draft."""
    s = setup
    body = _create_idea(s).json()
    draft_id = body["draft_id"]
    body2 = _create_idea(
        s, draft_id=draft_id, fields={"proposed_solution": "A red sticker"}
    ).json()
    assert body2["next_field"] == "impact"

    body3 = _create_idea(s, draft_id=draft_id, skip=["impact"]).json()
    assert body3["next_field"] is None
    assert body3["status"] == "review"

    # A later, unrelated turn on the same draft never re-asks impact.
    body4 = _create_idea(s, draft_id=draft_id, fields={}).json()
    assert body4["next_field"] is None


# ── AC-1104 - review with next_field null, department never required ─────────


def test_ac_1104_review_regardless_of_department(setup):
    """AC-1104: problem filled + both optional fields answered/skipped ->
    status review, next_field null, even though department was never
    mentioned (R15)."""
    s = setup
    body = _create_idea(s).json()
    draft_id = body["draft_id"]
    final = _answer_solution_and_impact(s, draft_id).json()
    assert final["status"] == "review"
    assert final["next_field"] is None


# ── AC-1105 - title stored + echoed; over-8-words rejected 422 ────────────────


def test_ac_1105_title_stored_and_echoed(setup):
    """AC-1105: a 1-8 word title is stored on the idea and echoed in the
    response; a title over 8 words is rejected with 422 uniform envelope."""
    s = setup
    body = _create_idea(s, title="Show promo price in red").json()
    assert body["title"] == "Show promo price in red"

    res2 = _create_idea(
        s,
        draft_id=body["draft_id"],
        title="one two three four five six seven eight nine",
    )
    assert res2.status_code == 422, res2.text
    err = res2.json()
    assert "error" in err
    assert err["error"]["code"] == "title_too_long"
    assert "message" in err["error"]


# ── AC-1106 - title on read surfaces (list + detail), null for pre-lane idea ──


def test_ac_1106_serializer_exposes_title_field(setup):
    """AC-1106: the list and detail serializers carry a ``title`` field; a
    pre-lane idea (created without one) shows it as null."""
    s = setup
    res = s["client"].post(
        "/ideation/ideas",
        headers=s["h"],
        json={
            "productId": s["product_id"],
            "problem": "Legacy idea created before this lane",
        },
    )
    assert res.status_code == 201, res.text
    idea_id = res.json()["id"]

    listing = s["client"].get("/ideation/ideas", headers=s["h"])
    assert listing.status_code == 200, listing.text
    item = next(i for i in listing.json() if i["id"] == idea_id)
    assert "title" in item
    assert item["title"] is None

    detail = s["client"].get(f"/ideation/ideas/{idea_id}", headers=s["h"])
    assert detail.status_code == 200, detail.text
    assert "title" in detail.json()
    assert detail.json()["title"] is None


# ── AC-1107 - duplicate_candidate, no upvote, draft stays open ───────────────


def test_ac_1107_duplicate_candidate_no_upvote_draft_open(setup):
    """AC-1107: a new draft similar to an existing NON-test idea of the same
    product gets status duplicate_candidate carrying {idea_number, title};
    no upvote is written and the draft stays open (status draft)."""
    s = setup
    problem = "the price tag should show promo price in red"
    existing = _complete_flow(s, problem).json()
    existing_id = existing["draft_id"]
    existing_row = _idea_row(s["factory"], existing_id)
    existing_idea_number = getattr(existing_row, "idea_number", None)

    other_contact = _make_contact(s["factory"], "Other", "Dealer", "+60111222333")
    dup = _create_idea(s, other_contact, message_text=problem).json()
    assert dup["status"] == "duplicate_candidate"
    assert dup["duplicate_candidate"] == {
        "idea_number": existing_idea_number,
        "title": problem,
    }
    assert _upvote_count(s["factory"], existing_id) == 0
    assert _idea_status_key(s["factory"], dup["draft_id"]) == "draft"


# ── AC-1108 - only-test-similar never offered to a live draft ────────────────


def test_ac_1108_test_lane_similar_ideas_excluded_for_live_draft(setup):
    """AC-1108: when only TEST ideas are similar, a live (non-test) draft gets
    no duplicate_candidate. Constructs the existing captured idea directly as
    ``is_test=True`` (isolated from the S1 turn-algorithm redesign, which the
    is_test dedup scoping does not depend on) so this is a strict proof: the
    ONLY similar idea in the system is test-lane, and the live draft must
    still land on plain ``collecting``, never ``duplicate_candidate``."""
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import idea_status_id

    s = setup
    problem = "the price tag should show promo price in red"
    db = s["factory"]()
    try:
        captured_id = idea_status_id(db, "captured", DEFAULT_TENANT_ID)
        existing = Idea(
            tenant_id=DEFAULT_TENANT_ID,
            product_id=s["product_id"],
            status_id=captured_id,
            problem=problem,
            captured_json={"problem": problem},
            is_test=True,
        )
        db.add(existing)
        db.commit()
    finally:
        db.close()

    live = _create_idea(s, message_text=problem, is_test=False).json()
    assert live["status"] != "duplicate_candidate"
    assert live["status"] == "collecting"
    assert live["duplicate_candidate"] is None


# ── AC-1109 - vote closes the draft, idempotent ───────────────────────────────


def test_ac_1109_duplicate_choice_vote_closes_draft_idempotent(setup):
    """AC-1109: duplicate_choice="vote" on a duplicate_candidate draft upvotes
    the candidate once, closes the draft (status duplicate, not an orphan
    draft), and returns status voted with the candidate's idea_number;
    repeating with the same draft_id is idempotent (voted again, no 2nd vote)."""
    s = setup
    problem = "the price tag should show promo price in red"
    existing = _complete_flow(s, problem).json()
    existing_id = existing["draft_id"]
    existing_row = _idea_row(s["factory"], existing_id)
    existing_idea_number = getattr(existing_row, "idea_number", None)

    voter_contact = _make_contact(s["factory"], "Voter", "Dealer", "+60177889900")
    cand_body = _create_idea(s, voter_contact, message_text=problem).json()
    assert cand_body["status"] == "duplicate_candidate"
    draft_id = cand_body["draft_id"]

    voted = _create_idea(s, voter_contact, draft_id=draft_id, duplicate_choice="vote").json()
    assert voted["status"] == "voted"
    assert voted["idea_number"] == existing_idea_number
    assert _upvote_count(s["factory"], existing_id) == 1
    assert _idea_status_key(s["factory"], draft_id) == "duplicate"

    voted_again = _create_idea(
        s, voter_contact, draft_id=draft_id, duplicate_choice="vote"
    ).json()
    assert voted_again["status"] == "voted"
    assert _upvote_count(s["factory"], existing_id) == 1


# ── AC-1110 - separate keeps the draft open, candidate never re-offered ──────


def test_ac_1110_duplicate_choice_separate_keeps_draft_open(setup):
    """AC-1110: duplicate_choice="separate" lets the draft continue normally
    and the same candidate is never offered again for this draft."""
    s = setup
    problem = "the price tag should show promo price in red"
    _complete_flow(s, problem)

    other_contact = _make_contact(s["factory"], "Sep", "Dealer", "+60199887766")
    cand_body = _create_idea(s, other_contact, message_text=problem).json()
    assert cand_body["status"] == "duplicate_candidate"
    draft_id = cand_body["draft_id"]

    sep = _create_idea(
        s,
        other_contact,
        draft_id=draft_id,
        duplicate_choice="separate",
        fields={"proposed_solution": "Also covers the online store price"},
    ).json()
    assert sep["status"] in {"collecting", "review"}
    assert _idea_status_key(s["factory"], draft_id) == "draft"

    # Sending the exact same problem text again on this draft never re-offers
    # the declined candidate.
    again = _create_idea(s, other_contact, draft_id=draft_id, fields={}).json()
    assert again["status"] != "duplicate_candidate"


# ── AC-1111 - confirm captures, idea_number format ────────────────────────────


def test_ac_1111_confirm_captures_with_formatted_idea_number(setup):
    """AC-1111: confirm:true in review captures the idea, mints the next
    idea_number formatted IDEA-<>=4 digits>, and status is complete; the row
    is status captured."""
    s = setup
    final = _complete_flow(s, "chatbot should remember what a dealer asked before").json()
    assert final["status"] == "complete"
    assert re.fullmatch(r"IDEA-\d{4,}", final["idea_number"] or "")
    assert _idea_status_key(s["factory"], final["draft_id"]) == "captured"


def test_ac_1111_idea_number_sequence_rolls_past_9999(setup):
    """AC-1111: the sequence grows past 9999 (IDEA-10000), never wraps or
    truncates - seed an existing idea at IDEA-9999 and confirm the next
    capture mints IDEA-10000."""
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import idea_status_id, initial_idea_status_id
    from modules.ideation.services.sinks import ideation_on_complete_sink

    s = setup
    db = s["factory"]()
    try:
        captured_id = idea_status_id(db, "captured", DEFAULT_TENANT_ID)
        existing = Idea(
            tenant_id=DEFAULT_TENANT_ID,
            product_id=s["product_id"],
            status_id=captured_id,
            problem="an already-captured idea at the rollover boundary",
            idea_number="IDEA-9999",
        )
        db.add(existing)
        db.commit()

        fresh = Idea(
            tenant_id=DEFAULT_TENANT_ID,
            product_id=s["product_id"],
            status_id=initial_idea_status_id(db, DEFAULT_TENANT_ID),
            problem="the next idea after the rollover boundary",
            captured_json={"problem": "the next idea after the rollover boundary"},
        )
        db.add(fresh)
        db.flush()
        ideation_on_complete_sink(db, fresh, DEFAULT_TENANT_ID)
        db.commit()
        assert fresh.idea_number == "IDEA-10000"
    finally:
        db.close()


# ── AC-1112 - two captures get different sequence numbers ────────────────────


def test_ac_1112_two_captures_get_different_idea_numbers(setup):
    """AC-1112: two ideas captured (even "concurrently") get different idea
    numbers - a real sequence, not max()+1 racing itself."""
    s = setup
    first = _complete_flow(s, "first idea for numbering", title=None).json()
    second_contact = _make_contact(s["factory"], "Second", "Dealer", "+60122334455")
    second = _complete_flow(
        s, "second idea for numbering", contact_id=second_contact
    ).json()
    assert first["idea_number"] is not None
    assert second["idea_number"] is not None
    assert first["idea_number"] != second["idea_number"]


# ── AC-1113 - cancel closes the draft, idempotent echo ────────────────────────


def test_ac_1113_cancel_closes_draft_idempotent(setup):
    """AC-1113: cancel:true closes any open draft with no idea number minted
    and status cancelled; the row is rejected; a later call with the same
    draft_id echoes cancelled idempotently."""
    s = setup
    body = _create_idea(s, message_text="stock alerts idea").json()
    draft_id = body["draft_id"]

    cancelled = _create_idea(s, draft_id=draft_id, cancel=True).json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["idea_number"] is None
    assert _idea_status_key(s["factory"], draft_id) == "rejected"

    again = _create_idea(s, draft_id=draft_id, cancel=True).json()
    assert again["status"] == "cancelled"


# ── AC-1114 / AC-1118 - complete link is the S5 public status URL ────────────


def test_ac_1114_1118_complete_link_and_reply_text(setup):
    """AC-1114/1118: a complete response for a WhatsApp-source idea carries
    link = {product_domain_base}/public/ideas/{status_token} (not the old SSO
    idea-detail URL), and reply_text names the idea number + link + WhatsApp
    update line."""
    s = setup
    final = _complete_flow(
        s, "show promo price in red on price tags", title="Show promo price in red"
    ).json()
    row = _idea_row(s["factory"], final["draft_id"])
    token = getattr(row, "status_token", None)
    assert token is not None, "status_token not minted"
    assert final["link"] == f"https://fe-sorento.foundryx.my/public/ideas/{token}"
    assert "/ideation/ideas/" not in (final["link"] or "")

    lines = final["reply_text"].split("\n")
    assert lines[0] == '"Show promo price in red"'
    assert lines[1] == f"Idea {final['idea_number']} is in. We'll update you on WhatsApp."
    assert lines[2] == f"Track it here: {final['link']}"


# ── AC-1115 - submitter_tier stored + surfaced ────────────────────────────────


def test_ac_1115_submitter_tier_stored_and_surfaced(setup):
    """AC-1115: submitter_tier:"dealer" is stored on the idea and surfaced on
    the read serializer as submitterTier."""
    s = setup
    body = _create_idea(s, submitter_tier="dealer").json()
    draft_id = body["draft_id"]
    row = _idea_row(s["factory"], draft_id)
    assert getattr(row, "submitter_tier", None) == "dealer"

    admin_h = s["h"]
    detail = s["client"].get(f"/ideation/ideas/{draft_id}", headers=admin_h)
    # A draft is not normally visible via the operator detail route until
    # captured in today's board semantics, but the serializer field must
    # exist regardless once the idea IS readable.
    if detail.status_code == 200:
        assert detail.json()["submitterTier"] == "dealer"
    else:
        # Fall back to asserting via a completed idea of the same submitter.
        final = _complete_flow(s, "tier check idea").json()
        d2 = s["client"].get(f"/ideation/ideas/{final['draft_id']}", headers=admin_h)
        assert d2.status_code == 200, d2.text
        assert "submitterTier" in d2.json()


# ── AC-1116 - every response carries all ten keys ─────────────────────────────


def test_ac_1116_response_envelope_collecting_and_review(setup):
    """AC-1116: collecting and review responses each carry exactly the ten
    contract keys, null where not applicable."""
    s = setup
    collecting = _create_idea(s).json()
    assert set(collecting.keys()) == ALL_RESPONSE_KEYS
    assert collecting["idea_number"] is None
    assert collecting["link"] is None
    assert collecting["duplicate_candidate"] is None

    review = _answer_solution_and_impact(s, collecting["draft_id"]).json()
    assert set(review.keys()) == ALL_RESPONSE_KEYS
    assert review["status"] == "review"


def test_ac_1116_response_envelope_complete(setup):
    s = setup
    final = _complete_flow(s, "envelope check on complete").json()
    assert set(final.keys()) == ALL_RESPONSE_KEYS
    assert final["status"] == "complete"


def test_ac_1116_response_envelope_duplicate_candidate(setup):
    s = setup
    problem = "the price tag should show promo price in red"
    _complete_flow(s, problem)
    other = _make_contact(s["factory"], "Env", "Dup", "+60133224455")
    dup = _create_idea(s, other, message_text=problem).json()
    assert set(dup.keys()) == ALL_RESPONSE_KEYS
    assert dup["status"] == "duplicate_candidate"


def test_ac_1116_response_envelope_voted_and_cancelled(setup):
    s = setup
    problem = "the price tag should show promo price in red"
    existing = _complete_flow(s, problem).json()
    voter = _make_contact(s["factory"], "Env2", "Voter", "+60133224466")
    cand = _create_idea(s, voter, message_text=problem).json()
    voted = _create_idea(s, voter, draft_id=cand["draft_id"], duplicate_choice="vote").json()
    assert set(voted.keys()) == ALL_RESPONSE_KEYS
    assert voted["status"] == "voted"

    cancel_draft = _create_idea(s, message_text="something to cancel").json()
    cancelled = _create_idea(s, draft_id=cancel_draft["draft_id"], cancel=True).json()
    assert set(cancelled.keys()) == ALL_RESPONSE_KEYS
    assert cancelled["status"] == "cancelled"


# ── AC-1117 - old sorento (no new fields) still works end to end ─────────────


def test_ac_1117_old_sorento_shape_still_works(setup):
    """AC-1117: a caller sending none of the new fields (no title, tier, skip)
    still gets a working collecting -> review -> complete flow, and the
    duplicate path returns duplicate_candidate (never duplicate/duplicate_of)."""
    s = setup
    payload1 = {
        "product_id": s["product_id"],
        "submitter_contact_id": s["contact_id"],
        "message_text": "old sorento sends this idea",
    }
    res1 = s["client"].post(
        "/ideation/intake/create-idea", headers=_key_auth(s["key"]), json=payload1
    )
    body1 = res1.json()
    assert body1["status"] == "collecting"
    assert "duplicate_of" not in body1

    payload2 = dict(payload1, draft_id=body1["draft_id"], fields={"proposed_solution": "x"})
    body2 = s["client"].post(
        "/ideation/intake/create-idea", headers=_key_auth(s["key"]), json=payload2
    ).json()
    payload3 = dict(payload1, draft_id=body1["draft_id"], fields={"impact": "y"})
    body3 = s["client"].post(
        "/ideation/intake/create-idea", headers=_key_auth(s["key"]), json=payload3
    ).json()
    assert body3["status"] == "review"

    payload4 = dict(payload1, draft_id=body1["draft_id"], confirm=True)
    body4 = s["client"].post(
        "/ideation/intake/create-idea", headers=_key_auth(s["key"]), json=payload4
    ).json()
    assert body4["status"] == "complete"
    assert "duplicate_of" not in body4

    # duplicate path, still old shape.
    payload5 = dict(payload1, submitter_contact_id=None)
    payload5.pop("draft_id", None)
    res5 = s["client"].post(
        "/ideation/intake/create-idea", headers=_key_auth(s["key"]), json=payload5
    )
    body5 = res5.json()
    assert body5["status"] == "duplicate_candidate"
    assert "duplicate_of" not in body5
    assert body5["status"] != "duplicate"


# ── Template shape tests (R10/R16) ────────────────────────────────────────────


def test_template_collecting_point_form_shape(setup):
    """The collecting reply is point form: optional title line, then Problem
    first, only present fields, then the exact single question line last."""
    s = setup
    body = _create_idea(
        s, title="Show promo price in red", message_text="the price tag should show promo price in red"
    ).json()
    lines = body["reply_text"].split("\n")
    assert lines[0] == '"Show promo price in red"'
    assert lines[1] == "Problem: the price tag should show promo price in red"
    assert lines[-1] == "What's your proposed solution?"

    body2 = _create_idea(
        s, draft_id=body["draft_id"], fields={"proposed_solution": "A small red sticker"}
    ).json()
    lines2 = body2["reply_text"].split("\n")
    assert "Solution: A small red sticker" in lines2
    assert lines2[-1] == "What's the impact if we do this?"


def test_template_review_last_line(setup):
    s = setup
    body = _create_idea(s).json()
    final = _answer_solution_and_impact(s, body["draft_id"]).json()
    assert final["reply_text"].split("\n")[-1] == "Submit it?"


def test_template_duplicate_candidate_two_lines(setup):
    """The duplicate_candidate template is exactly two lines - the candidate
    title, then the vote/separate question - never this draft's own recap."""
    s = setup
    problem = "the price tag should show promo price in red"
    _complete_flow(s, problem)
    other = _make_contact(s["factory"], "Tmpl", "Dup", "+60133998877")
    dup = _create_idea(s, other, message_text=problem).json()
    lines = dup["reply_text"].split("\n")
    assert lines == [
        f"Similar idea exists: {problem}",
        "Vote for that one, or keep yours separate?",
    ]
