"""Cluster D (sprint-4/05) slice-3 — coverage-gap tests (QA, tester-authored).

The coder's `tests/test_cluster_d.py` covers the slice-3 happy paths (ticket
status entity seeded, status_id set, nominate+rotate+no-re-transfer, scan
admit/double/tamper/rotated-dies, derived check-in via `_move_to_key`, auto edge
carried on the copied scope). This file fills the gaps the QA brief calls out,
all mapped to the slice-3 features + AC-03-* ids:

- DERIVED check-in END-TO-END through the real SCAN endpoint (HTTP scan → the
  bus re-derives the participant), not the service shortcut (R3-2 / AC-03-23 in
  the EMS domain).
- The `==` denominator guard: a PARTIAL check-in (1 of 2 admission tickets) does
  NOT advance the participant; the SECOND closes it (R3-2 the centerpiece).
- Owner-scoped aggregate facts: a SIBLING participant's tickets never contribute
  to this participant's count (AC-03-13/33 pattern, EMS domain).
- Fail-isolation: a broken derivation (resolver raises) never 500s the scan
  write — the checkpoint_log + ticket move still commit (AC-03-14).
- The auto Eligible→Checked-in edge is EXCLUDED from a participant's manual
  transition surfaces (AC-03-04 in the EMS domain).
- Segment gating: a checkpoint that gates a segment denies a mismatched ticket
  and WRITES a denied log; the scan endpoint is permission-gated.
- Tampered/garbage QR writes NO log (clean rejection before any record touch).
"""
import pytest

from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from tests.test_cluster_d import (
    _admin,
    _confirm_ticket,
    _ga_offering,
    _make_event,
    _make_product,
    _scope_status_id,
)


# ── helpers ──


def _seed_checked_in(db, tid):
    """Force-set a ticket's legacy mirror to checked_in WITHOUT going through the
    bus (used to fabricate aggregate-fact states for assertions)."""
    from modules.ems.models import Ticket

    t = db.query(Ticket).filter(Ticket.id == tid).first()
    t.status = "checked_in"
    db.commit()


def _move_participant_to_eligible(db, pid, pp):
    """Drive a participant onto Eligible so the auto Eligible→Checked-in edge is
    live (mirror of the coder's centerpiece setup)."""
    from app.models.tenant import DEFAULT_TENANT_ID
    from app.services import status_machine
    from modules.ems.models import PARTICIPANT_ENTITY

    elig = _scope_status_id(db, PARTICIPANT_ENTITY, DEFAULT_TENANT_ID, pid, "eligible")
    status_machine.transition(db, PARTICIPANT_ENTITY, pp, elig, None, tenant_id=DEFAULT_TENANT_ID)
    db.commit()


# ── 1) derived check-in END-TO-END through the real scan endpoint ────────────


def test_scan_endpoint_auto_advances_participant_checked_in(client, session_factory):
    """R3-2 centerpiece, end-to-end: a real HTTP scan checks the ticket in →
    fires the ticket status_changed event → the bus re-derives the participant →
    it auto-advances Eligible→Checked-in WITHOUT a manual participant transition.
    (The coder's test drives the service `_move_to_key`; this proves the whole
    stack through the API surface.)"""
    from app.models.tenant import DEFAULT_TENANT_ID
    from modules.ems.models import PARTICIPANT_ENTITY, Ticket, ProjectParticipant

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, "E2EScan")
    tid = _confirm_ticket(client, session_factory, pid, o["id"], email="e2e@x.com")

    db = session_factory()
    t = db.query(Ticket).filter(Ticket.id == tid).first()
    pp = db.query(ProjectParticipant).filter(ProjectParticipant.id == t.participant_id).first()
    pp_id = pp.id
    qr = t.qr_token
    _move_participant_to_eligible(db, pid, pp)
    db.close()

    cp = client.post(
        f"/ems/projects/{pid}/checkpoints", json={"name": "Gate", "entryType": "single"}, headers=h
    ).json()
    res = client.post(
        f"/ems/projects/{pid}/checkpoints/{cp['id']}/scan", json={"qrToken": qr}, headers=h
    )
    assert res.status_code == 200, res.text
    assert res.json()["result"] == "admitted"

    db = session_factory()
    pp = db.query(ProjectParticipant).filter(ProjectParticipant.id == pp_id).first()
    checked = _scope_status_id(db, PARTICIPANT_ENTITY, DEFAULT_TENANT_ID, pid, "checked_in")
    assert pp.status_id == checked  # auto-advanced via the bus, no manual transition
    db.close()


# ── 2) the `==` denominator guard: PARTIAL check-in must NOT advance ─────────


def test_partial_checkin_does_not_advance_then_full_does(client, session_factory):
    """R3-2 — the auto edge fires only when checkedInTicketCount ==
    admissionTicketCount (>0). With TWO admission tickets on one participant,
    checking ONE in must NOT advance the participant; checking the SECOND does."""
    from app.models.tenant import DEFAULT_TENANT_ID
    from modules.ems.models import PARTICIPANT_ENTITY, Ticket, ProjectParticipant
    from modules.ems.services import CheckoutService, TicketService

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, "Partial")

    # confirm TWO tickets for the SAME attendee email → one participant, two tickets
    db = session_factory()
    CheckoutService(db).confirm(
        DEFAULT_TENANT_ID,
        pid,
        [
            {"offeringId": o["id"], "attendee": {"name": "Twin", "email": "twin@x.com"}},
            {"offeringId": o["id"], "attendee": {"name": "Twin", "email": "twin@x.com"}},
        ],
    )
    db.close()

    db = session_factory()
    tks = (
        db.query(Ticket)
        .filter(Ticket.project_id == pid)
        .order_by(Ticket.created_at.asc())
        .all()
    )
    assert len(tks) == 2
    pp = db.query(ProjectParticipant).filter(ProjectParticipant.id == tks[0].participant_id).first()
    assert tks[0].participant_id == tks[1].participant_id  # both on one participant
    pp_id = pp.id
    _move_participant_to_eligible(db, pid, pp)
    t0_id, t1_id = tks[0].id, tks[1].id
    db.close()

    eligible = None
    checked = None
    db = session_factory()
    eligible = _scope_status_id(db, PARTICIPANT_ENTITY, DEFAULT_TENANT_ID, pid, "eligible")
    checked = _scope_status_id(db, PARTICIPANT_ENTITY, DEFAULT_TENANT_ID, pid, "checked_in")
    db.close()

    # check in ONE ticket → 1 of 2 → participant must STAY eligible
    db = session_factory()
    t0 = db.query(Ticket).filter(Ticket.id == t0_id).first()
    TicketService(db)._move_to_key(DEFAULT_TENANT_ID, t0, "checked_in", None)
    db.close()

    db = session_factory()
    pp = db.query(ProjectParticipant).filter(ProjectParticipant.id == pp_id).first()
    assert pp.status_id == eligible, "1-of-2 check-in must NOT advance the participant"
    db.close()

    # check in the SECOND → 2 of 2 → participant advances to checked_in
    db = session_factory()
    t1 = db.query(Ticket).filter(Ticket.id == t1_id).first()
    TicketService(db)._move_to_key(DEFAULT_TENANT_ID, t1, "checked_in", None)
    db.close()

    db = session_factory()
    pp = db.query(ProjectParticipant).filter(ProjectParticipant.id == pp_id).first()
    assert pp.status_id == checked, "2-of-2 check-in must advance the participant"
    db.close()


# ── 3) owner-scoped aggregate facts: a sibling's tickets never contribute ─────


def test_checkin_aggregate_facts_are_owner_scoped(client, session_factory):
    """AC-03-13/33 (EMS domain) — admissionTicketCount / checkedInTicketCount
    count ONLY the owning participant's own tickets. A sibling participant fully
    checked-in must never tip THIS participant's count (the resolver scopes by
    fk_attr=participant_id AND tenant_id)."""
    from app.models.tenant import DEFAULT_TENANT_ID
    from app.rule_engine.registry import resolve_facts
    from modules.ems.models import Ticket, ProjectParticipant
    from modules.ems.services import CheckoutService

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, "Sibling")

    db = session_factory()
    CheckoutService(db).confirm(
        DEFAULT_TENANT_ID,
        pid,
        [
            {"offeringId": o["id"], "attendee": {"name": "A", "email": "sa@x.com"}},
            {"offeringId": o["id"], "attendee": {"name": "B", "email": "sb@x.com"}},
        ],
    )
    db.close()

    db = session_factory()
    tks = db.query(Ticket).filter(Ticket.project_id == pid).all()
    a = db.query(ProjectParticipant).filter(ProjectParticipant.id == tks[0].participant_id).first()
    b = db.query(ProjectParticipant).filter(ProjectParticipant.id == tks[1].participant_id).first()
    assert a.id != b.id
    # fully check in participant B's ticket (mirror only — fact reads the string)
    tks_b = [t for t in tks if t.participant_id == b.id]
    for t in tks_b:
        t.status = "checked_in"
    db.commit()

    keys = {"record.admissionTicketCount", "record.checkedInTicketCount"}
    fa = resolve_facts(db, {"record:project_participant": a}, only_keys=keys)
    fb = resolve_facts(db, {"record:project_participant": b}, only_keys=keys)
    db.close()

    # A: 1 admission, 0 checked-in (B's check-in does NOT bleed across)
    assert fa["record.admissionTicketCount"] == 1
    assert fa["record.checkedInTicketCount"] == 0
    # B: 1 admission, 1 checked-in (its own)
    assert fb["record.admissionTicketCount"] == 1
    assert fb["record.checkedInTicketCount"] == 1


def test_voided_ticket_excluded_from_admission_count(client, session_factory):
    """The admission denominator counts LIVE tickets only — a void/refunded/
    transferred ticket drops out (so a participant with a voided ticket can still
    derive Checked-in on its remaining live ones)."""
    from app.models.tenant import DEFAULT_TENANT_ID
    from app.rule_engine.registry import resolve_facts
    from modules.ems.models import Ticket, ProjectParticipant
    from modules.ems.services import CheckoutService

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, "VoidExcl")

    db = session_factory()
    CheckoutService(db).confirm(
        DEFAULT_TENANT_ID,
        pid,
        [
            {"offeringId": o["id"], "attendee": {"name": "V", "email": "vv@x.com"}},
            {"offeringId": o["id"], "attendee": {"name": "V", "email": "vv@x.com"}},
        ],
    )
    db.close()

    db = session_factory()
    tks = (
        db.query(Ticket).filter(Ticket.project_id == pid).order_by(Ticket.created_at.asc()).all()
    )
    pp = db.query(ProjectParticipant).filter(ProjectParticipant.id == tks[0].participant_id).first()
    tks[0].status = "void"  # one voided
    tks[1].status = "checked_in"  # the live one checked in
    db.commit()
    f = resolve_facts(
        db,
        {"record:project_participant": pp},
        only_keys={"record.admissionTicketCount", "record.checkedInTicketCount"},
    )
    db.close()
    # void excluded → 1 live admission, 1 checked-in → the `==` guard is satisfiable
    assert f["record.admissionTicketCount"] == 1
    assert f["record.checkedInTicketCount"] == 1


# ── 4) fail-isolation: a broken derivation never 500s the scan write ─────────


def test_broken_derivation_never_500s_the_scan(client, session_factory):
    """AC-03-14 — if a bus subscriber (the derived re-eval seam) raises on the
    ticket status_changed event, the scan write (checkpoint_log + ticket →
    CheckedIn) still succeeds and the endpoint returns 2xx. Each subscriber runs
    in its own commit, isolated (`_notify_subscribers`).

    We inject a deliberately-raising subscriber via the REAL registration path
    (`register_event_subscriber`) — patching the module-level `_on_event` name
    would not work, since the registry captured the original function reference."""
    from app.workflow_engine.entity_events import (
        register_event_subscriber,
        unregister_event_subscriber,
    )
    from modules.ems.models import Ticket, CheckpointLog

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, "Boom")
    tid = _confirm_ticket(client, session_factory, pid, o["id"], email="boom@x.com")

    db = session_factory()
    qr = db.query(Ticket).filter(Ticket.id == tid).first().qr_token
    db.close()

    fired = {"n": 0}

    def _boom(session, ev):
        if ev.get("entity_type") == "ticket" and ev.get("action") == "status_changed":
            fired["n"] += 1
            raise RuntimeError("derivation exploded")

    register_event_subscriber(_boom)
    try:
        cp = client.post(f"/ems/projects/{pid}/checkpoints", json={"name": "BoomGate"}, headers=h).json()
        res = client.post(
            f"/ems/projects/{pid}/checkpoints/{cp['id']}/scan", json={"qrToken": qr}, headers=h
        )
        # the triggering write must NOT 500 despite the broken subscriber
        assert res.status_code == 200, res.text
        assert res.json()["result"] == "admitted"
    finally:
        unregister_event_subscriber(_boom)

    assert fired["n"] >= 1, "the raising subscriber must actually have been invoked"

    db = session_factory()
    t = db.query(Ticket).filter(Ticket.id == tid).first()
    assert t.status == "checked_in"  # ticket move committed despite the explosion
    n = db.query(CheckpointLog).filter(CheckpointLog.ticket_id == tid, CheckpointLog.result == "admitted").count()
    db.close()
    assert n == 1  # checkpoint_log committed


# ── 5) auto edge excluded from the participant's manual transition surfaces ──


def test_auto_checkin_edge_absent_from_participant_transitions(client, session_factory):
    """AC-03-04 (EMS domain) — the system-fired Eligible→Checked-in auto edge is
    NEVER offered as a user action; manual edges from Eligible still appear."""
    from app.models.status_transition import StatusTransition
    from app.models.tenant import DEFAULT_TENANT_ID
    from app.services import status_machine
    from modules.ems.models import PARTICIPANT_ENTITY, Ticket, ProjectParticipant

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, "AutoHide")
    tid = _confirm_ticket(client, session_factory, pid, o["id"], email="hide@x.com")

    db = session_factory()
    t = db.query(Ticket).filter(Ticket.id == tid).first()
    pp = db.query(ProjectParticipant).filter(ProjectParticipant.id == t.participant_id).first()
    _move_participant_to_eligible(db, pid, pp)

    # The auto Eligible→Checked-in edge DOES exist on the copied scope graph...
    elig = _scope_status_id(db, PARTICIPANT_ENTITY, DEFAULT_TENANT_ID, pid, "eligible")
    checked = _scope_status_id(db, PARTICIPANT_ENTITY, DEFAULT_TENANT_ID, pid, "checked_in")
    raw_edge = (
        db.query(StatusTransition)
        .filter(
            StatusTransition.from_status_id == elig,
            StatusTransition.to_status_id == checked,
        )
        .first()
    )
    assert raw_edge is not None and raw_edge.trigger_mode == "auto"

    # ...but it is EXCLUDED from the user-facing transition surface.
    edges = status_machine.available_transitions(
        db, PARTICIPANT_ENTITY, pp, None, tenant_id=DEFAULT_TENANT_ID
    )
    labels = {e.label for e in edges}
    db.close()
    assert "Check in" not in labels  # the derived auto path is never an action


# ── 6) segment gating writes a denied log; scan is permission-gated ─────────


def test_segment_mismatch_denies_and_logs(client, session_factory):
    """A checkpoint that gates a SEGMENT denies a ticket whose participant is not
    in that segment, and WRITES a denied checkpoint_log (audit trail). The ticket
    is NOT moved to checked_in."""
    from app.models.tenant import DEFAULT_TENANT_ID
    from modules.ems.models import Ticket, CheckpointLog

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, "SegGate")
    tid = _confirm_ticket(client, session_factory, pid, o["id"], email="seg@x.com")

    db = session_factory()
    qr = db.query(Ticket).filter(Ticket.id == tid).first().qr_token
    db.close()

    # a checkpoint gating a (made-up) segment the participant isn't in
    cp = client.post(
        f"/ems/projects/{pid}/checkpoints",
        json={"name": "VIP Gate", "segmentId": "seg-does-not-match"},
        headers=h,
    ).json()
    res = client.post(
        f"/ems/projects/{pid}/checkpoints/{cp['id']}/scan", json={"qrToken": qr}, headers=h
    ).json()
    assert res["result"] == "denied"

    db = session_factory()
    t = db.query(Ticket).filter(Ticket.id == tid).first()
    assert t.status == "issued"  # not admitted
    denied = db.query(CheckpointLog).filter(
        CheckpointLog.ticket_id == tid, CheckpointLog.result == "denied"
    ).count()
    db.close()
    assert denied == 1  # the denial is logged


def test_tampered_qr_writes_no_log(client, session_factory):
    """A garbage/tampered token is rejected BEFORE any ticket is resolved, so no
    checkpoint_log row is written (clean rejection, never a 500 — complements the
    coder's tamper test by asserting the no-log invariant)."""
    from modules.ems.models import CheckpointLog

    h = _admin(client)
    pid = _make_event(client, h)
    cp = client.post(f"/ems/projects/{pid}/checkpoints", json={"name": "TamperGate"}, headers=h).json()
    res = client.post(
        f"/ems/projects/{pid}/checkpoints/{cp['id']}/scan",
        json={"qrToken": "not-a-token"},
        headers=h,
    )
    assert res.status_code == 200
    assert res.json()["result"] == "denied"
    db = session_factory()
    n = db.query(CheckpointLog).filter(CheckpointLog.checkpoint_id == cp["id"]).count()
    db.close()
    assert n == 0  # nothing logged for an undecodable token


def test_scan_requires_checkpoints_manage(client, session_factory):
    """The scan endpoint is gated checkpoints.manage — an unauthenticated caller
    is rejected (real boundary, not just UI gating)."""
    h = _admin(client)
    pid = _make_event(client, h)
    cp = client.post(f"/ems/projects/{pid}/checkpoints", json={"name": "AuthGate"}, headers=h).json()
    # no auth header → 401
    res = client.post(
        f"/ems/projects/{pid}/checkpoints/{cp['id']}/scan", json={"qrToken": "x"}
    )
    assert res.status_code == 401


def test_nominate_requires_tickets_manage(client, session_factory):
    """Nomination/transfer is gated tickets.manage — unauthenticated = 401."""
    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, "NomAuth")
    tid = _confirm_ticket(client, session_factory, pid, o["id"], email="na@x.com")
    res = client.post(f"/ems/projects/{pid}/tickets/{tid}/nominate", json={"profileId": "x"})
    assert res.status_code == 401


# ── 7) nomination: invoice/money untouched on transfer ───────────────────────


def test_nominate_leaves_invoice_untouched(client, session_factory):
    """R3 nomination rule — a transfer reassigns the attendee + rotates the QR but
    leaves the money alone: ticket.invoice_id unchanged, invoice total intact."""
    from app.models.tenant import DEFAULT_TENANT_ID
    from app.module_platform import resolve_capability
    from modules.ems.models import Ticket

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, "MoneyNom", price=120)
    tid = _confirm_ticket(client, session_factory, pid, o["id"], email="payer@x.com")

    db = session_factory()
    t = db.query(Ticket).filter(Ticket.id == tid).first()
    inv_id = t.invoice_id
    assert inv_id is not None
    resolver = resolve_capability(db, DEFAULT_TENANT_ID, "invoice.resolve", 1)
    total_before = resolver(db, DEFAULT_TENANT_ID, {"id": inv_id})["total"]
    db.close()

    nominee = client.post("/ems/profiles", json={"email": "newowner@x.com", "fullName": "NO"}, headers=h).json()
    res = client.post(
        f"/ems/projects/{pid}/tickets/{tid}/nominate", json={"profileId": nominee["id"]}, headers=h
    )
    assert res.status_code == 200, res.text

    db = session_factory()
    t = db.query(Ticket).filter(Ticket.id == tid).first()
    assert t.invoice_id == inv_id  # invoice link unchanged
    total_after = resolver(db, DEFAULT_TENANT_ID, {"id": inv_id})["total"]
    db.close()
    assert total_after == total_before  # money untouched


def test_nominate_blocked_for_suspended_nominee(client, session_factory):
    """Foolproof-UI + real boundary — a blocks_access nominee can't receive a
    ticket (422)."""
    from app.models.status import Status
    from app.models.tenant import DEFAULT_TENANT_ID
    from modules.ems.models import Profile

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, "SuspNom")
    tid = _confirm_ticket(client, session_factory, pid, o["id"], email="ok@x.com")

    pr = client.post("/ems/profiles", json={"email": "bad@x.com", "fullName": "Bad"}, headers=h).json()
    db = session_factory()
    blocked = (
        db.query(Status)
        .filter(
            Status.entity_type == "profile",
            Status.tenant_id == DEFAULT_TENANT_ID,
            Status.blocks_access.is_(True),
        )
        .first()
    )
    prof = db.query(Profile).filter(Profile.id == pr["id"]).first()
    prof.status_id = blocked.id
    db.commit()
    db.close()

    res = client.post(
        f"/ems/projects/{pid}/tickets/{tid}/nominate", json={"profileId": pr["id"]}, headers=h
    )
    assert res.status_code == 422


def test_nominate_unknown_profile_422(client, session_factory):
    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, "UnkNom")
    tid = _confirm_ticket(client, session_factory, pid, o["id"], email="u@x.com")
    res = client.post(
        f"/ems/projects/{pid}/tickets/{tid}/nominate", json={"profileId": "ghost-id"}, headers=h
    )
    assert res.status_code == 422


# ── 8) reviewer-flagged regression guards ────────────────────────────────────


def test_checkpoint_entry_type_multi_rejected_single_ok(client, session_factory):
    """Reviewer fix #1 — `CheckpointIn.entryType` allows ONLY "single"
    (multi-entry re-entry tracking is Cluster H; accepting it here would let the
    API be configured into a guaranteed-wrong state — foolproof-UI). A create
    with `entryType:"multi"` is a 422; `"single"` still succeeds (no regression),
    as does the implicit default (omitting the field)."""
    h = _admin(client)
    pid = _make_event(client, h)

    bad = client.post(
        f"/ems/projects/{pid}/checkpoints",
        json={"name": "MultiGate", "entryType": "multi"},
        headers=h,
    )
    assert bad.status_code == 422, bad.text

    ok = client.post(
        f"/ems/projects/{pid}/checkpoints",
        json={"name": "SingleGate", "entryType": "single"},
        headers=h,
    )
    assert ok.status_code in (200, 201), ok.text
    assert ok.json()["entryType"] == "single"

    # the field is optional → omitting it defaults to single, still fine
    default = client.post(
        f"/ems/projects/{pid}/checkpoints", json={"name": "DefaultGate"}, headers=h
    )
    assert default.status_code in (200, 201), default.text
    assert default.json()["entryType"] == "single"


def test_update_tenant_self_heals_ticket_status_graph(session_factory):
    """Reviewer fix #2 — `update_tenant` self-heals a missing ticket status graph
    (a tenant that installed EMS before slice 3 had none → `_status_id_by_key`
    returns None → 409 on the first scan/nominate). Simulate that pre-slice-3
    state by deleting the ticket-entity status rows + edges, confirm the graph is
    gone, then `update_tenant` re-seeds it; a SECOND call is idempotent (no
    duplicate rows)."""
    from app.models.status import Status
    from app.models.status_transition import StatusTransition
    from app.models.tenant import DEFAULT_TENANT_ID
    from modules.ems.bootstrap import update_tenant
    from modules.ems.models import TICKET_ENTITY
    from modules.ems.services import _status_id_by_key

    db = session_factory()
    try:
        # the install fixture already seeded the ticket graph — tear it down to
        # mimic a tenant that predates slice 3.
        ids = [
            r[0]
            for r in db.query(Status.id)
            .filter(
                Status.entity_type == TICKET_ENTITY,
                Status.tenant_id == DEFAULT_TENANT_ID,
                Status.scope_id.is_(None),
            )
            .all()
        ]
        assert ids, "fixture should have seeded a ticket graph to remove"
        db.query(StatusTransition).filter(
            (StatusTransition.from_status_id.in_(ids))
            | (StatusTransition.to_status_id.in_(ids))
        ).delete(synchronize_session=False)
        db.query(Status).filter(Status.id.in_(ids)).delete(synchronize_session=False)
        db.commit()

        # graph is gone → Issued no longer resolves (the pre-slice-3 broken state)
        assert (
            _status_id_by_key(db, TICKET_ENTITY, DEFAULT_TENANT_ID, "issued") is None
        )

        # update_tenant self-heals
        update_tenant(db, DEFAULT_TENANT_ID, from_version="0.0.0")
        db.commit()

        issued = _status_id_by_key(db, TICKET_ENTITY, DEFAULT_TENANT_ID, "issued")
        assert issued is not None  # graph re-seeded, Issued resolves again
        count_after_heal = (
            db.query(Status)
            .filter(
                Status.entity_type == TICKET_ENTITY,
                Status.tenant_id == DEFAULT_TENANT_ID,
                Status.scope_id.is_(None),
            )
            .count()
        )
        edges_after_heal = (
            db.query(StatusTransition)
            .filter(
                StatusTransition.entity_type == TICKET_ENTITY,
                StatusTransition.tenant_id == DEFAULT_TENANT_ID,
            )
            .count()
        )

        # a SECOND call is idempotent — no duplicate status/edge rows
        update_tenant(db, DEFAULT_TENANT_ID, from_version="0.0.0")
        db.commit()
        assert _status_id_by_key(db, TICKET_ENTITY, DEFAULT_TENANT_ID, "issued") == issued
        count_after_second = (
            db.query(Status)
            .filter(
                Status.entity_type == TICKET_ENTITY,
                Status.tenant_id == DEFAULT_TENANT_ID,
                Status.scope_id.is_(None),
            )
            .count()
        )
        edges_after_second = (
            db.query(StatusTransition)
            .filter(
                StatusTransition.entity_type == TICKET_ENTITY,
                StatusTransition.tenant_id == DEFAULT_TENANT_ID,
            )
            .count()
        )
        assert count_after_second == count_after_heal
        assert edges_after_second == edges_after_heal
    finally:
        db.close()


# ── 8) void / refund (AC-05-TKT-04) — QR rotated + RESERVED seat released ─────


def _reserved_seated_ticket(client, session_factory, h, pid, name="VoidVIP"):
    """Build a RESERVED offering with one zone of seats, mint capacity units, then
    confirm one seated ticket through the public cart. Returns (offering, ticket,
    unit) ids."""
    from modules.ems.models import Ticket
    from tests.test_cluster_d import _make_product

    prod_json = _make_product(client, h, name)
    v = client.post("/ems/venues", json={"name": f"{name}Arena"}, headers=h).json()
    z = client.post(f"/ems/venues/{v['id']}/zones", json={"name": "Z"}, headers=h).json()
    client.post(
        "/ems/venues/seats/generate",
        json={"zoneId": z["id"], "rows": 1, "perRow": 2},
        headers=h,
    )
    o = client.post(
        f"/ems/projects/{pid}/offerings",
        json={
            "productId": prod_json["id"],
            "allocationMode": "RESERVED",
            "price": 100,
            "currency": "MYR",
            "taxRate": 0,
            "venueId": v["id"],
            "zoneIds": [z["id"]],
        },
        headers=h,
    ).json()
    client.post(f"/ems/projects/{pid}/offerings/{o['id']}/mint", headers=h)

    cart = client.post(f"/public/register/default/{pid}/cart").json()
    cid = cart["cartId"]
    rows = client.get(f"/public/register/default/{pid}/seatmap/{o['id']}?cart={cid}").json()
    seat_id = rows[0]["seats"][0]["id"]
    client.post(
        f"/public/register/default/{pid}/cart/{cid}/seat",
        json={"offeringId": o["id"], "seatId": seat_id},
    )
    client.post(
        f"/public/register/default/{pid}/cart/{cid}/confirm",
        json={"attendees": [{"name": "Seated", "email": "vseat@x.com"}]},
    )
    db = session_factory()
    t = (
        db.query(Ticket)
        .filter(Ticket.project_id == pid)
        .order_by(Ticket.created_at.desc())
        .first()
    )
    tid, unit_id = t.id, t.capacity_unit_id
    db.close()
    return o["id"], tid, unit_id


def test_void_releases_reserved_seat_and_kills_qr(client, session_factory):
    """AC-05-TKT-04: voiding a RESERVED ticket returns its capacity_unit to
    `free` (sellable again) and rotates the QR so the old token is denied at
    scan."""
    from modules.ems.models import CapacityUnit, Ticket

    h = _admin(client)
    pid = _make_event(client, h)
    _off, tid, unit_id = _reserved_seated_ticket(client, session_factory, h, pid)
    assert unit_id is not None, "RESERVED confirm must occupy a seat"

    db = session_factory()
    old_qr = db.query(Ticket).filter(Ticket.id == tid).first().qr_token
    assert db.query(CapacityUnit).filter(CapacityUnit.id == unit_id).first().status == "sold"
    db.close()

    # void via the real endpoint
    res = client.post(f"/ems/projects/{pid}/tickets/{tid}/void", headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "void"
    assert body["qrRotated"] is True and body["seatReleased"] is True

    db = session_factory()
    t = db.query(Ticket).filter(Ticket.id == tid).first()
    unit = db.query(CapacityUnit).filter(CapacityUnit.id == unit_id).first()
    # seat released back to the pool
    assert unit.status == "free"
    assert unit.participant_id is None and unit.held_until is None and unit.held_by_cart_id is None
    # QR rotated — old token no longer matches the stored nonce
    new_qr = t.qr_token
    assert new_qr != old_qr
    db.close()

    # the OLD token is denied at scan (kills the QR)
    cp = client.post(
        f"/ems/projects/{pid}/checkpoints", json={"name": "Gate", "entryType": "single"}, headers=h
    ).json()
    scan = client.post(
        f"/ems/projects/{pid}/checkpoints/{cp['id']}/scan", json={"qrToken": old_qr}, headers=h
    )
    assert scan.status_code == 200, scan.text
    assert scan.json()["result"] == "denied"


def test_double_void_409(client, session_factory):
    """A ticket already void can no longer be voided (foolproof-UI/backend gate)."""
    h = _admin(client)
    pid = _make_event(client, h)
    _off, tid, _unit = _reserved_seated_ticket(client, session_factory, h, pid, name="DblVoid")
    assert client.post(f"/ems/projects/{pid}/tickets/{tid}/void", headers=h).status_code == 200
    again = client.post(f"/ems/projects/{pid}/tickets/{tid}/void", headers=h)
    assert again.status_code == 409
    assert "no longer" in again.json()["detail"]


def test_refund_releases_seat_and_rotates_qr(client, session_factory):
    """AC-05-TKT-04: refund mirrors void — seat freed, QR rotated, money/invoice
    untouched (the ticket keeps its invoice_id; reversal = Cluster F)."""
    from modules.ems.models import CapacityUnit, Ticket

    h = _admin(client)
    pid = _make_event(client, h)
    _off, tid, unit_id = _reserved_seated_ticket(client, session_factory, h, pid, name="RefVIP")

    db = session_factory()
    old_qr = db.query(Ticket).filter(Ticket.id == tid).first().qr_token
    inv_before = db.query(Ticket).filter(Ticket.id == tid).first().invoice_id
    db.close()

    res = client.post(f"/ems/projects/{pid}/tickets/{tid}/refund", headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "refunded"

    db = session_factory()
    t = db.query(Ticket).filter(Ticket.id == tid).first()
    unit = db.query(CapacityUnit).filter(CapacityUnit.id == unit_id).first()
    assert unit.status == "free"
    assert t.qr_token != old_qr
    assert t.invoice_id == inv_before  # money/invoice untouched
    db.close()

    # refund + then void both blocked once terminal
    assert client.post(f"/ems/projects/{pid}/tickets/{tid}/void", headers=h).status_code == 409


def test_void_ga_frees_the_counter(client, session_factory):
    """A GA ticket has no unit row; voiding it must free the GA counter (the
    sold count excludes void/refunded), making capacity purchasable again."""
    from app.models.tenant import DEFAULT_TENANT_ID
    from modules.ems.models import ProjectProduct
    from modules.ems.services import CartService
    from tests.test_cluster_d import _make_product

    h = _admin(client)
    pid = _make_event(client, h)
    # capacity 1 so the void must free the single seat to allow a 2nd hold
    prod_json = _make_product(client, h, "GAVoid")
    o = client.post(
        f"/ems/projects/{pid}/offerings",
        json={"productId": prod_json["id"], "allocationMode": "GA", "capacity": 1, "price": 10, "currency": "MYR"},
        headers=h,
    ).json()
    tid = _confirm_ticket(client, session_factory, pid, o["id"], email="ga1@x.com")

    db = session_factory()
    off = db.query(ProjectProduct).filter(ProjectProduct.id == o["id"]).first()
    assert CartService(db)._ga_remaining(DEFAULT_TENANT_ID, off) == 0  # sold out
    db.close()

    assert client.post(f"/ems/projects/{pid}/tickets/{tid}/void", headers=h).status_code == 200

    db = session_factory()
    off = db.query(ProjectProduct).filter(ProjectProduct.id == o["id"]).first()
    assert CartService(db)._ga_remaining(DEFAULT_TENANT_ID, off) == 1  # freed by the void
    db.close()


def test_void_requires_tickets_manage(client, session_factory):
    """The void/refund endpoints are gated tickets.manage (unauth → 401)."""
    h = _admin(client)
    pid = _make_event(client, h)
    _off, tid, _u = _reserved_seated_ticket(client, session_factory, h, pid, name="GateVIP")
    assert client.post(f"/ems/projects/{pid}/tickets/{tid}/void").status_code == 401
    assert client.post(f"/ems/projects/{pid}/tickets/{tid}/refund").status_code == 401


def test_tickets_list_exposes_qr_token(client, session_factory):
    """AC-05-TKT-02: the admin tickets list row carries qrToken (so the admin
    Tickets tab can render a real QR)."""
    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, "QrRow")
    _confirm_ticket(client, session_factory, pid, o["id"], email="qr@x.com")
    res = client.get(f"/ems/projects/{pid}/tickets", headers=h)
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert items, "expected at least one ticket row"
    assert items[0]["qrToken"]  # signed/opaque token present


def test_confirm_returns_per_ticket_qr(client, session_factory):
    """AC-05-TKT-02: the confirm result carries per-ticket qrToken so the public
    Done screen renders the real QR from the live confirm response."""
    from app.models.tenant import DEFAULT_TENANT_ID
    from modules.ems.services import CheckoutService

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, "DoneQr")
    db = session_factory()
    order = CheckoutService(db).confirm(
        DEFAULT_TENANT_ID,
        pid,
        [{"offeringId": o["id"], "attendee": {"name": "Done", "email": "done@x.com"}}],
    )
    db.close()
    assert order["ticketCount"] == 1
    assert "tickets" in order and len(order["tickets"]) == 1
    tk = order["tickets"][0]
    assert tk["qrToken"] and tk["ticketId"]
    assert tk["attendeeName"] == "Done"


# ── checkpoint list + recent-logs endpoints (admin Check-in UI) ──────────────


def test_list_checkpoints_returns_project_scoped(client, session_factory):
    """GET /checkpoints lists this project's checkpoints (tenant + project
    scoped); a checkpoint of another project does NOT leak in."""
    h = _admin(client)
    pid_a = _make_event(client, h)
    pid_b = _make_event(client, h)
    cp_a = client.post(
        f"/ems/projects/{pid_a}/checkpoints", json={"name": "GateA"}, headers=h
    ).json()
    client.post(f"/ems/projects/{pid_b}/checkpoints", json={"name": "GateB"}, headers=h)

    res = client.get(f"/ems/projects/{pid_a}/checkpoints", headers=h)
    assert res.status_code == 200, res.text
    rows = res.json()
    assert [c["id"] for c in rows] == [cp_a["id"]]
    assert rows[0]["name"] == "GateA"
    assert rows[0]["entryType"] == "single"


def test_list_checkpoints_requires_read(client):
    """The list endpoint is gated checkpoints.read (unauthenticated = 401)."""
    res = client.get("/ems/projects/whatever/checkpoints")
    assert res.status_code == 401


def test_checkpoint_logs_newest_first_with_attendee_name(client, session_factory):
    """GET /logs returns scan records newest-first with the attendee name
    resolved (ticket → attendee profile). An admit log shows the attendee."""
    h = _admin(client)
    pid = _make_event(client, h)
    o1 = _ga_offering(client, h, pid, "LogVIP1")
    o2 = _ga_offering(client, h, pid, "LogVIP2")
    _confirm_ticket(client, session_factory, pid, o1["id"], email="alice@x.com", name="Alice")
    _confirm_ticket(client, session_factory, pid, o2["id"], email="bob@x.com", name="Bob")

    # resolve each ticket's QR by attendee profile email (the confirm helper's
    # "latest ticket" lookup ties on equal timestamps — go through the profile).
    db = session_factory()
    from modules.ems.models import Profile, Ticket

    def _qr(email):
        prof = db.query(Profile).filter(Profile.email == email).first()
        return db.query(Ticket).filter(Ticket.attendee_profile_id == prof.id).first().qr_token

    qr1 = _qr("alice@x.com")
    qr2 = _qr("bob@x.com")
    db.close()

    cp = client.post(f"/ems/projects/{pid}/checkpoints", json={"name": "LogGate"}, headers=h).json()
    client.post(f"/ems/projects/{pid}/checkpoints/{cp['id']}/scan", json={"qrToken": qr1}, headers=h)
    client.post(f"/ems/projects/{pid}/checkpoints/{cp['id']}/scan", json={"qrToken": qr2}, headers=h)

    res = client.get(f"/ems/projects/{pid}/checkpoints/{cp['id']}/logs", headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 2
    items = body["items"]
    # both admits surface with the resolved attendee names; ordering is by
    # scanned_at desc (microsecond-precise in Postgres; ties on SQLite, so assert
    # the set rather than a flaky tiebreak).
    assert {it["attendeeName"] for it in items} == {"Alice", "Bob"}
    assert all(it["result"] == "admitted" for it in items)
    assert all(it["scannedAt"].endswith("Z") for it in items)
    # newest-first contract: scanned_at is non-increasing down the list
    times = [it["scannedAt"] for it in items]
    assert times == sorted(times, reverse=True)


def test_checkpoint_logs_records_denied_reason(client, session_factory):
    """A denied scan (different-event ticket) is logged with its reason and shows
    up in the recent-logs feed."""
    h = _admin(client)
    pid = _make_event(client, h)
    other = _make_event(client, h)
    o = _ga_offering(client, h, other, "WrongEvent")
    tid = _confirm_ticket(client, session_factory, other, o["id"], email="carol@x.com", name="Carol")
    db = session_factory()
    from modules.ems.models import Ticket

    qr = db.query(Ticket).filter(Ticket.id == tid).first().qr_token
    db.close()

    cp = client.post(f"/ems/projects/{pid}/checkpoints", json={"name": "DenyGate"}, headers=h).json()
    scan = client.post(
        f"/ems/projects/{pid}/checkpoints/{cp['id']}/scan", json={"qrToken": qr}, headers=h
    ).json()
    assert scan["result"] == "denied"

    body = client.get(f"/ems/projects/{pid}/checkpoints/{cp['id']}/logs", headers=h).json()
    assert body["total"] == 1
    log = body["items"][0]
    assert log["result"] == "denied"
    assert log["reason"]


def test_checkpoint_logs_requires_read(client):
    """The logs endpoint is gated checkpoints.read (unauthenticated = 401)."""
    res = client.get("/ems/projects/p/checkpoints/c/logs")
    assert res.status_code == 401
