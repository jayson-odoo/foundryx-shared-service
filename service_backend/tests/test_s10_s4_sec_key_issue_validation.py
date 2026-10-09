"""Sprint-5/10 S4 security round 1 - HIGH 2: `PullKeyService.issue()` must
validate `company_ids` at SAVE TIME, tenant-scoped.

PROVEN (independent Opus security review): a tenant-A admin could issue a
key carrying tenant B's `ac_company.id` (or a made-up id) and both were
stored with no error - exactly the polymorphic-stored-id class that leaked
cross-tenant twice in this codebase already, even though use-time scoping
happens to block a read today.

RED before the fix: every test below currently issues successfully with no
validation at all.
"""
from __future__ import annotations

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.tenant import Tenant


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


OTHER_TENANT = "tenant-other-s10-s4-sec-key-issue"


def _other_tenant(db) -> None:
    if db.get(Tenant, OTHER_TENANT) is None:
        default_tenant = db.get(Tenant, DEFAULT_TENANT_ID)
        db.add(
            Tenant(
                id=OTHER_TENANT, slug="other-s10-s4-sec-key-issue", name="Other Co",
                status_id=default_tenant.status_id,
            )
        )
        db.commit()


def _connection(db, tenant_id=DEFAULT_TENANT_ID):
    from app.models.connection import Connection

    conn = Connection(
        tenant_id=tenant_id, provider="autocount", type="erp", name="db1 REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id, *, tenant_id=DEFAULT_TENANT_ID, database_name="AED_SORENTO"):
    from modules.autocount.models import AcCompany

    company = AcCompany(
        tenant_id=tenant_id, connection_id=connection_id, database_name=database_name,
        company_name="Sorento", name="Sorento", is_active=True, sorento_company_code="SRT",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _issue(db, tenant_id, company_ids):
    from modules.autocount.services.pull_key_service import PullKeyService

    return PullKeyService(db).issue(tenant_id, name="k", company_ids=company_ids)


# ── save-time validation, tenant-scoped, uniform message ────────────────────


def test_issuing_with_another_tenants_company_id_is_refused(db):
    from modules.autocount.services.pull_key_service import PullKeyValidationError

    _other_tenant(db)
    conn = _connection(db, tenant_id=OTHER_TENANT)
    theirs = _company(db, conn.id, tenant_id=OTHER_TENANT, database_name="AED_THEIRS")

    with pytest.raises(PullKeyValidationError):
        _issue(db, DEFAULT_TENANT_ID, [theirs.id])

    from modules.autocount.models import AcPullApiKey

    assert db.query(AcPullApiKey).count() == 0


def test_issuing_with_an_unknown_company_id_is_refused(db):
    from modules.autocount.services.pull_key_service import PullKeyValidationError

    with pytest.raises(PullKeyValidationError):
        _issue(db, DEFAULT_TENANT_ID, ["not-a-real-company-id"])


def test_issuing_with_an_empty_company_set_is_refused(db):
    from modules.autocount.services.pull_key_service import PullKeyValidationError

    with pytest.raises(PullKeyValidationError):
        _issue(db, DEFAULT_TENANT_ID, [])


def test_issuing_with_a_duplicate_company_id_is_refused(db):
    from modules.autocount.services.pull_key_service import PullKeyValidationError

    conn = _connection(db)
    mine = _company(db, conn.id)

    with pytest.raises(PullKeyValidationError):
        _issue(db, DEFAULT_TENANT_ID, [mine.id, mine.id])


def test_the_refusal_message_does_not_reveal_whether_the_id_exists_elsewhere(db):
    """Uniform message for BOTH "genuinely unknown" and "real, but another
    tenant's" - `CompanyRepository.get` is already tenant-scoped so a miss
    for either reason reads identically; this test pins that they are in
    fact identical, not merely both errors."""
    from modules.autocount.services.pull_key_service import PullKeyValidationError

    _other_tenant(db)
    conn = _connection(db, tenant_id=OTHER_TENANT)
    theirs = _company(db, conn.id, tenant_id=OTHER_TENANT, database_name="AED_THEIRS2")

    with pytest.raises(PullKeyValidationError) as unknown_exc:
        _issue(db, DEFAULT_TENANT_ID, ["totally-made-up-id"])
    with pytest.raises(PullKeyValidationError) as cross_tenant_exc:
        _issue(db, DEFAULT_TENANT_ID, [theirs.id])

    assert unknown_exc.value.field_errors == cross_tenant_exc.value.field_errors


def test_issuing_with_a_real_own_tenant_company_id_still_succeeds_control(db):
    """POSITIVE control - the validation itself is sound, not merely
    refusing everything."""
    conn = _connection(db)
    mine = _company(db, conn.id)

    key, plaintext = _issue(db, DEFAULT_TENANT_ID, [mine.id])
    assert plaintext.startswith("fxa_live_")
    assert key.company_ids == [mine.id]


# ── the operator route surfaces the SAME refusal as a 422 ───────────────────


def _auth(client, email="demo@example.com", password="demo1234"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_issue_key_route_422s_on_an_unknown_company_id(client, db):
    headers = _auth(client)
    response = client.post(
        "/autocount/pull/keys",
        json={"name": "bad", "companyIds": ["not-a-real-company-id"]},
        headers=headers,
    )
    assert response.status_code == 422, response.text


# ── kill tests ────────────────────────────────────────────────────────────
#
# * test_issuing_with_another_tenants_company_id_is_refused and
#   test_issuing_with_an_unknown_company_id_is_refused die if `issue()`
#   stores `company_ids` verbatim with no per-id existence check.
# * test_issuing_with_another_tenants_company_id_is_refused ALSO dies if the
#   existence check resolves a company id with an unscoped `get_by_id`
#   (the polymorphic-id leak class) - it would wrongly succeed.
# * test_the_refusal_message_does_not_reveal_whether_the_id_exists_elsewhere
#   dies if the two cases raise with different text (an id-existence oracle).
