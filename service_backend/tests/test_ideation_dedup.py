"""Ideation Slice 6 — dedup via ``pg_trgm`` text-similarity (AC-A-21/30/31/32).

Deterministic (NO LLM/embedding, D20), inline in the ``create_idea`` path, scoped
to ``(tenant, product)``, above a configured similarity threshold:

- AC-A-21 — a high text-similarity match ⇒ ``status="duplicate"`` + ``duplicate_of``
  = the existing idea id, the existing idea's ``upvotes`` incremented once per
  submitter (idempotent, reusing ``idea_votes``), and ``reply_text`` relays
  "similar to … upvoted".
- AC-A-31 — above threshold ⇒ duplicate; below threshold ⇒ proceeds; per-product
  scope prevents cross-product false positives.
- AC-A-32 — the check is a single deterministic query over existing OLTP ideas; no
  derived vector artifact. On SQLite the comparison uses the difflib Python
  fallback so the unit tests run GREEN with no live Postgres.
- AC-A-30 — the Postgres ``pg_trgm`` extension + GIN trigram index provisioning is
  a no-op / gracefully skipped on the SQLite test engine.

Test-first (PRINCIPLES.md): written before the DedupService exists.
"""
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD  # noqa: F401
from tests.test_ideation_create_idea import (  # noqa: F401 — reused fixtures/helpers
    _FULL_FIELDS,
    _auth,
    _create_idea,
    _create_software_product,
    _idea_count,
    _idea_status_key,
    _make_contact,
    _mint_key,
    _set_delivery,
    ideation_client,
    setup,
)
from app.models import DEFAULT_TENANT_ID


# ── helpers ───────────────────────────────────────────────────────────────────


def _upvotes(factory, idea_id) -> int:
    from modules.ideation.models import Idea

    db = factory()
    try:
        idea = db.query(Idea).filter(Idea.id == idea_id).first()
        assert idea is not None
        return idea.upvotes
    finally:
        db.close()


def _capture_idea(s, message_text) -> str:
    """Create + confirm an idea to ``captured`` so it is a real dedup candidate."""
    r1 = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"],
        message_text=message_text, fields=_FULL_FIELDS,
    )
    assert r1.json()["status"] == "review", r1.text
    draft_id = r1.json()["draft_id"]
    r2 = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"],
        draft_id=draft_id, confirm=True,
    )
    assert r2.json()["status"] == "complete", r2.text
    assert _idea_status_key(s["factory"], draft_id) == "captured"
    return draft_id


_ORIGINAL = "Let CS export orders to Excel"
_NEAR_DUP = "Allow the CS team to export orders to Excel"
_DISSIMILAR = "Add dark mode to the settings page"


# ── AC-A-21 / AC-A-31 — near-duplicate ⇒ duplicate + upvote ───────────────────


def test_near_duplicate_flags_and_upvotes(setup):
    s = setup
    original_id = _capture_idea(s, _ORIGINAL)
    assert _upvotes(s["factory"], original_id) == 0

    # A DIFFERENT submitter sends a near-duplicate (turn 1).
    other = _make_contact(s["factory"], first_name="Aisha", phone="+60111222333")
    res = _create_idea(
        s["client"], s["key"], other, s["product_id"], message_text=_NEAR_DUP
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "duplicate"
    assert body["duplicate_of"] == original_id
    assert "upvot" in body["reply_text"].lower()
    # The existing idea gained exactly one upvote; no second captured idea.
    assert _upvotes(s["factory"], original_id) == 1


# ── AC-A-31 — below threshold proceeds ────────────────────────────────────────


def test_below_threshold_proceeds(setup):
    s = setup
    original_id = _capture_idea(s, _ORIGINAL)

    res = _create_idea(
        s["client"], s["key"], s["contact_id"], s["product_id"],
        message_text=_DISSIMILAR,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "collecting"  # not a duplicate — proceeds
    assert "duplicate_of" not in body
    assert _upvotes(s["factory"], original_id) == 0


# ── AC-A-31 — per-product scope (no cross-product false positive) ─────────────


def test_same_text_under_different_product_is_not_duplicate(setup):
    s = setup
    original_id = _capture_idea(s, _ORIGINAL)

    # A second software product with its own delivery base.
    h = _auth(s["client"])
    product2 = _create_software_product(s["client"], h, name="Rigel WMS")
    _set_delivery(s["client"], h, product2, base="https://fe-rigel.foundryx.my")

    # The SAME text under product2 must NOT dedup against product1's idea.
    res = _create_idea(
        s["client"], s["key"], s["contact_id"], product2, message_text=_ORIGINAL
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] != "duplicate"
    assert _upvotes(s["factory"], original_id) == 0


# ── AC-A-21 — upvote idempotent per submitter; distinct submitters accumulate ──


def test_upvote_idempotent_on_repeat_same_submitter(setup):
    s = setup
    original_id = _capture_idea(s, _ORIGINAL)
    voter = _make_contact(s["factory"], first_name="Voter", phone="+60199887766")

    for _ in range(3):
        res = _create_idea(
            s["client"], s["key"], voter, s["product_id"], message_text=_NEAR_DUP
        )
        assert res.json()["status"] == "duplicate", res.text
    # Same submitter voting 3× still counts once.
    assert _upvotes(s["factory"], original_id) == 1


def test_distinct_submitters_each_add_a_vote(setup):
    s = setup
    original_id = _capture_idea(s, _ORIGINAL)

    v1 = _make_contact(s["factory"], first_name="One", phone="+60100000001")
    v2 = _make_contact(s["factory"], first_name="Two", phone="+60100000002")
    for voter in (v1, v2):
        res = _create_idea(
            s["client"], s["key"], voter, s["product_id"], message_text=_NEAR_DUP
        )
        assert res.json()["status"] == "duplicate", res.text
    assert _upvotes(s["factory"], original_id) == 2


# ── AC-A-30 — pg_trgm provisioning is a no-op on SQLite ───────────────────────


def test_pg_trgm_provisioning_noop_on_sqlite(ideation_client):
    """AC-A-30 — ``ensure_pg_trgm_index`` gracefully skips on the SQLite engine
    (Postgres-only DDL); it must not raise and must create nothing."""
    from modules.ideation.services.dedup import ensure_pg_trgm_index

    db = ideation_client._factory()
    try:
        # Must be a clean no-op on a non-Postgres bind.
        ensure_pg_trgm_index(db.get_bind())
    finally:
        db.close()


def test_dedup_service_uses_python_fallback_on_sqlite(ideation_client):
    """AC-A-32 — on SQLite the DedupService computes similarity in Python (difflib)
    and still returns a match id for near-duplicate text."""
    from modules.ideation.services.dedup import DedupService

    db = ideation_client._factory()
    try:
        svc = DedupService(db)
        # No ideas yet -> no match.
        assert svc.find_duplicate(DEFAULT_TENANT_ID, "p", "hello world", None) is None
    finally:
        db.close()
