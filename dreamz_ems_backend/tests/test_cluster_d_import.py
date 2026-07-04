"""Cluster D bulk-import Ticket mode (sprint-4/05, R3-5) — AC-05-IMP-01..05.

Drives the generic two-phase import (Test = validate dry-run, zero writes →
Import = commit, all-or-nothing) on the project-scoped ``project_participant``
importer with the job-level Ticket mode carried in ``context_json``. Verifies:
GA-only enforcement (RESERVED rejected), capacity-at-Test never oversells, blocked
profiles row-error, Comp = tickets with invoice_id NULL, Paid = N tickets + ONE
consolidated Draft Client invoice.
"""
import json

import pytest

from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


def _login(client, email, pw):
    return client.post("/auth/login", json={"email": email, "password": pw})


def _h(res):
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _admin(client):
    return _h(_login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD))


def _make_event(client, h):
    t = client.post("/ems/project-types", json={"name": "Conference"}, headers=h).json()
    tmpl = client.post(
        "/ems/project-templates", json={"typeId": t["id"], "name": "Std"}, headers=h
    ).json()
    proj = client.post(
        "/ems/projects", json={"templateId": tmpl["id"], "title": "Import Summit"}, headers=h
    ).json()
    return proj["id"]


def _make_product(client, h, name):
    return client.post("/products", json={"name": name, "kind": "admission"}, headers=h).json()


def _offering(client, h, pid, name, *, mode="GA", capacity=100, price=50):
    prod = _make_product(client, h, name)
    return client.post(
        f"/ems/projects/{pid}/offerings",
        json={
            "productId": prod["id"],
            "allocationMode": mode,
            "capacity": capacity,
            "price": price,
            "currency": "MYR",
            "taxRate": 10,
        },
        headers=h,
    ).json()


def _make_client(client, h, name="Acme Corp"):
    return client.post("/crm/clients", json={"name": name}, headers=h).json()


def _csv_rows(emails):
    body = "Profile email\n" + "\n".join(emails) + "\n"
    return body.encode("utf-8")


def _run_import(client, h, pid, emails, *, context_extra=None):
    """Upload → map → (eager validate) → return the job after Test."""
    context = {"project_id": pid}
    context.update(context_extra or {})
    up = client.post(
        "/imports",
        data={
            "entityType": "project_participant",
            "mode": "create_only",
            "context": json.dumps(context),
        },
        files={"file": ("reg.csv", _csv_rows(emails), "application/octet-stream")},
        headers=h,
    )
    assert up.status_code == 201, up.text
    job_id = up.json()["jobId"]
    res = client.put(
        f"/imports/{job_id}/mapping",
        json={"mapping": {"Profile email": "profile"}, "sheetName": None},
        headers=h,
    )
    assert res.status_code == 200, res.text
    job = client.get(f"/imports/{job_id}", headers=h).json()
    return job_id, job


def _commit(client, h, job_id):
    res = client.post(f"/imports/{job_id}/commit", headers=h)
    assert res.status_code == 200, res.text
    return client.get(f"/imports/{job_id}", headers=h).json()


# ── AC-05-IMP-01 — config exposes the participant importer in a project ctx ──


def test_participant_importer_config_carries_ticket_context_keys(client):
    h = _admin(client)
    cfg = client.get("/imports/config/project_participant", headers=h)
    assert cfg.status_code == 200, cfg.text
    keys = cfg.json()["contextKeys"]
    assert {"project_id", "ticket_mode", "offering_id", "bill_to_client_id"} <= set(keys)


# ── AC-05-IMP-02 — GA-only; RESERVED rejected; offering required ──


def test_comp_requires_offering(client):
    h = _admin(client)
    pid = _make_event(client, h)
    _, job = _run_import(
        client, h, pid, ["a@x.com", "b@x.com"], context_extra={"ticket_mode": "comp"}
    )
    assert job["validRows"] == 0
    assert any("offering is required" in e["message"].lower() for e in job["errors"])


def test_reserved_offering_rejected_v1(client):
    h = _admin(client)
    pid = _make_event(client, h)
    o = _offering(client, h, pid, "Reserved", mode="RESERVED", capacity=0)
    _, job = _run_import(
        client, h, pid, ["a@x.com"], context_extra={"ticket_mode": "comp", "offering_id": o["id"]}
    )
    assert job["validRows"] == 0
    assert any("ga offerings" in e["message"].lower() for e in job["errors"])


# ── AC-05-IMP-04 — capacity validated at Test; commit blocked; no oversell ──


def test_capacity_overflow_reported_at_test_and_blocks_commit(client, session_factory):
    from app.models.tenant import DEFAULT_TENANT_ID
    from modules.ems.models import Ticket

    h = _admin(client)
    pid = _make_event(client, h)
    o = _offering(client, h, pid, "Tiny", capacity=2)
    job_id, job = _run_import(
        client,
        h,
        pid,
        ["a@x.com", "b@x.com", "c@x.com"],  # 3 > capacity 2
        context_extra={"ticket_mode": "comp", "offering_id": o["id"]},
    )
    assert job["validRows"] == 0
    assert any("capacity exceeded" in e["message"].lower() for e in job["errors"])

    # commit must not oversell — zero tickets minted.
    done = _commit(client, h, job_id)
    assert done["status"] in ("failed", "done")
    db = session_factory()
    n = db.query(Ticket).filter(Ticket.tenant_id == DEFAULT_TENANT_ID, Ticket.project_product_id == o["id"]).count()
    db.close()
    assert n == 0


# ── AC-05-IMP-05 — blocked-status profile row-errors at Test ──


def test_blocked_profile_row_errors(client, session_factory):
    from app.models.status import Status
    from app.models.tenant import DEFAULT_TENANT_ID
    from modules.ems.models import Profile

    h = _admin(client)
    pid = _make_event(client, h)
    o = _offering(client, h, pid, "BlkImport", capacity=50)
    # pre-create + blacklist a profile
    pr = client.post("/ems/profiles", json={"email": "blocked@x.com", "fullName": "Blk"}, headers=h).json()
    db = session_factory()
    blocked = (
        db.query(Status)
        .filter(Status.entity_type == "profile", Status.tenant_id == DEFAULT_TENANT_ID, Status.blocks_access.is_(True))
        .first()
    )
    db.query(Profile).filter(Profile.id == pr["id"]).update({"status_id": blocked.id})
    db.commit()
    db.close()

    job_id, _ = _run_import(
        client,
        h,
        pid,
        ["blocked@x.com", "fresh@x.com"],
        context_extra={"ticket_mode": "comp", "offering_id": o["id"]},
    )
    # the blocked row makes the all-or-nothing commit fail → no tickets at all.
    done = _commit(client, h, job_id)
    assert done["status"] == "failed"
    errs = " ".join(e["message"].lower() for e in (done["errors"] or []))
    assert "suspended" in errs or "blacklist" in errs


# ── AC-05-IMP-03 — Comp = tickets with invoice_id NULL, no invoice ──


def test_comp_mints_tickets_without_invoice(client, session_factory):
    from app.models.tenant import DEFAULT_TENANT_ID
    from modules.ems.models import ProjectParticipant, Ticket

    h = _admin(client)
    pid = _make_event(client, h)
    o = _offering(client, h, pid, "CompGA", capacity=50)
    job_id, job = _run_import(
        client,
        h,
        pid,
        ["c1@x.com", "c2@x.com"],
        context_extra={"ticket_mode": "comp", "offering_id": o["id"]},
    )
    assert job["validRows"] == 2 and job["invalidRows"] == 0
    done = _commit(client, h, job_id)
    assert done["status"] == "done"

    db = session_factory()
    parts = db.query(ProjectParticipant).filter(ProjectParticipant.project_id == pid).count()
    tickets = db.query(Ticket).filter(Ticket.project_product_id == o["id"]).all()
    db.close()
    assert parts == 2
    assert len(tickets) == 2
    assert all(t.invoice_id is None for t in tickets)
    assert all(t.qr_token for t in tickets)


# ── AC-05-IMP-03 — Paid = N tickets + ONE consolidated Client invoice ──


def test_paid_mints_one_consolidated_client_invoice(client, session_factory):
    from app.models.tenant import DEFAULT_TENANT_ID
    from modules.ems.models import Ticket

    h = _admin(client)
    pid = _make_event(client, h)
    o = _offering(client, h, pid, "PaidGA", capacity=50, price=120)
    acme = _make_client(client, h, "Acme Bulk")
    job_id, job = _run_import(
        client,
        h,
        pid,
        ["p1@x.com", "p2@x.com", "p3@x.com"],
        context_extra={"ticket_mode": "paid", "offering_id": o["id"], "bill_to_client_id": acme["id"]},
    )
    assert job["validRows"] == 3
    done = _commit(client, h, job_id)
    assert done["status"] == "done"

    db = session_factory()
    tickets = db.query(Ticket).filter(Ticket.project_product_id == o["id"]).all()
    db.close()
    assert len(tickets) == 3
    invoice_ids = {t.invoice_id for t in tickets}
    assert len(invoice_ids) == 1  # ONE consolidated invoice
    inv_id = invoice_ids.pop()
    assert inv_id is not None

    # the invoice is a Draft to the Client covering all 3 (qty 3 line).
    inv = client.get(f"/finance/invoices/{inv_id}", headers=h)
    assert inv.status_code == 200, inv.text
    body = inv.json()
    assert body["billToType"] == "Client"
    assert body["billToId"] == acme["id"]
    qty = sum(int(ln["qty"]) for ln in body["lines"])
    assert qty == 3
    assert body["total"] == pytest.approx(3 * 120 * 1.10, rel=1e-3)


def test_paid_requires_bill_to_client(client):
    h = _admin(client)
    pid = _make_event(client, h)
    o = _offering(client, h, pid, "PaidNoClient", capacity=50)
    _, job = _run_import(
        client,
        h,
        pid,
        ["x@x.com"],
        context_extra={"ticket_mode": "paid", "offering_id": o["id"]},
    )
    assert job["validRows"] == 0
    assert any("bill-to client is required" in e["message"].lower() for e in job["errors"])


# ── Participants-only = no tickets, no invoice (default mode unchanged) ──


def test_ticket_options_via_mapping_context_merge(client, session_factory):
    """The FE persists Ticket mode through the mapping(validate) + commit calls
    (not just upload). Verify that path: upload with only project_id, then send
    ticket options via the mapping context → capacity validated, tickets minted."""
    from modules.ems.models import Ticket

    h = _admin(client)
    pid = _make_event(client, h)
    o = _offering(client, h, pid, "MergeGA", capacity=50)
    up = client.post(
        "/imports",
        data={
            "entityType": "project_participant",
            "mode": "create_only",
            "context": json.dumps({"project_id": pid}),
        },
        files={"file": ("reg.csv", _csv_rows(["m1@x.com", "m2@x.com"]), "application/octet-stream")},
        headers=h,
    )
    job_id = up.json()["jobId"]
    res = client.put(
        f"/imports/{job_id}/mapping",
        json={
            "mapping": {"Profile email": "profile"},
            "sheetName": None,
            "context": {"ticket_mode": "comp", "offering_id": o["id"]},
        },
        headers=h,
    )
    assert res.status_code == 200, res.text
    job = client.get(f"/imports/{job_id}", headers=h).json()
    assert job["context"]["ticket_mode"] == "comp"
    assert job["validRows"] == 2
    done = _commit(client, h, job_id)
    assert done["status"] == "done"
    db = session_factory()
    n = db.query(Ticket).filter(Ticket.project_product_id == o["id"]).count()
    db.close()
    assert n == 2


def test_participants_only_creates_no_tickets(client, session_factory):
    from modules.ems.models import ProjectParticipant, Ticket

    h = _admin(client)
    pid = _make_event(client, h)
    job_id, job = _run_import(client, h, pid, ["solo1@x.com", "solo2@x.com"])
    assert job["validRows"] == 2
    done = _commit(client, h, job_id)
    assert done["status"] == "done"

    db = session_factory()
    parts = db.query(ProjectParticipant).filter(ProjectParticipant.project_id == pid).count()
    tickets = db.query(Ticket).filter(Ticket.project_id == pid).count()
    db.close()
    assert parts == 2 and tickets == 0
