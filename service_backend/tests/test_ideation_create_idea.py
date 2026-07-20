"""Ideation Slice 5 — ``create_idea`` intake engine + IntakeDefinition + confirm gate.

Covers the §5.1 CANONICAL contract and AC-A-13..20, AC-A-18b/c, AC-A-22, AC-A-25,
AC-A-45:

- AC-A-13/14/15/16 — the IntakeDefinition registry (key="ideation"), its
  form_engine ``target_schema`` (valid ``validate_form_doc``), the
  ``completion_rule`` (captured/missing), and the idempotent ``on_complete_sink``.
- AC-A-17/18 — endpoint input + output contract byte-for-byte per §5.1.
- AC-A-18b — one-shot-complete still returns ``review`` (never auto-completes).
- AC-A-18c — revision loop merges then re-reviews across >=3 turns; a removed
  required field drops back to ``collecting``; identical re-send is idempotent.
- AC-A-19 — a draft Idea (status ``draft``) is created on turn 1.
- AC-A-20 — ``confirm=true`` -> ``complete`` + product-domain link; the draft moves
  ``draft -> captured``; ``confirm`` on an already-captured idea is a no-op.
- AC-A-22 — idempotency on ``draft_id`` (never duplicates / regresses).
- AC-A-25 — public ``POST /ideation/intake/create-idea``, workspace-key auth,
  uniform ``{error:{code,message}}`` envelope.

Test-first (PRINCIPLES.md): written before the implementation exists.
"""
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


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
    """A workspace API key (``fxw_live_…``) — the intake endpoint's server-to-server
    auth (reuses the omnichannel workspace-key mechanism until the respond.io
    binding lands)."""
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


def _make_contact(factory, first_name="Jayson", last_name="Tan", phone="+60123456789") -> str:
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


# The captured intake fields (besides ``problem``, seeded from message_text):
# proposed_solution / impact / department (the required set after the schema change).
_FULL_FIELDS = {
    "proposed_solution": "Add an Export to Excel button on the orders list",
    "impact": "Saves 30 minutes a day",
    "department": "Customer Service",
}


def _create_idea(client, key, contact_id, product_id, **body):
    payload = {
        "product_id": product_id,
        "submitter_contact_id": contact_id,
        "message_text": body.pop("message_text", "Let CS export orders to Excel"),
    }
    payload.update(body)
    return client.post(
        "/ideation/intake/create-idea", headers=_key_auth(key), json=payload
    )


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
    }


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


def _idea_count(factory) -> int:
    from modules.ideation.models import Idea

    db = factory()
    try:
        return db.query(Idea).filter(Idea.tenant_id == DEFAULT_TENANT_ID).count()
    finally:
        db.close()


# ── AC-A-13/14/15/16 — IntakeDefinition registry ──────────────────────────────


def test_intake_definition_registered_and_valid(ideation_client):
    """The registry holds exactly the ``ideation`` definition; its target_schema is
    a valid form_engine document (AC-A-13/14)."""
    from app.form_engine.schemas import validate_form_doc
    from modules.ideation.services.intake_definitions import get_intake_definition

    definition = get_intake_definition("ideation")
    assert definition is not None
    assert definition.key == "ideation"
    assert definition.on_complete_sink is not None
    assert definition.completion_rule is not None
    # target_schema is a valid published form document (Page->Section->Field).
    assert validate_form_doc(definition.target_schema) == []
    keys = {f.key for f in definition.target_schema.input_fields()}
    assert {"problem", "proposed_solution", "impact", "department"} <= keys


def test_completion_rule_computes_captured_missing():
    """AC-A-15 — captured = answered keys->values; missing = required unanswered."""
    from modules.ideation.services.intake_definitions import get_intake_definition

    definition = get_intake_definition("ideation")
    captured, missing = definition.completion_rule(
        {"problem": "x", "proposed_solution": "y"}
    )
    assert captured == {"problem": "x", "proposed_solution": "y"}
    assert "impact" in missing and "department" in missing
    assert "problem" not in missing

    captured2, missing2 = definition.completion_rule(
        {
            "problem": "x",
            "proposed_solution": "y",
            "impact": "faster",
            "department": "CS",
        }
    )
    assert missing2 == []


# ── AC-A-17/18 — endpoint input / output contract ─────────────────────────────


def test_input_output_shape(setup):
    """AC-A-17/18 — accepts the §5.1 input; returns exactly
    {draft_id,status,captured,missing,reply_text} on a collecting turn."""
    s = setup
    res = _create_idea(s["client"], s["key"], s["contact_id"], s["product_id"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body.keys()) == {"draft_id", "status", "captured", "missing", "reply_text"}
    assert body["status"] == "collecting"
    assert isinstance(body["draft_id"], str) and body["draft_id"]
    # problem seeded from message_text; the rest still missing.
    assert body["captured"].get("problem")
    assert set(body["missing"]) == {"proposed_solution", "impact", "department"}


def test_draft_created_on_turn_1(setup):
    """AC-A-19 — turn 1 (no draft_id) creates a draft Idea (status ``draft``)."""
    s = setup
    res = _create_idea(s["client"], s["key"], s["contact_id"], s["product_id"])
    assert res.status_code == 200, res.text
    draft_id = res.json()["draft_id"]
    assert _idea_status_key(s["factory"], draft_id) == "draft"
    assert _idea_count(s["factory"]) == 1


# ── AC-A-18b — confirmation gate: review before capture ────────────────────────


def test_one_shot_complete_returns_review(setup):
    """AC-A-18b — a first turn that is fully complete still returns ``review``
    (never auto-completes); the draft stays ``draft``."""
    s = setup
    res = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"], fields=_FULL_FIELDS
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "review"
    assert body["missing"] == []
    assert "link" not in body  # not complete yet
    assert _idea_status_key(s["factory"], body["draft_id"]) == "draft"


def test_collecting_to_review_after_missing_filled(setup):
    """AC-A-18 — collecting on a partial turn, review once ``missing == []``."""
    s = setup
    r1 = _create_idea(s["client"], s["key"], s["contact_id"], s["product_id"])
    assert r1.json()["status"] == "collecting"
    draft_id = r1.json()["draft_id"]

    r2 = _create_idea(
        s["client"],
        s["key"],
        s["contact_id"],
        s["product_id"],
        draft_id=draft_id,
        fields=_FULL_FIELDS,
    )
    body = r2.json()
    assert body["status"] == "review"
    assert body["draft_id"] == draft_id
    assert body["missing"] == []


# ── AC-A-18c — revision loop (>=3 turns) ──────────────────────────────────────


def test_revision_loop_over_three_turns(setup):
    """AC-A-18c — a review draft re-merges fields/remove and re-reviews; removing a
    required field drops to collecting; identical re-send is idempotent; >=3 turns."""
    s = setup
    # Turn 1 -> review (one-shot complete)
    r1 = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"], fields=_FULL_FIELDS
    )
    draft_id = r1.json()["draft_id"]
    assert r1.json()["status"] == "review"

    # Turn 2 — change a field, still review, captured reflects the change.
    r2 = _create_idea(
        s["client"],
        s["key"],
        s["contact_id"],
        s["product_id"],
        draft_id=draft_id,
        fields={"impact": "Saves an hour a day"},
    )
    assert r2.json()["status"] == "review"
    assert r2.json()["captured"]["impact"] == "Saves an hour a day"

    # Turn 3 — remove a required field -> back to collecting.
    r3 = _create_idea(
        s["client"],
        s["key"],
        s["contact_id"],
        s["product_id"],
        draft_id=draft_id,
        remove=["department"],
    )
    assert r3.json()["status"] == "collecting"
    assert "department" in r3.json()["missing"]

    # Turn 4 — re-add it -> review again.
    r4 = _create_idea(
        s["client"],
        s["key"],
        s["contact_id"],
        s["product_id"],
        draft_id=draft_id,
        fields={"department": "Customer Service"},
    )
    assert r4.json()["status"] == "review"

    # Turn 5 — identical re-send is idempotent (still review, same captured).
    r5 = _create_idea(
        s["client"],
        s["key"],
        s["contact_id"],
        s["product_id"],
        draft_id=draft_id,
        fields={"department": "Customer Service"},
    )
    assert r5.json()["status"] == "review"
    assert r5.json()["captured"] == r4.json()["captured"]
    assert _idea_count(s["factory"]) == 1


# ── AC-A-20 — completion on explicit confirm ──────────────────────────────────


def test_confirm_completes_with_link(setup):
    """AC-A-20 — confirm=true -> complete; draft moves to captured; link is the
    product-domain deep link."""
    s = setup
    r1 = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"], fields=_FULL_FIELDS
    )
    draft_id = r1.json()["draft_id"]

    r2 = _create_idea(
        s["client"],
        s["key"],
        s["contact_id"],
        s["product_id"],
        draft_id=draft_id,
        confirm=True,
    )
    body = r2.json()
    assert body["status"] == "complete"
    assert body["link"] == f"https://fe-sorento.foundryx.my/ideas/{draft_id}"
    assert _idea_status_key(s["factory"], draft_id) == "captured"

    # On completion the captured answers are promoted to first-class Idea columns.
    from modules.ideation.models import Idea

    db = s["factory"]()
    try:
        idea = db.query(Idea).filter(Idea.id == draft_id).first()
        assert idea is not None
        assert idea.proposed_solution == _FULL_FIELDS["proposed_solution"]
        assert idea.impact == _FULL_FIELDS["impact"]
        assert idea.department == _FULL_FIELDS["department"]
    finally:
        db.close()


def test_confirm_on_captured_is_idempotent(setup):
    """AC-A-16/20 — re-confirming a captured draft is a no-op returning complete +
    the same link; no second Idea, no double-advance."""
    s = setup
    r1 = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"], fields=_FULL_FIELDS
    )
    draft_id = r1.json()["draft_id"]
    _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"],
        draft_id=draft_id, confirm=True,
    )
    # Re-fire.
    r3 = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"],
        draft_id=draft_id, confirm=True,
    )
    body = r3.json()
    assert body["status"] == "complete"
    assert body["link"] == f"https://fe-sorento.foundryx.my/ideas/{draft_id}"
    assert _idea_count(s["factory"]) == 1
    assert _idea_status_key(s["factory"], draft_id) == "captured"


# ── AC-A-22 / AC-A-23 — idempotency + interrupt/resume ────────────────────────


def test_idempotency_on_draft_id(setup):
    """AC-A-22 — repeated identical calls with the same draft_id never duplicate
    the draft nor regress captured fields."""
    s = setup
    r1 = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"],
        fields={"department": "Customer Service"},
    )
    draft_id = r1.json()["draft_id"]
    captured1 = r1.json()["captured"]

    r2 = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"],
        draft_id=draft_id, fields={"department": "Customer Service"},
    )
    assert r2.json()["draft_id"] == draft_id
    assert r2.json()["captured"] == captured1
    assert _idea_count(s["factory"]) == 1


def test_interrupt_resume_keeps_captured(setup):
    """AC-A-23 — an interleaved (non-ideate) turn does not corrupt the draft;
    resuming by draft_id keeps prior captured fields intact."""
    s = setup
    r1 = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"],
        fields={"proposed_solution": "Add an export button"},
    )
    draft_id = r1.json()["draft_id"]

    # (interrupt happens sorento-side — no create_idea call) then resume:
    r2 = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"],
        draft_id=draft_id, fields={"department": "The CS team"},
    )
    captured = r2.json()["captured"]
    assert captured.get("problem")  # from turn 1 message_text
    assert captured.get("proposed_solution") == "Add an export button"  # from turn 1
    assert captured.get("department") == "The CS team"  # from resume


# ── product validation ────────────────────────────────────────────────────────


def test_unknown_product_rejected(setup):
    """AC-A-17 — a product_id that does not resolve for the workspace is rejected
    with the uniform envelope (binding spoof-refusal deferred to respond.io slice)."""
    s = setup
    res = _create_idea(
        s["client"], s["key"], s["contact_id"], "does-not-exist"
    )
    assert res.status_code == 404, res.text
    assert set(res.json()["error"].keys()) >= {"code", "message"}


# ── AC-A-25 — transport / auth + envelope ─────────────────────────────────────


def test_auth_required(setup):
    """AC-A-25 — a missing/invalid workspace key is refused with the uniform
    ``{error:{code,message}}`` envelope."""
    s = setup
    # No auth header at all.
    res = s["client"].post(
        "/ideation/intake/create-idea",
        json={
            "product_id": s["product_id"],
            "submitter_contact_id": s["contact_id"],
            "message_text": "hi",
        },
    )
    assert res.status_code == 401, res.text
    assert set(res.json()["error"].keys()) >= {"code", "message"}

    # A garbage key.
    res2 = _create_idea(s["client"], "fxw_live_garbage", s["contact_id"], s["product_id"])
    assert res2.status_code == 401, res2.text


# ── reply_text determinism ────────────────────────────────────────────────────


def test_reply_text_deterministic(setup):
    """AC-A-18 — reply_text is a deterministic template: collecting echoes captured
    + lists missing; review echoes the full summary + confirm ask; complete carries
    the link."""
    s = setup
    r1 = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"],
        fields={"proposed_solution": "Add an export button"},
    )
    draft_id = r1.json()["draft_id"]
    text1 = r1.json()["reply_text"]
    assert "Add an export button" in text1  # captured echoed
    # a missing field's label surfaces
    assert "Impact" in text1 or "Department" in text1

    r2 = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"],
        draft_id=draft_id, fields=_FULL_FIELDS,
    )
    text2 = r2.json()["reply_text"]
    assert "confirm" in text2.lower()

    r3 = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"],
        draft_id=draft_id, confirm=True,
    )
    assert f"https://fe-sorento.foundryx.my/ideas/{draft_id}" in r3.json()["reply_text"]


# ── WS-A / AC-CAP-1..3 — submitter_name stored verbatim ───────────────────────


def _idea_field(factory, idea_id, attr):
    from modules.ideation.models import Idea

    db = factory()
    try:
        idea = db.query(Idea).filter(Idea.id == idea_id).first()
        assert idea is not None
        return getattr(idea, attr)
    finally:
        db.close()


def test_submitter_name_stored_on_idea(setup):
    """A submitter_name from the host is persisted on the Idea (shown instead of
    'Unknown'); a later blank name never clobbers it."""
    s = setup
    r1 = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"],
        submitter_name="Aisha Rahman", fields=_FULL_FIELDS,
    )
    draft_id = r1.json()["draft_id"]
    assert _idea_field(s["factory"], draft_id, "submitter_name") == "Aisha Rahman"

    # A continuation WITHOUT a name must not wipe the stored one.
    _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"],
        draft_id=draft_id, fields={"impact": "Saves an hour"},
    )
    assert _idea_field(s["factory"], draft_id, "submitter_name") == "Aisha Rahman"


# ── WS-B / AC-CAP-5..7 — raw_transcript becomes the Idea's raw_text ───────────


def test_raw_transcript_stored_as_raw_text(setup):
    """When the host sends the cumulative transcript it becomes raw_text (the whole
    convo), refreshed each turn — NOT just the last message."""
    s = setup
    r1 = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"],
        message_text="I want AI to update contractors",
        raw_transcript="I want AI to update contractors",
    )
    draft_id = r1.json()["draft_id"]
    assert _idea_field(s["factory"], draft_id, "raw_text") == "I want AI to update contractors"

    # Turn 2 — transcript grows; raw_text reflects the WHOLE convo, not "okay i confirm".
    _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"],
        draft_id=draft_id,
        message_text="okay i confirm",
        raw_transcript="I want AI to update contractors\nimpact is high ROI\nokay i confirm",
        fields=_FULL_FIELDS,
    )
    assert _idea_field(s["factory"], draft_id, "raw_text") == (
        "I want AI to update contractors\nimpact is high ROI\nokay i confirm"
    )


def test_message_text_still_used_when_no_transcript(setup):
    """Back-compat: no raw_transcript → raw_text falls back to message_text."""
    s = setup
    r1 = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"],
        message_text="just the one message",
    )
    draft_id = r1.json()["draft_id"]
    assert _idea_field(s["factory"], draft_id, "raw_text") == "just the one message"


# ── §5.1 attachments[] + discard_draft_id (DC-9 / DC-10) ──────────────────────
# Multi-modal capture: sorento durably stores the Respond CDN bytes and passes a
# resolved ``attachments[]``; shared-service persists the pointers idempotently on
# ``source_msg_id`` and surfaces them in the read. ``discard_draft_id`` rejects an
# abandoned draft when the user starts a genuinely new idea (is_new_idea, DC-10).

_ATT = {
    "source_msg_id": "wamid.ABC123",
    "url": "https://cdn.sorento.my/ideas/att/mockup.jpg",
    "type": "image",
    "filename": "mockup.jpg",
    "caption": "a hand-drawn export button on the orders grid",
}


def _attachments(factory, idea_id):
    from modules.ideation.models import IdeaAttachment

    db = factory()
    try:
        return (
            db.query(IdeaAttachment)
            .filter(IdeaAttachment.idea_id == idea_id)
            .all()
        )
    finally:
        db.close()


def test_create_idea_persists_attachments(setup):
    s = setup
    res = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"], attachments=[_ATT]
    )
    assert res.status_code == 200, res.text
    draft_id = res.json()["draft_id"]
    rows = _attachments(s["factory"], draft_id)
    assert len(rows) == 1
    a = rows[0]
    assert a.source_msg_id == _ATT["source_msg_id"]
    assert a.kind == "image"
    assert a.url == _ATT["url"]
    assert a.filename == "mockup.jpg"
    assert a.caption == _ATT["caption"]


def test_attachments_surface_in_read(setup):
    s = setup
    res = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"], attachments=[_ATT]
    )
    draft_id = res.json()["draft_id"]
    got = s["client"].get(f"/ideation/ideas/{draft_id}", headers=_auth(s["client"]))
    assert got.status_code == 200, got.text
    atts = got.json()["attachments"]
    assert len(atts) == 1
    assert atts[0]["kind"] == "image"
    assert atts[0]["url"] == _ATT["url"]
    assert atts[0]["name"] == "mockup.jpg"


def test_attachments_idempotent_on_source_msg_id(setup):
    s = setup
    r1 = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"], attachments=[_ATT]
    )
    draft_id = r1.json()["draft_id"]
    # Continuation turn re-sends the SAME media (same source_msg_id) → no dup.
    r2 = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"],
        draft_id=draft_id, attachments=[_ATT],
    )
    assert r2.status_code == 200, r2.text
    rows = _attachments(s["factory"], draft_id)
    assert len(rows) == 1


def test_attachments_caption_can_update_on_reprocess(setup):
    """Idempotent upsert refreshes mutable metadata (caption/url) for the same
    source_msg_id — a re-run with a better vision caption updates in place."""
    s = setup
    r1 = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"], attachments=[_ATT]
    )
    draft_id = r1.json()["draft_id"]
    better = {**_ATT, "caption": "sketch: Export-to-Excel button, top-right of orders grid"}
    _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"],
        draft_id=draft_id, attachments=[better],
    )
    rows = _attachments(s["factory"], draft_id)
    assert len(rows) == 1
    assert rows[0].caption == better["caption"]


def test_discard_draft_id_rejects_old_draft(setup):
    s = setup
    r1 = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"],
        message_text="idea about exporting orders",
    )
    old = r1.json()["draft_id"]
    # New, unrelated idea; discard the abandoned draft (DC-10 is_new_idea restart).
    r2 = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"],
        message_text="different idea: a dark mode toggle",
        discard_draft_id=old,
    )
    assert r2.status_code == 200, r2.text
    new = r2.json()["draft_id"]
    assert new != old
    assert _idea_status_key(s["factory"], old) == "rejected"


def test_discard_unknown_draft_is_noop(setup):
    """A discard_draft_id that doesn't resolve must not 500 — just proceed."""
    s = setup
    res = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"],
        message_text="fresh idea", discard_draft_id="does-not-exist",
    )
    assert res.status_code == 200, res.text
