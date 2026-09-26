"""Ideation intake redesign - public idea status page (S5), Group F of the UAC
(AC-1601..AC-1604) + the 0010 migration existence check. TEST-FIRST
(PRINCIPLES.md): written BEFORE the S5 implementation lands.

Most tests here work at the sink/router boundary directly (constructing an
already-``captured`` ``Idea`` row via the ORM with the target columns) so they
do not depend on the S1 turn-algorithm redesign (Group A) also being done -
the public status page is a separate, independently-testable surface per the
lane brief.
"""
import hashlib
import importlib.util
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

MODULE_ROOT = Path(__file__).resolve().parents[1] / "modules" / "ideation"
VERSIONS_DIR = MODULE_ROOT / "alembic" / "versions"


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


@pytest.fixture
def setup(ideation_client):
    factory = ideation_client._factory
    h = _auth(ideation_client)
    product_id = _create_software_product(ideation_client, h)
    _set_delivery(ideation_client, h, product_id)
    return {
        "client": ideation_client,
        "factory": factory,
        "product_id": product_id,
        "h": h,
    }


UNIFORM_404 = {"error": {"code": "not_found", "message": "Not found."}}


def _make_captured_idea(
    factory,
    product_id,
    *,
    problem="Show promo price in red on price tags",
    title=None,
    idea_number="IDEA-0001",
    status_token=None,
    is_test=False,
    status_key="captured",
    tenant_id=DEFAULT_TENANT_ID,
    proposed_solution=None,
    impact=None,
    department=None,
    upvotes=0,
    submitter_name=None,
    submitter_contact_id=None,
):
    """Directly construct an already-``captured`` Idea row with the S5 columns
    (title/idea_number/status_token) - isolates the public-status tests from
    the Group A turn-algorithm redesign. ``status_key``/``tenant_id`` and the
    detail-field kwargs (AC-90-1xx) widen this helper for the timeline/
    off-ramp/tenant-scoping/detail-section tests without a bespoke builder."""
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import idea_status_id

    db = factory()
    try:
        status_id = idea_status_id(db, status_key, tenant_id)
        assert status_id is not None
        idea = Idea(
            tenant_id=tenant_id,
            product_id=product_id,
            status_id=status_id,
            problem=problem,
            title=title,
            idea_number=idea_number,
            status_token=status_token,
            is_test=is_test,
            proposed_solution=proposed_solution,
            impact=impact,
            department=department,
            upvotes=upvotes,
            submitter_name=submitter_name,
            submitter_contact_id=submitter_contact_id,
            captured_json={"problem": problem},
        )
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


# ── AC-1601 - public status returns only title/status/idea_number ────────────


def test_ac_1601_returns_only_title_status_idea_number(setup):
    """AC-1601 (superseded by issue #90 - the exact-key-set pin now lives in
    ``test_public_status_exact_key_set_and_no_pii``, AC-90-104, since the
    page grew problem/solution/impact/department/product/submitter/timeline
    fields on the owner's ruling). This one stays as a narrower value check
    on the three original fields - REWRITTEN, not deleted, per the #90 lane
    brief."""
    s = setup
    token = "tok_" + "a" * 20
    _make_captured_idea(
        s["factory"],
        s["product_id"],
        title="Show promo price in red on price tags",
        idea_number="IDEA-0182",
        status_token=token,
    )
    res = s["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["title"] == "Show promo price in red on price tags"
    assert body["ideaNumber"] == "IDEA-0182"
    assert body["status"] == "New"


def test_ac_1601_no_auth_header_required(setup):
    """AC-1601: the route needs no Authorization header at all (public).

    Superseded forbidden-key list (issue #90, REWRITTEN not deleted):
    ``problem``/``impact``/``department`` are now RETURNED fields (the owner's
    #90 ruling), so they are removed from this list; the exact allow/forbid
    set lives in ``test_public_status_exact_key_set_and_no_pii`` (AC-90-104).
    What must never appear survives here unchanged: no full submitter name, no
    raw ids, no ``product``/``draftId`` literal keys."""
    s = setup
    token = "tok_" + "b" * 20
    _make_captured_idea(s["factory"], s["product_id"], status_token=token, idea_number="IDEA-0002")
    res = s["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 200, res.text
    body = res.json()
    for forbidden_key in (
        "solution", "submitter", "submitterName", "product", "productId", "id", "draftId",
    ):
        assert forbidden_key not in body


# ── AC-1602 - unknown/malformed/draft tokens -> uniform 404 ───────────────────


@pytest.mark.parametrize(
    "token",
    [
        "unknown-token-that-does-not-exist",
        "bad token!",
        "%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20",  # decodes whitespace-only
        "x" * 15,  # below the 16-char minimum
        "x" * 400,
        "IDEA-0001",  # an idea number must never resolve as a token
    ],
)
def test_ac_1602_unknown_and_malformed_tokens_uniform_404(setup, token):
    """Tokens here all reach ``/public/ideas/{token}`` as a SINGLE path
    segment. A literal or percent-encoded ``../`` (e.g. ``%2e%2e%2fetc``)
    decodes to a value containing ``/`` - starlette/FastAPI then routes it as
    MULTIPLE segments, missing the ``{token}`` route entirely and hitting the
    framework's generic ``{"detail": "Not Found"}`` 404 instead of ours; that
    is a routing-normalization artifact, not this endpoint's behavior, so it
    is excluded from this parametrization."""
    res = setup["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 404
    assert res.json() == UNIFORM_404


def test_ac_1602_identical_body_unknown_vs_malformed(setup):
    """AC-1602: an unknown token and a malformed token produce byte-identical
    bodies - no distinguishing "wrong token" from "not yours"."""
    s = setup
    res_unknown = s["client"].get("/public/ideas/unknown-xxxxxxxxxxxxxxxxxxxx")
    res_malformed = s["client"].get("/public/ideas/" + "y" * 400)
    assert res_unknown.status_code == res_malformed.status_code == 404
    assert res_unknown.json() == res_malformed.json() == UNIFORM_404


def test_ac_1602_draft_status_row_is_404_even_with_a_token(setup):
    """AC-1602: a draft-status idea's row must 404 even if it somehow carries a
    status_token (drafts never mint one in the real flow; this proves the
    lookup gates on status, not merely token match)."""
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import initial_idea_status_id

    s = setup
    token = "tok_" + "d" * 20
    db = s["factory"]()
    try:
        idea = Idea(
            tenant_id=DEFAULT_TENANT_ID,
            product_id=s["product_id"],
            status_id=initial_idea_status_id(db, DEFAULT_TENANT_ID),
            problem="an open draft",
            status_token=token,
        )
        db.add(idea)
        db.commit()
    finally:
        db.close()

    res = s["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 404
    assert res.json() == UNIFORM_404


# ── AC-1603 - each token returns only its own idea; token shape ──────────────


def test_ac_1603_each_token_returns_only_its_own_idea(setup):
    s = setup
    token1 = "tok_" + "1" * 20
    token2 = "tok_" + "2" * 20
    _make_captured_idea(
        s["factory"], s["product_id"], title="Idea One", idea_number="IDEA-0001", status_token=token1
    )
    _make_captured_idea(
        s["factory"], s["product_id"], title="Idea Two", idea_number="IDEA-0002", status_token=token2
    )
    res1 = s["client"].get(f"/public/ideas/{token1}")
    res2 = s["client"].get(f"/public/ideas/{token2}")
    assert res1.status_code == res2.status_code == 200
    b1, b2 = res1.json(), res2.json()
    assert b1["title"] == "Idea One"
    assert b1["ideaNumber"] == "IDEA-0001"
    assert b2["title"] == "Idea Two"
    assert b2["ideaNumber"] == "IDEA-0002"
    assert b1 != b2


def test_ac_1603_token_minted_by_sink_matches_shape(setup):
    """AC-1603: the token minted by the completion sink is a signed/random
    per-idea value - never the row's UUID, never its sequential idea_number -
    and matches ``^[A-Za-z0-9_-]{16,64}$``."""
    from modules.ideation.models import Idea
    from modules.ideation.services.sinks import ideation_on_complete_sink
    from modules.ideation.services.statuses import initial_idea_status_id

    s = setup
    db = s["factory"]()
    try:
        idea = Idea(
            tenant_id=DEFAULT_TENANT_ID,
            product_id=s["product_id"],
            status_id=initial_idea_status_id(db, DEFAULT_TENANT_ID),
            problem="an idea about to be captured",
            captured_json={"problem": "an idea about to be captured"},
        )
        db.add(idea)
        db.flush()
        ideation_on_complete_sink(db, idea, DEFAULT_TENANT_ID)
        db.commit()
        token = getattr(idea, "status_token", None)
        assert token is not None, "status_token was not minted by the sink"
        assert re.fullmatch(r"[A-Za-z0-9_-]{16,64}", token)
        assert token != idea.id
        assert token != getattr(idea, "idea_number", None)
    finally:
        db.close()


def test_ac_1603_token_is_never_the_sequential_idea_number(setup):
    s = setup
    token = "tok_" + "9" * 20
    _make_captured_idea(
        s["factory"], s["product_id"], idea_number="IDEA-0099", status_token=token
    )
    res = s["client"].get(f"/public/ideas/IDEA-0099")
    assert res.status_code == 404
    assert res.json() == UNIFORM_404


# ── mint_idea_link never mints, only reads (review round 2, N1c) ─────────────


def test_mint_idea_link_none_when_status_token_missing(setup, monkeypatch):
    """``mint_idea_link`` is a pure READ (review round 1, should-fix #6): a
    captured row with NO ``status_token`` yet returns None even though
    ``settings.frontend_url`` (the ONLY input the link now needs, review
    round 2) is configured - minting happens only in
    ``numbering.mint_idea_identity`` (the sink), never as a side effect of
    reading the link. The product's OWN delivery base plays no part any more
    (the page lives on the shared-service frontend, not the product's
    domain)."""
    monkeypatch.setattr(settings, "frontend_url", "https://fe.example.test")
    from modules.ideation.services.sinks import mint_idea_link

    s = setup
    idea_id = _make_captured_idea(
        s["factory"], s["product_id"], idea_number="IDEA-0055", status_token=None
    )
    db = s["factory"]()
    try:
        idea = _idea_row(s["factory"], idea_id)
        assert idea.status_token is None
        assert mint_idea_link(db, idea) is None
    finally:
        db.close()


# ── AC-1604 - is_test idea still gets a token + link ──────────────────────────


def test_ac_1604_is_test_idea_still_gets_token_and_link(setup, monkeypatch):
    """AC-1604: a completed is_test idea still gets a status_token and a link,
    the same as any other idea. The link is on the shared-service frontend
    (``settings.frontend_url``, review round 2), not the product's own
    delivery domain."""
    monkeypatch.setattr(settings, "frontend_url", "https://fe.example.test")
    from modules.ideation.models import Idea
    from modules.ideation.services.sinks import ideation_on_complete_sink, mint_idea_link
    from modules.ideation.services.statuses import initial_idea_status_id

    s = setup
    db = s["factory"]()
    try:
        idea = Idea(
            tenant_id=DEFAULT_TENANT_ID,
            product_id=s["product_id"],
            status_id=initial_idea_status_id(db, DEFAULT_TENANT_ID),
            problem="a console/--say test turn",
            captured_json={"problem": "a console/--say test turn"},
            is_test=True,
        )
        db.add(idea)
        db.flush()
        ideation_on_complete_sink(db, idea, DEFAULT_TENANT_ID)
        db.commit()
        token = getattr(idea, "status_token", None)
        assert token is not None
        link = mint_idea_link(db, idea)
        assert link is not None
        assert link == f"https://fe.example.test/public/ideas/{token}"
    finally:
        db.close()

    res = s["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 200, res.text


# ── issue #90 - the public idea page grows into a real status page ───────────
# W1: AC-90-101..109. The owner's #90 ruling widens the public contract from
# {title,status,ideaNumber} to a full page (product name, problem/solution/
# impact/department, submitter first name, votes, a status timeline, "what
# happens next" copy) - superseding the AC-1601 3-key pin above (rewritten,
# not deleted).


def _full_fork_idea_statuses(factory, tenant_id: str):
    """A COMPLETE tenant fork of the Idea status set (every ``IDEA_STATUS_SEED``
    row, same key/label/color/sort_order/flags) - unlike
    ``test_ideation_intake_contract._fork_idea_statuses_partial`` (deliberately
    partial), this fork is used to prove the public timeline follows
    ``sort_order`` from the DB, never a hardcoded key order (AC-90-102), so it
    must carry every row. Returns ``{key: status_id}``."""
    import uuid as _uuid

    from app.models.status import Status
    from modules.ideation.services.statuses import IDEA_ENTITY, IDEA_STATUS_SEED

    db = factory()
    try:
        id_map = {}
        for key, label, color, sort_order, flags in IDEA_STATUS_SEED:
            row = Status(
                id=str(_uuid.uuid4()),
                entity_type=IDEA_ENTITY,
                key=key,
                category=key.upper(),
                label=label,
                color=color,
                sort_order=sort_order,
                tenant_id=tenant_id,
                is_system=True,
                **flags,
            )
            db.add(row)
            id_map[key] = row.id
        db.commit()
        return id_map
    finally:
        db.close()


def _swap_sort_order(factory, status_id_a: str, status_id_b: str) -> None:
    from app.models.status import Status

    db = factory()
    try:
        a = db.query(Status).filter(Status.id == status_id_a).first()
        b = db.query(Status).filter(Status.id == status_id_b).first()
        a.sort_order, b.sort_order = b.sort_order, a.sort_order
        db.commit()
    finally:
        db.close()


def test_public_status_returns_page_fields(setup):
    """AC-90-101: every new page field the #90 ruling adds, with real values -
    productName (the idea's core Product), statusColor, the detail sections,
    submitterFirstName, submittedAt, upvotes, nextStep, and a non-empty
    timeline."""
    s = setup
    token = "tok90_" + "a" * 18
    _make_captured_idea(
        s["factory"],
        s["product_id"],
        title="Show promo price in red on price tags",
        idea_number="IDEA-0500",
        status_token=token,
        problem="Promo price is not visible in-store",
        proposed_solution="Print it in red on the price tag",
        impact="Fewer missed promotions at checkout",
        department="Merchandising",
        upvotes=7,
        submitter_name="Jayson Teh",
    )
    res = s["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["title"] == "Show promo price in red on price tags"
    assert body["ideaNumber"] == "IDEA-0500"
    assert body["status"] == "New"
    assert body["statusColor"] == "blue"  # IDEA_STATUS_SEED "captured" color
    assert body["productName"] == "Sorento CRM"
    assert body["problem"] == "Promo price is not visible in-store"
    assert body["proposedSolution"] == "Print it in red on the price tag"
    assert body["impact"] == "Fewer missed promotions at checkout"
    assert body["department"] == "Merchandising"
    assert body["submitterFirstName"] == "Jayson"
    assert body["submittedAt"] is not None
    assert body["upvotes"] == 7
    assert isinstance(body["nextStep"], str) and body["nextStep"]
    assert isinstance(body["timeline"], list) and len(body["timeline"]) > 0
    for step in body["timeline"]:
        assert set(step.keys()) == {"label", "color", "state"}
        assert step["state"] in ("done", "current", "upcoming")


def test_public_timeline_order_and_states(setup):
    """AC-90-102: the platform set's 5 main-path steps (captured/triaged/
    linked/building/delivered), ordered by ``sort_order``; the states around
    ``triaged`` are done/current/upcoming. Then a tenant fork with two
    swapped ``sort_order`` values proves the ordering is read from the DB, not
    a hardcoded key sequence."""
    s = setup
    token = "tok90_" + "b" * 18
    _make_captured_idea(
        s["factory"], s["product_id"], idea_number="IDEA-0501", status_token=token,
        status_key="triaged",
    )
    res = s["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 200, res.text
    timeline = res.json()["timeline"]
    labels = [step["label"] for step in timeline]
    assert labels == ["New", "Triaged", "Linked to BR", "Building", "Delivered"]
    states = {step["label"]: step["state"] for step in timeline}
    assert states["New"] == "done"
    assert states["Triaged"] == "current"
    assert states["Linked to BR"] == "upcoming"
    assert states["Building"] == "upcoming"
    assert states["Delivered"] == "upcoming"

    # A tenant fork with "linked" and "building" sort_order swapped: the idea
    # sits on "building" - the timeline must reorder around the swap, proving
    # sort_order (not the fixed key sequence) drives the order.
    from app.models.tenant import Tenant

    db = s["factory"]()
    try:
        default_tenant = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).first()
        tenant = Tenant(
            name="Swapped Order Co", slug="swapped-order-90", status_id=default_tenant.status_id
        )
        db.add(tenant)
        db.commit()
        tenant_id = tenant.id
    finally:
        db.close()
    status_ids = _full_fork_idea_statuses(s["factory"], tenant_id)
    _swap_sort_order(s["factory"], status_ids["linked"], status_ids["building"])

    from modules.ideation.models import Idea
    from app.models.catalog import Product

    db = s["factory"]()
    try:
        product = Product(tenant_id=tenant_id, name="Forked Product", kind="software")
        db.add(product)
        db.flush()
        token2 = "tok90_" + "c" * 18
        idea = Idea(
            tenant_id=tenant_id,
            product_id=product.id,
            status_id=status_ids["building"],
            problem="a forked-tenant idea",
            idea_number="IDEA-F500",
            status_token=token2,
            captured_json={"problem": "a forked-tenant idea"},
        )
        db.add(idea)
        db.commit()
    finally:
        db.close()

    res2 = s["client"].get(f"/public/ideas/{token2}")
    assert res2.status_code == 200, res2.text
    timeline2 = res2.json()["timeline"]
    labels2 = [step["label"] for step in timeline2]
    # "linked" now sorts AFTER "building" (swapped), so the order is
    # New, Triaged, Building, Linked to BR, Delivered.
    assert labels2 == ["New", "Triaged", "Building", "Linked to BR", "Delivered"]
    states2 = {step["label"]: step["state"] for step in timeline2}
    assert states2["Building"] == "current"
    assert states2["Linked to BR"] == "upcoming"


def test_public_timeline_off_ramp(setup):
    """AC-90-103: an off-ramp status (Rejected, ``is_archived``) is not on the
    main path - the timeline is truthfully short: [first main-path step
    (New) done, Rejected current] - never a fabricated position among steps
    the idea never actually passed."""
    s = setup
    token = "tok90_" + "d" * 18
    _make_captured_idea(
        s["factory"], s["product_id"], idea_number="IDEA-0502", status_token=token,
        status_key="rejected",
    )
    res = s["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 200, res.text
    timeline = res.json()["timeline"]
    assert [(step["label"], step["state"]) for step in timeline] == [
        ("New", "done"),
        ("Rejected", "current"),
    ]


def test_public_status_exact_key_set_and_no_pii(setup):
    """AC-90-104: the widened contract's EXACT key set (rewrite of the old
    3-key AC-1601 pin) - a future field cannot leak silently - and no PII
    beyond a first name ever appears in the body (no phone/email substrings)."""
    s = setup
    token = "tok90_" + "e" * 18
    _make_captured_idea(
        s["factory"],
        s["product_id"],
        idea_number="IDEA-0503",
        status_token=token,
        submitter_name="Priya Nair",
        proposed_solution="Do the thing",
        impact="Saves time",
        department="Ops",
    )
    res = s["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body.keys()) == {
        "title", "status", "ideaNumber", "statusColor", "productName",
        "problem", "proposedSolution", "impact", "department",
        "submitterFirstName", "submittedAt", "upvotes", "nextStep", "timeline",
    }
    for forbidden_key in (
        "id", "productId", "tenantId", "statusId", "key", "submitterContactId",
        "phone", "email", "lastName", "submitterName", "submitterTier",
        "rawText", "capturedJson", "intakeState", "attachments", "downvotes",
        "priority", "isTest", "statusToken", "draftId", "submitter", "product",
    ):
        assert forbidden_key not in body
    raw = res.text
    assert "@" not in raw
    assert "Nair" not in raw  # last name never leaks
    assert "Priya" in raw  # first name is the one allowed PII


def test_first_name_only(setup):
    """AC-90-105: an operator-authored idea's ``submitter_name`` ("Jayson
    Teh") surfaces only the FIRST token."""
    s = setup
    token = "tok90_" + "f" * 18
    _make_captured_idea(
        s["factory"], s["product_id"], idea_number="IDEA-0504", status_token=token,
        submitter_name="Jayson Teh",
    )
    res = s["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 200, res.text
    assert res.json()["submitterFirstName"] == "Jayson"


@pytest.mark.parametrize(
    "raw_name, via_contact, forbidden_fragment",
    [
        # AC-90-106 original case: intake's find-or-create writes
        # first_name=phone for every new WhatsApp contact
        # (services/intake.py) - must publish NO name at all.
        ("+60123456789", True, "+60123456789"),
        # Review round 2 probes - a token-only digit-count check leaked
        # FRAGMENTS of these, not the whole string:
        # a phone split by spaces/hyphens leaves a short first token
        # ("+60") with too few digits to trip a token-only check.
        ("+60 12-345 6789", False, "+60"),
        ("0123 456 789", False, "0123"),
        # A fullwidth "＠" bypasses an ASCII-only '@' check unless the
        # whole string is NFKC-normalized first.
        ("a＠b.co", False, "a@b.co"),
        # A name-shaped token with a trailing digit run has fewer than 5
        # digits total, so the old whole-token digit-count threshold missed
        # it; the first token must be rejected outright for carrying ANY
        # digit.
        ("Ali_0123", False, "Ali_0123"),
    ],
)
def test_first_name_never_a_phone(setup, raw_name, via_contact, forbidden_fragment):
    """AC-90-106 (security-critical, parametrized - review round 2): the
    guard must catch every fragment leak above, not just a first-token
    digit-count check. The first (phone-only, via a Contact) case is the
    original scenario and must keep passing unchanged."""
    s = setup
    digest = hashlib.sha1(raw_name.encode("utf-8")).hexdigest()[:18]
    token = "tok90p" + digest
    idea_number = f"IDEA-P{digest[:6]}"

    if via_contact:
        from modules.omnichannel.models import Contact, Workspace

        db = s["factory"]()
        try:
            ws = (
                db.query(Workspace)
                .filter(Workspace.tenant_id == DEFAULT_TENANT_ID, Workspace.is_default.is_(True))
                .first()
            )
            assert ws is not None, "omnichannel default workspace not seeded"
            contact = Contact(
                tenant_id=DEFAULT_TENANT_ID,
                workspace_id=ws.id,
                first_name=raw_name,
                phone=raw_name,
            )
            db.add(contact)
            db.commit()
            contact_id = contact.id
        finally:
            db.close()
        _make_captured_idea(
            s["factory"], s["product_id"], idea_number=idea_number, status_token=token,
            submitter_contact_id=contact_id,
        )
    else:
        _make_captured_idea(
            s["factory"], s["product_id"], idea_number=idea_number, status_token=token,
            submitter_name=raw_name,
        )

    res = s["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["submitterFirstName"] is None
    assert forbidden_fragment not in res.text


def test_product_and_contact_lookups_tenant_scoped(setup):
    """AC-90-107 (polymorphic stored-id rule): an idea whose ``product_id``/
    ``submitter_contact_id`` point at rows OWNED BY ANOTHER TENANT (never
    happens in the real flow, but every stored id must resolve tenant-scoped
    defensively) must resolve neither - null, never the other tenant's data."""
    from app.models.catalog import Product
    from app.models.tenant import Tenant
    from modules.omnichannel.models import Contact, Workspace

    s = setup
    db = s["factory"]()
    try:
        default_tenant = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).first()
        other = Tenant(
            name="Other Co", slug="other-ideation-90", status_id=default_tenant.status_id
        )
        db.add(other)
        db.flush()
        other_product = Product(tenant_id=other.id, name="Other Tenant Product", kind="software")
        db.add(other_product)
        ws = Workspace(tenant_id=other.id, name="Other WS", is_default=True)
        db.add(ws)
        db.flush()
        other_contact = Contact(
            tenant_id=other.id, workspace_id=ws.id, first_name="Alice", phone="+60199999999"
        )
        db.add(other_contact)
        db.flush()
        other_product_id = other_product.id
        other_contact_id = other_contact.id
        db.commit()
    finally:
        db.close()

    token = "tok90_" + "h" * 18
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import idea_status_id

    db = s["factory"]()
    try:
        idea = Idea(
            tenant_id=DEFAULT_TENANT_ID,
            product_id=other_product_id,  # cross-tenant polymorphic ref
            status_id=idea_status_id(db, "captured", DEFAULT_TENANT_ID),
            problem="cross tenant scoping check",
            idea_number="IDEA-0506",
            status_token=token,
            submitter_contact_id=other_contact_id,  # cross-tenant polymorphic ref
            captured_json={"problem": "cross tenant scoping check"},
        )
        db.add(idea)
        db.commit()
    finally:
        db.close()

    res = s["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["productName"] is None
    assert body["submitterFirstName"] is None
    assert "Other Tenant Product" not in res.text
    assert "Alice" not in res.text


def test_next_step_copy_and_fallback(setup):
    """AC-90-108: a known platform status key gets its authored copy; a
    tenant-added key unknown to ``PUBLIC_NEXT_STEP`` falls back on trait
    flags (``is_terminal``/``is_archived`` -> "This idea is closed.")."""
    s = setup
    token = "tok90_" + "i" * 18
    _make_captured_idea(
        s["factory"], s["product_id"], idea_number="IDEA-0507", status_token=token,
        status_key="captured",
    )
    res = s["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 200, res.text
    assert res.json()["nextStep"] == "Your idea is in. The team will review it soon."

    # A tenant-added terminal status with a key PUBLIC_NEXT_STEP has never
    # heard of.
    from app.models.catalog import Product
    from app.models.status import Status
    from app.models.tenant import Tenant
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import IDEA_ENTITY

    db = s["factory"]()
    try:
        default_tenant = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).first()
        tenant = Tenant(
            name="Custom Status Co", slug="custom-status-90", status_id=default_tenant.status_id
        )
        db.add(tenant)
        db.flush()
        custom_status = Status(
            id="idea-status-custom-90",
            entity_type=IDEA_ENTITY,
            key="on_hold_custom",
            category="ON_HOLD_CUSTOM",
            label="On hold",
            color="gray",
            sort_order=1,
            tenant_id=tenant.id,
            is_system=False,
            is_terminal=True,
            is_archived=True,
        )
        db.add(custom_status)
        product = Product(tenant_id=tenant.id, name="Custom Status Product", kind="software")
        db.add(product)
        db.flush()
        token2 = "tok90_" + "j" * 18
        idea = Idea(
            tenant_id=tenant.id,
            product_id=product.id,
            status_id=custom_status.id,
            problem="an idea on a tenant-only status",
            idea_number="IDEA-F507",
            status_token=token2,
            captured_json={"problem": "an idea on a tenant-only status"},
        )
        db.add(idea)
        db.commit()
    finally:
        db.close()

    res2 = s["client"].get(f"/public/ideas/{token2}")
    assert res2.status_code == 200, res2.text
    assert res2.json()["nextStep"] == "This idea is closed."


def test_public_status_no_store_header(setup):
    """AC-90-109: richer content (problem/solution/impact/department) must
    never sit in a shared cache - ``Cache-Control: no-store`` on the 200."""
    s = setup
    token = "tok90_" + "k" * 18
    _make_captured_idea(
        s["factory"], s["product_id"], idea_number="IDEA-0508", status_token=token
    )
    res = s["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 200, res.text
    assert res.headers.get("cache-control") == "no-store"


def test_public_status_hardening_headers(setup):
    """Optional hardening (review round 2): the token is a bearer credential
    forwarded over WhatsApp/links - a search engine must never index the
    page and the browser must never send it onward as a Referer header."""
    s = setup
    token = "tok90_" + "n" * 18
    _make_captured_idea(
        s["factory"], s["product_id"], idea_number="IDEA-0510", status_token=token
    )
    res = s["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 200, res.text
    assert res.headers.get("x-robots-tag") == "noindex"
    assert res.headers.get("referrer-policy") == "no-referrer"


def test_status_lookup_is_tenant_scoped(setup):
    """Review round 2 nit (``public_status.py`` current-Status lookup): the
    query is scoped to ``Status.tenant_id IN (idea.tenant_id, NULL)`` -
    an idea's ``status_id`` pointing at a status row owned by ANOTHER
    tenant's fork (never happens in the real flow; defensive, same
    polymorphic-stored-id rule already applied to Product/Contact,
    AC-90-107) must resolve to nothing - uniform 404, never that other
    tenant's label/color leaking through."""
    from app.models.tenant import Tenant
    from modules.ideation.models import Idea

    s = setup
    db = s["factory"]()
    try:
        default_tenant = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).first()
        other = Tenant(
            name="Status Scope Co", slug="status-scope-90", status_id=default_tenant.status_id
        )
        db.add(other)
        db.commit()
        other_tenant_id = other.id
    finally:
        db.close()

    other_status_ids = _full_fork_idea_statuses(s["factory"], other_tenant_id)

    token = "tok90_" + "m" * 18
    db = s["factory"]()
    try:
        idea = Idea(
            tenant_id=DEFAULT_TENANT_ID,
            product_id=s["product_id"],
            status_id=other_status_ids["triaged"],  # another tenant's status row
            problem="a corrupted cross-tenant status reference",
            idea_number="IDEA-0509",
            status_token=token,
            captured_json={"problem": "a corrupted cross-tenant status reference"},
        )
        db.add(idea)
        db.commit()
    finally:
        db.close()

    res = s["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 404
    assert res.json() == UNIFORM_404


# ── Review round 1, blocking #2 - layering + tenant signin_allowed ───────────


def test_router_never_queries_the_db_directly():
    """Review round 1 (blocking #2): the public_ideas ROUTER is HTTP/Pydantic
    only - the lookup lives in ``services/public_status.py``. A static check:
    the route HANDLER's own source (not the module docstring, which is free
    to describe the rule in prose) never mentions ``db.query``, and the
    resolve logic is reachable as ``PublicIdeaStatusService.resolve``."""
    import inspect

    from modules.ideation.routers.public_ideas import get_public_idea_status
    from modules.ideation.services.public_status import PublicIdeaStatusService

    source = inspect.getsource(get_public_idea_status)
    assert "db.query" not in source
    assert "PublicIdeaStatusService" in source
    assert hasattr(PublicIdeaStatusService, "resolve")


def test_suspended_tenant_never_serves_a_public_idea_status(setup):
    """Review round 1 (blocking #2 / nit 9): a tenant whose sign-in is
    blocked (status-engine ``blocks_access``, e.g. suspended) must never
    serve its idea's public status page - ``Tenant.signin_allowed`` is the
    single chokepoint core checks per request (``FormService._resolve_public``
    reuses the same predicate for its own public surface); this endpoint
    reuses it too. Uniform 404, same as an unknown token."""
    from app.models.status import TENANT_STATUS_IDS, TENANT_STATUS_SUSPENDED
    from app.models.tenant import Tenant
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import idea_status_id

    s = setup
    token = "tok_" + "z" * 20
    db = s["factory"]()
    try:
        suspended = Tenant(
            name="Suspended Co",
            slug="suspended-ideation",
            status_id=TENANT_STATUS_IDS[TENANT_STATUS_SUSPENDED],
        )
        db.add(suspended)
        db.flush()
        assert suspended.signin_allowed is False
        status_id = idea_status_id(db, "captured", suspended.id)
        idea = Idea(
            tenant_id=suspended.id,
            product_id=s["product_id"],
            status_id=status_id,
            problem="an idea under a suspended tenant",
            idea_number="IDEA-9001",
            status_token=token,
            captured_json={"problem": "an idea under a suspended tenant"},
        )
        db.add(idea)
        db.commit()
    finally:
        db.close()

    res = s["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 404
    assert res.json() == UNIFORM_404


# ── Migration existence: 0010 chains onto 0009 ────────────────────────────────


def test_migration_0010_ideation_intake_contract_exists_and_chains():
    """The 0010 migration exists and revises 0009_ideation_is_test (current
    head) - imported by path per the codebase's own precedent
    (tests/test_autocount_so_ref.py::test_revision_0019_...)."""
    path = VERSIONS_DIR / "0010_ideation_intake_contract.py"
    assert path.exists(), f"missing migration file: {path}"
    spec = importlib.util.spec_from_file_location("_ideation_rev_0010", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "0009_ideation_is_test"
    assert len(module.revision) <= 32
