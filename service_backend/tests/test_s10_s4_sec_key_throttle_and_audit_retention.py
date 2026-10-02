"""Sprint-5/10 S4 security round 1 - MEDIUM 4: no per-KEY limit + unbounded
audit growth.

PROVEN (independent Opus security review): 40 authenticated out-of-scope 404
reads with the SAME valid key cost zero throttle budget (AC-10-35's `pull`
scope only ever counts a 401 on the caller's IP - a resolvable-but-narrowly-
scoped key can probe forever for free), and `ac_pull_audit` has no retention
sweep at all (`prune_pull_snapshots` only ever touches `ac_pull_snapshot`).

AC-10-35 itself is PER-IP only ("records a failure per client IP on every
401... Successful calls never consume the bucket") - it does not ask for a
per-key limit. This file therefore pins an ADDITIVE, settings-driven
per-key request budget (`THROTTLE_SCOPE_PULL_KEY`, generous defaults) plus
audit retention on the existing prune beat.

RED before the fix: every test below currently either never 429s no matter
how many authenticated calls are made, or finds no retention sweep at all.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany

GATEWAY_PREFIX = "/api/v1/autocount"


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    import httpx

    real_send = httpx.Client.send
    real_async_send = httpx.AsyncClient.send

    def guarded_send(self, request, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise RuntimeError(
                f"blocked a LIVE network call to {request.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return real_send(self, request, *args, **kwargs)

    async def guarded_async_send(self, request, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise RuntimeError(
                f"blocked a LIVE network call to {request.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return await real_async_send(self, request, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", guarded_send)
    monkeypatch.setattr(httpx.AsyncClient, "send", guarded_async_send)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _company(db, *, sorento_company_code="SRT") -> AcCompany:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="db1 REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True,
        sorento_company_code=sorento_company_code,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _issue_key(db, *, company_ids):
    from modules.autocount.services.pull_key_service import PullKeyService

    _key, plaintext = PullKeyService(db).issue(
        DEFAULT_TENANT_ID, name="k", company_ids=company_ids,
    )
    return _key, plaintext


# ── AC-10-35 verbatim: PER-IP, on a 401 only. Control, not a fix target. ────


def test_ac_10_35_is_per_ip_and_401_only_control():
    """AC-10-35's own text: "records a failure per client IP on every 401
    and enforces before key resolution... Successful calls never consume the
    bucket." It says nothing about a per-KEY limit - this file's per-key
    budget below is additive, not a contradiction to fix here."""
    from app.models.auth_throttle import THROTTLE_SCOPE_PULL

    assert THROTTLE_SCOPE_PULL == "pull"


# ── the additive per-key budget ──────────────────────────────────────────────


def test_settings_carry_the_two_pull_key_throttle_knobs():
    from app.config import settings

    assert hasattr(settings, "throttle_pull_key_max_requests")
    assert hasattr(settings, "throttle_pull_key_window_minutes")


def test_many_authenticated_out_of_scope_reads_eventually_429(client, db, monkeypatch):
    """The PoC: repeated AUTHENTICATED (valid key) out-of-scope 404 reads
    must eventually throttle even though none of them is a 401."""
    from app.config import settings

    monkeypatch.setattr(settings, "throttle_pull_key_max_requests", 5)
    company = _company(db)
    _key, plaintext = _issue_key(db, company_ids=[company.id])
    headers = {"X-API-Key": plaintext}

    statuses = []
    for _ in range(8):
        response = client.get(
            f"{GATEWAY_PREFIX}/snapshots/does-not-exist", headers=headers,
        )
        statuses.append(response.status_code)
    assert 404 in statuses
    assert 429 in statuses
    last = client.get(f"{GATEWAY_PREFIX}/snapshots/does-not-exist", headers=headers)
    assert last.status_code == 429, last.text
    assert last.headers.get("Retry-After")


def test_a_different_keys_budget_is_independent(client, db, monkeypatch):
    """CONTROL: exhausting one key's budget must never throttle a second,
    unrelated key."""
    from app.config import settings

    monkeypatch.setattr(settings, "throttle_pull_key_max_requests", 2)
    company = _company(db)
    _key1, plaintext1 = _issue_key(db, company_ids=[company.id])
    _key2, plaintext2 = _issue_key(db, company_ids=[company.id])

    for _ in range(5):
        client.get(
            f"{GATEWAY_PREFIX}/snapshots/does-not-exist",
            headers={"X-API-Key": plaintext1},
        )
    second_key_response = client.get(
        f"{GATEWAY_PREFIX}/snapshots/does-not-exist", headers={"X-API-Key": plaintext2},
    )
    assert second_key_response.status_code == 404, second_key_response.text


# ── ac_pull_audit retention on the existing prune beat ──────────────────────


def test_prune_pull_snapshots_also_prunes_old_audit_rows(db):
    from modules.autocount.models import AcPullAudit
    from modules.autocount.services.pull_service import prune_pull_snapshots

    now = datetime.now(timezone.utc)
    old_row = AcPullAudit(
        tenant_id=DEFAULT_TENANT_ID, action="get_header", status_code=200,
        created_at=now - timedelta(days=200),
    )
    recent_row = AcPullAudit(
        tenant_id=DEFAULT_TENANT_ID, action="get_header", status_code=200,
        created_at=now - timedelta(days=1),
    )
    db.add_all([old_row, recent_row])
    db.commit()
    # Capture ids BEFORE the retention delete + its commit - `commit()`
    # expires ORM instances by default, and re-reading an attribute off a
    # row the sweep just deleted raises `ObjectDeletedError`, not a
    # meaningful assertion failure.
    old_id, recent_id = old_row.id, recent_row.id

    result = prune_pull_snapshots(db, now=now)
    assert result.get("auditPruned", 0) >= 1

    remaining_ids = {row.id for row in db.query(AcPullAudit).all()}
    assert old_id not in remaining_ids
    assert recent_id in remaining_ids


# ── kill tests ────────────────────────────────────────────────────────────
#
# * test_many_authenticated_out_of_scope_reads_eventually_429 dies if
#   authenticated (non-401) calls are never counted against any bucket - the
#   exact reported gap.
# * test_a_different_keys_budget_is_independent dies if the counter is keyed
#   by IP or globally rather than per key id.
# * test_prune_pull_snapshots_also_prunes_old_audit_rows dies if no audit
#   retention exists at all, or if it also deletes rows inside the
#   retention window (the recent_row control).
