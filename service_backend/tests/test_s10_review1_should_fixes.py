"""Sprint-5/10 S1 review round 1 (Opus reviewer) - SHOULD-FIX items 4, 5, 7
(the "every row enabled" assertion), 8.

4. ``EtlSourceConfigIn.lookups`` was ``[] `` by default - a client omitting
   the key wiped a saved lookup forever. Now ``Optional[...] = None``:
   ``None`` keeps what is stored, an EXPLICIT ``[]`` clears it.
5. A cross-tenant test for ``/autocount/http/preview-columns`` (the
   reviewer's kill-test mutation SURVIVED - no test covered this route's
   tenant scoping at all).
7. An explicit assertion that every SO/PO/SPO preset row is enabled
   (companion to the fingerprint re-baseline in ``test_autocount_so_ref.py``
   - constants only there, per the review brief).
8. The lookup probe rows in preview are capped at ``PREVIEW_PAGE_SIZE`` like
   the main path.
"""
from __future__ import annotations

from typing import Any, Dict

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID, Tenant
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany, AcEntityConfig, SOURCE_IMPL_AUTOCOUNT_HTTP
from modules.autocount.presets import PO_PRESET, SO_PRESET, SPO_PRESET
from modules.autocount.services.etl_service import EtlService

DB_NAME = "MOCHA"


# ── should-fix 7: every SO/PO/SPO preset row is enabled ─────────────────────


def test_every_so_po_spo_preset_row_is_enabled():
    for preset in (SO_PRESET, PO_PRESET, SPO_PRESET):
        rows = list(preset.header) + list(preset.line)
        assert rows, f"{preset.label} has no rows"
        disabled = [(r.source_path, r.canonical_field) for r in rows if not r.enabled]
        assert not disabled, f"{preset.label} has disabled rows: {disabled}"


# ── should-fix 4: lookups None (keep) vs [] (clear) ──────────────────────────


def _http_raw(**overrides: Any) -> Dict[str, Any]:
    raw: Dict[str, Any] = {
        "sourceImpl": SOURCE_IMPL_AUTOCOUNT_HTTP,
        "connectionId": None,
        "path": "/itembypage",
        "keyFields": ["ItemCode"],
        "watermarkField": "LastModified",
        "comparedFields": [],
        "distinctOf": None,
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileHours": None,
        "reconcileAt": "02:00",
    }
    raw.update(overrides)
    return raw


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _open_connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="Mocha REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db2", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _open_company(db):
    conn = _open_connection(db)
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name=DB_NAME,
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company, conn


def test_omitting_lookups_on_a_second_save_keeps_the_seeded_preset(db):
    company, conn = _open_company(db)
    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(connectionId=conn.id)
    )
    config = EtlService(db).configs.get(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    seeded = config.source_config.get("lookups")
    assert seeded, "the first save must have seeded the preset's ItemUOM lookup"

    # A second save whose raw payload has NO "lookups" key at all (a client
    # that does not round-trip it) - must KEEP the seeded lookup, never wipe
    # it silently.
    raw = _http_raw(connectionId=conn.id, incrementalMinutes=30)
    assert "lookups" not in raw
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, raw)
    config2 = EtlService(db).configs.get(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert config2.source_config.get("lookups") == seeded


def test_explicit_empty_lookups_list_clears_the_saved_lookups(db):
    company, conn = _open_company(db)
    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(connectionId=conn.id)
    )
    config = EtlService(db).configs.get(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert config.source_config.get("lookups"), "must have seeded first"

    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        _http_raw(connectionId=conn.id, lookups=[]),
    )
    config2 = EtlService(db).configs.get(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert config2.source_config.get("lookups") == []


# ── should-fix 5: cross-tenant /preview-columns ──────────────────────────────


@pytest.fixture
def headers(client):
    response = client.post(
        "/auth/login", json={"email": "demo@example.com", "password": "demo1234"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_preview_columns_rejects_another_tenants_connection_422_never_leaks(client, headers, db):
    """Clones ``test_autocount_http_task_config.py::
    test_preview_http_rejects_another_tenants_connection_422_never_leaks``
    for the ``/preview-columns`` route - the reviewer's kill-test mutation
    survived because no test named this route's tenant scoping at all."""
    other_tenant_id = "tenant-other-review1-preview-columns"
    default_tenant = db.get(Tenant, DEFAULT_TENANT_ID)
    if db.get(Tenant, other_tenant_id) is None:
        db.add(
            Tenant(
                id=other_tenant_id, slug="other-review1-preview-columns",
                name="Other Co", status_id=default_tenant.status_id,
            )
        )
        db.commit()
    other_conn = Connection(
        tenant_id=other_tenant_id, provider="autocount", type="erp", name="Other tenant conn",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(other_conn)
    db.commit()
    db.refresh(other_conn)

    response = client.post(
        "/autocount/http/preview-columns",
        json={"connectionId": other_conn.id, "path": "/itembypage"},
        headers=headers,
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert "connectionId" in body["detail"]["fieldErrors"]
    # Never leaks that a connection of that id exists at all - the SAME
    # "choose an open connection" message as a genuinely unknown id.
    assert other_tenant_id not in response.text
    assert other_conn.id not in str(body["detail"])


# ── should-fix 8: preview caps the lookup probe rows too ────────────────────


def _multi_transport(pages_by_path: Dict[str, Any]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        match = next((p for p in pages_by_path if request.url.path.endswith(p)), None)
        if match is None:
            return httpx.Response(404, text=f"no fixture for {request.url.path}")
        return httpx.Response(200, json=pages_by_path[match])

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_preview_caps_the_lookup_probe_rows_at_preview_page_size(client, headers, db):
    """A server that ignores `pageSize` and answers MORE than requested -
    the main path already guards this with a slice (`rows =
    parsed.rows[:PREVIEW_PAGE_SIZE]`); the lookup path must too. Proven by
    placing item A0's OWN matching remote row PAST the cap boundary: if the
    cap is applied, A0 is a MISS (its match was never indexed); if it is
    NOT applied (the bug), A0 matches."""
    from app.main import app
    from modules.autocount.http_client import get_http_transport
    from modules.autocount.http_source.preview import PREVIEW_PAGE_SIZE

    conn = _open_connection(db)
    over_cap = PREVIEW_PAGE_SIZE + 10
    lookup_rows = [{"ItemCode": f"OTHER{i}", "Price": 1.0} for i in range(over_cap)]
    # A0's own match sits PAST the PREVIEW_PAGE_SIZE boundary.
    lookup_rows[PREVIEW_PAGE_SIZE + 1] = {"ItemCode": "A0", "Price": 99.0}
    app.dependency_overrides[get_http_transport] = lambda: _multi_transport({
        "/itembypage": {
            "TotalCount": 1, "Page": 1, "PageSize": 50, "TotalPages": 1,
            "Data": [{"ItemCode": "A0", "BaseUOM": "UNIT"}],
        },
        "/itemuombypage": {
            "TotalCount": over_cap, "Page": 1, "PageSize": over_cap, "TotalPages": 1,
            "Data": lookup_rows,
        },
    })
    try:
        response = client.post(
            "/autocount/http/preview",
            json={
                "connectionId": conn.id, "path": "/itembypage",
                "lookups": [{
                    "path": "/itemuombypage", "as": "uom",
                    "on": [{"local": "ItemCode", "remote": "ItemCode"}],
                    "fields": [{"remote": "Price", "as": "UomPrice"}],
                }],
            },
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_http_transport, None)
    # sprint-5/11 (AC-11-21/22) - the route is now a 202 job start; poll
    # for the landed `sample` result.
    assert response.status_code == 202, response.text
    poll = client.get(f"/autocount/previews/{response.json()['jobId']}", headers=headers)
    assert poll.status_code == 200, poll.text
    poll_body = poll.json()
    assert poll_body["status"] == "done", poll_body
    body = poll_body["result"]["preview"]
    lookup_counts = body["lookups"][0]
    assert lookup_counts["missed"] == 1, (
        "A0's own match sits past PREVIEW_PAGE_SIZE - the lookup probe must "
        f"be capped the same way the main path is: {lookup_counts}"
    )
    assert lookup_counts["matched"] == 0
    assert "UomPrice" not in (body["rows"][0] if body["rows"] else {})
