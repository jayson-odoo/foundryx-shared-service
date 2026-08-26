"""Numbering engine tests (sprint-4/07, Cluster F) - AC-07-03/04/05/06/07.

format_number token matrix · gapless + consecutive · rollback un-advances the
counter (no gap) · per-period reset · active_modules catalog filter · set_next_val
changes the next generated number · assign-at-state-change synthetic doc_type.
"""
from datetime import date

import pytest

from app.models.tenant import DEFAULT_TENANT_ID
from app.numbering.registry import (
    NumberSequenceDef,
    register_number_sequence,
)
from app.services.numbering_service import (
    NumberingService,
    format_number,
    period_key_for,
)
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


def _admin(client):
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


# ── AC-07-05: format_number token matrix (pure helper) ───────────────────────


def test_format_number_tokens():
    d = date(2026, 6, 9)
    assert format_number("{prefix}{YYYY}-{NNNN}", "INV-", 7, d) == "INV-2026-0007"
    assert format_number("{YY}{MM}{DD}-{NN}", "", 3, d) == "260609-03"
    # pad width = N count; literals pass through
    assert format_number("X/{NNNNN}/Y", "", 42, d) == "X/00042/Y"
    # no prefix token → prefix unused
    assert format_number("{YYYY}{NNNN}", "INV-", 1, d) == "20260001"


def test_period_key_buckets():
    d = date(2026, 6, 9)
    assert period_key_for("never", d) == ""
    assert period_key_for("yearly", d) == "2026"
    assert period_key_for("monthly", d) == "2026-06"


# ── AC-07-04: gapless + consecutive + rollback un-advances ───────────────────


def test_next_number_consecutive_and_gapless(session_factory):
    db = session_factory()
    register_number_sequence(
        NumberSequenceDef("t_gapless", "Gapless test", module="core",
                          default_prefix="G-", default_format="{prefix}{NNNN}",
                          default_reset="never")
    )
    svc = NumberingService(db)
    d = date(2026, 1, 1)
    n1 = svc.next_number(DEFAULT_TENANT_ID, "t_gapless", d)
    n2 = svc.next_number(DEFAULT_TENANT_ID, "t_gapless", d)
    n3 = svc.next_number(DEFAULT_TENANT_ID, "t_gapless", d)
    db.commit()
    assert [n1, n2, n3] == ["G-0001", "G-0002", "G-0003"]
    db.close()


def test_rollback_leaves_counter_unadvanced(session_factory):
    """AC-07-04 - a caller rollback un-advances the counter (no gap). The
    increment rides the caller's transaction (flush, not commit)."""
    db = session_factory()
    register_number_sequence(
        NumberSequenceDef("t_rollback", "Rollback test", module="core",
                          default_prefix="R-", default_format="{prefix}{NNNN}",
                          default_reset="never")
    )
    svc = NumberingService(db)
    d = date(2026, 1, 1)
    first = svc.next_number(DEFAULT_TENANT_ID, "t_rollback", d)
    db.commit()
    assert first == "R-0001"

    # Hand out the next one but ROLL BACK - the counter must un-advance.
    second = svc.next_number(DEFAULT_TENANT_ID, "t_rollback", d)
    assert second == "R-0002"
    db.rollback()

    # The next call returns the SAME number (no gap).
    again = svc.next_number(DEFAULT_TENANT_ID, "t_rollback", d)
    db.commit()
    assert again == "R-0002"
    db.close()


# ── DEFECT-1: first-of-period create is race-safe ────────────────────────────


def test_get_or_create_counter_returns_existing_under_lock(session_factory):
    """The lock-or-create path returns the EXISTING row when one is present
    (no duplicate INSERT, no IntegrityError)."""
    from app.repositories.numbering_repository import NumberingRepository

    db = session_factory()
    repo = NumberingRepository(db)
    a = repo.create_counter(DEFAULT_TENANT_ID, "t_race1", "2026", start=5)
    db.flush()
    b = repo.get_or_create_counter_for_update(DEFAULT_TENANT_ID, "t_race1", "2026")
    assert b.id == a.id
    assert b.next_val == 5
    db.rollback()
    db.close()


def test_create_race_loser_recovers_no_error(session_factory):
    """Simulate the race: a concurrent 'winner' has already inserted the row when
    the 'loser' reaches its create branch. The loser's INSERT trips the unique
    constraint inside the SAVEPOINT; it must rollback the SAVEPOINT, re-fetch the
    winner's row and return it WITHOUT raising - not 500."""
    from app.models.numbering import NumberCounter
    from app.repositories.numbering_repository import NumberingRepository

    db = session_factory()
    repo = NumberingRepository(db)

    # Pre-seed the "winner" row directly via core SQL so the ORM session does not
    # already track it - mirrors a row a concurrent committed transaction wrote.
    winner = NumberCounter(
        tenant_id=DEFAULT_TENANT_ID, doc_type="t_race2", period_key="", next_val=9
    )
    db.add(winner)
    db.flush()
    db.expunge(winner)  # forget it → the next get_counter sees nothing cached

    # The "loser" path: get_counter_for_update inside get_or_create finds the row
    # now (single SQLite connection), so it returns it directly. To force the
    # INSERT-conflict branch, monkeypatch the first lookup to miss once.
    real_lookup = repo.get_counter_for_update
    calls = {"n": 0}

    def _miss_first(tenant_id, doc_type, period_key):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # pretend the row is absent → enter the create branch
        return real_lookup(tenant_id, doc_type, period_key)

    repo.get_counter_for_update = _miss_first  # type: ignore[assignment]
    row = repo.get_or_create_counter_for_update(DEFAULT_TENANT_ID, "t_race2", "")
    assert row.next_val == 9  # recovered the winner's row, no IntegrityError
    db.rollback()
    db.close()


# ── AC-07-05: per-period reset ───────────────────────────────────────────────


def test_per_period_reset_yearly(session_factory):
    db = session_factory()
    register_number_sequence(
        NumberSequenceDef("t_yearly", "Yearly test", module="core",
                          default_prefix="Y-", default_format="{prefix}{YYYY}-{NNNN}",
                          default_reset="yearly")
    )
    svc = NumberingService(db)
    a = svc.next_number(DEFAULT_TENANT_ID, "t_yearly", date(2026, 6, 1))
    b = svc.next_number(DEFAULT_TENANT_ID, "t_yearly", date(2026, 12, 1))
    c = svc.next_number(DEFAULT_TENANT_ID, "t_yearly", date(2027, 1, 1))
    db.commit()
    assert a == "Y-2026-0001"
    assert b == "Y-2026-0002"  # same year → continues
    assert c == "Y-2027-0001"  # new year → resets
    db.close()


def test_per_period_reset_monthly(session_factory):
    db = session_factory()
    register_number_sequence(
        NumberSequenceDef("t_monthly", "Monthly test", module="core",
                          default_prefix="M-", default_format="{prefix}{YYYY}{MM}-{NNN}",
                          default_reset="monthly")
    )
    svc = NumberingService(db)
    a = svc.next_number(DEFAULT_TENANT_ID, "t_monthly", date(2026, 6, 1))
    b = svc.next_number(DEFAULT_TENANT_ID, "t_monthly", date(2026, 6, 28))
    c = svc.next_number(DEFAULT_TENANT_ID, "t_monthly", date(2026, 7, 1))
    db.commit()
    assert a == "M-202606-001"
    assert b == "M-202606-002"
    assert c == "M-202607-001"  # new month → resets
    db.close()


# ── AC-07-03: active_modules catalog filter ──────────────────────────────────


def test_catalog_filters_inactive_modules(session_factory):
    """A doc_type whose module is NOT active for the tenant is absent from the
    catalog; core types are always present."""
    db = session_factory()
    register_number_sequence(
        NumberSequenceDef("t_ghost", "Ghost", module="no_such_module",
                          default_format="{NNNN}")
    )
    items = NumberingService(db).catalog(DEFAULT_TENANT_ID)
    keys = {i.docType for i in items}
    db.close()
    assert "document_no" in keys  # core always visible
    # (finance "invoice" / crm "quotation" doc_types are stripped from this fork)
    assert "t_ghost" not in keys  # inactive module → hidden


# ── AC-07-07: set_next_val changes the next generated number ──────────────────


def test_set_next_val_changes_next_number(session_factory):
    db = session_factory()
    register_number_sequence(
        NumberSequenceDef("t_setnext", "Set next", module="core",
                          default_prefix="S-", default_format="{prefix}{NNNN}",
                          default_reset="never")
    )
    svc = NumberingService(db)
    svc.set_next_val(DEFAULT_TENANT_ID, "t_setnext", 500)
    n = svc.next_number(DEFAULT_TENANT_ID, "t_setnext", date(2026, 1, 1))
    db.commit()
    assert n == "S-0500"
    db.close()


def test_set_format_changes_generated_number(session_factory):
    db = session_factory()
    register_number_sequence(
        NumberSequenceDef("t_setfmt", "Set fmt", module="core",
                          default_prefix="A-", default_format="{prefix}{NNNN}",
                          default_reset="never")
    )
    svc = NumberingService(db)
    svc.set_format(DEFAULT_TENANT_ID, "t_setfmt", "Z-", "{prefix}{YYYY}/{NNN}", "yearly", None)
    n = svc.next_number(DEFAULT_TENANT_ID, "t_setfmt", date(2026, 1, 1))
    db.commit()
    assert n == "Z-2026/001"
    db.close()


# ── AC-07-06: assign-at-state-change synthetic doc_type ──────────────────────


def test_number_assigned_at_state_change(session_factory):
    """A Draft has NO number; it gets one only when the caller invokes
    next_number at the 'issue' step, in the same commit."""
    db = session_factory()
    register_number_sequence(
        NumberSequenceDef("t_doc", "Synthetic doc", module="core",
                          default_prefix="D-", default_format="{prefix}{NNNN}",
                          default_reset="never")
    )

    class _Doc:
        number = None

    doc = _Doc()
    assert doc.number is None  # draft - no number

    # "Issue" step assigns the number in the SAME transaction as the state change.
    svc = NumberingService(db)
    doc.number = svc.next_number(DEFAULT_TENANT_ID, "t_doc", date(2026, 1, 1))
    db.commit()
    assert doc.number == "D-0001"
    db.close()


# ── AC-07-07: settings API (perm-gated, on the resource shell) ───────────────


def test_numbering_api_catalog_and_edit(client, session_factory):
    h = _admin(client)
    res = client.get("/numbering", headers=h)
    assert res.status_code == 200, res.text
    cat = {i["docType"]: i for i in res.json()}
    # core "document_no" (the finance "invoice" doc_type is stripped from this fork)
    assert "document_no" in cat
    assert cat["document_no"]["nextVal"] == 1
    assert cat["document_no"]["sample"]  # live sample present

    # Edit the prefix + next-val → the next generated number reflects both.
    assert client.put(
        "/numbering/document_no",
        json={"prefix": "BILL-", "formatPattern": "{prefix}{NNNN}", "reset": "never"},
        headers=h,
    ).status_code == 204
    assert client.put(
        "/numbering/document_no/next-val", json={"nextVal": 42}, headers=h
    ).status_code == 204

    db = session_factory()
    n = NumberingService(db).next_number(DEFAULT_TENANT_ID, "document_no", date(2026, 1, 1))
    db.commit()
    db.close()
    assert n == "BILL-0042"


def test_numbering_unknown_doctype_422(client):
    h = _admin(client)
    assert client.put(
        "/numbering/not_a_doc", json={"prefix": "", "formatPattern": "{NNNN}", "reset": "never"},
        headers=h,
    ).status_code == 422


def test_numbering_format_must_have_running_token_422(client):
    h = _admin(client)
    assert client.put(
        "/numbering/document_no", json={"prefix": "X-", "formatPattern": "{prefix}{YYYY}", "reset": "never"},
        headers=h,
    ).status_code == 422


def test_numbering_reset_drops_override(client, session_factory):
    h = _admin(client)
    client.put(
        "/numbering/document_no",
        json={"prefix": "BILL-", "formatPattern": "{prefix}{NNNN}", "reset": "never"},
        headers=h,
    )
    assert client.delete("/numbering/document_no", headers=h).status_code == 204
    cat = {i["docType"]: i for i in client.get("/numbering", headers=h).json()}
    assert cat["document_no"]["overridePrefix"] is None
    assert cat["document_no"]["prefix"] == "DOC-"  # back to the registered default


def test_numbering_requires_auth(client):
    assert client.get("/numbering").status_code == 401


def test_admin_has_numbering_perms(client):
    """AC: the new core perms reach the tenant Admin grant (CSV synced)."""
    h = _admin(client)
    assert client.get("/numbering", headers=h).status_code == 200
