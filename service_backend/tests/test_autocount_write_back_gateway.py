"""Plan 55 S5: write-back gateway routes, key scopes, company resolution
(AC-55-40, 41, 43, 44, 45, 04).

Routes call ``WriteBackService`` through the FastAPI dependency
``get_write_back_service`` (overridden here). Two flavours of override:

* a recording SPY service (status mapping, resolved ids, validation);
* the REAL service over a fake AutoCount wrapper (zero-request and
  no-action-row assertions, key id, no secrets).
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from sqlalchemy.sql import func

from app.main import app
from app.models import DEFAULT_TENANT_ID, Role, User, UserStatus
from app.models.connection import Connection
from app.models.tenant import Tenant
from app.repositories.permission_repository import PermissionRepository
from app.secrets import encrypt_secret
from app.security import hash_password
from modules.autocount.models import AcCompany, AcPullApiKey, AcStagedRecord, AcWriteAction
from modules.autocount.services.pull_key_service import PullKeyService
from modules.autocount.write_back.client import AutoCountWriteClient
from modules.autocount.write_back.deps import get_write_back_service
from modules.autocount.write_back.reader import AutoCountDocReader
from modules.autocount.write_back.service import WriteActionResult, WriteBackService
from tests.test_autocount_write_back_service import FakeAutoCount, _load

PREFIX = "/api/v1/autocount"
LINK = f"{PREFIX}/po-links"
UNLINK = f"{PREFIX}/po-links/unlink"
SPO_UNLINK = f"{PREFIX}/spo-links/unlink"
DB3 = "https://ac.example.test/api/db3"
DBNAME = "AED_GW"
OTHER_TENANT = "tenant-other-s55-gateway"
OTHER_SLUG = "other-s55-gateway"
SECRETS = {"appId": "app-secret-gw", "password": "pw-secret-gw"}

LINK_BODY = {
    "companyCode": "SRT", "poDocKey": 12008, "poDtlKey": 12017,
    "soDocKey": 11988, "soDtlKey": 11989, "qty": 10,
}
UNLINK_BODY = {"companyCode": "SRT", "poDocKey": 12008, "poDtlKey": 12013}
SPO_BODY = {"companyCode": "SRT", "spoDocKey": 46179074, "spoDtlKey": 46179075}


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


# ---- seeding ------------------------------------------------------------------

def _other_tenant(db) -> None:
    if db.get(Tenant, OTHER_TENANT) is None:
        default = db.get(Tenant, DEFAULT_TENANT_ID)
        db.add(Tenant(id=OTHER_TENANT, slug=OTHER_SLUG, name="Other Co", status_id=default.status_id))
        db.commit()


def _connection(db, tenant_id=DEFAULT_TENANT_ID, base_url=DB3) -> Connection:
    conn = Connection(
        tenant_id=tenant_id, provider="autocount", type="erp", name="AC",
        config_json={"baseUrl": base_url, "userId": "ADMIN"},
        credentials_json=encrypt_secret(SECRETS), is_active=True,
    )
    db.add(conn)
    db.commit()
    return conn


def _company(db, tenant_id=DEFAULT_TENANT_ID, *, code="SRT", database=DBNAME, write=True) -> AcCompany:
    conn = _connection(db, tenant_id)
    company = AcCompany(
        tenant_id=tenant_id, connection_id=conn.id, database_name=database, company_name=database,
        name=database, is_active=True, sorento_company_code=code,
        write_connection_id=conn.id if write else None,
    )
    db.add(company)
    db.commit()
    return company


def _stage(db, company: AcCompany, entity: str, doc: Dict[str, Any]) -> None:
    raw = {k: v for k, v in doc.items() if k != "Details"}
    raw["_lines"] = copy.deepcopy(doc["Details"])
    db.add(AcStagedRecord(
        tenant_id=company.tenant_id, company_id=company.id, entity_type=entity, job_id="job-1",
        source_ref=f"{company.database_name}:{doc['DocKey']}", doc_no=doc["DocNo"],
        raw_json=raw, canonical_json={}, status="staged",
    ))
    db.commit()


def _key(db, company_ids, *, scopes=None, tenant_id=DEFAULT_TENANT_ID):
    row, plaintext = PullKeyService(db).issue(tenant_id, name="gw", company_ids=company_ids)
    if scopes is not None:
        row.scopes = list(scopes)
        db.commit()
    return row, plaintext


def _hdr(plaintext: str) -> Dict[str, str]:
    return {"X-API-Key": plaintext}


class Spy:
    """Records calls; answers with a canned WriteActionResult."""

    def __init__(self, outcome="done", error_code=None, document=None):
        self.calls: List[tuple] = []
        self.result = WriteActionResult(
            action_id="act-1", outcome=outcome, error_code=error_code, document=document
        )

    def _rec(self, name):
        def fn(**kwargs):
            self.calls.append((name, kwargs))
            return self.result

        return fn

    @property
    def link(self):
        return self._rec("link")

    @property
    def unlink(self):
        return self._rec("unlink")

    @property
    def spo_unlink(self):
        return self._rec("spo_unlink")


def _use(service) -> None:
    app.dependency_overrides[get_write_back_service] = lambda: service


def _real_service(db, session_factory):
    """Real service over a fake wrapper. Returns (service, fake)."""
    fake = FakeAutoCount(db, session_factory)
    fake.serve("purchaseorderbydocdate", _load("po_202602_S0007.json"))
    fake.serve("salesorderbydocdate", _load("so_SO389293.json"))
    service = WriteBackService(
        db,
        client_factory=lambda url: AutoCountWriteClient(url, transport=fake.write_transport),
        reader_factory=lambda url: AutoCountDocReader(url, transport=fake.read_transport),
        sink_factory=lambda *a, **k: SimpleNamespace(
            name="fake", write=lambda *a, **k: None, push=lambda *a, **k: None
        ),
    )
    return service, fake


def _no_action_rows(db) -> bool:
    db.expire_all()
    return db.query(AcWriteAction).count() == 0


@pytest.fixture
def setup(db):
    company = _company(db)
    row, plaintext = _key(db, [company.id], scopes=["write_back"])
    return SimpleNamespace(company=company, key=row, plain=plaintext)


# ---- AC-55-43: status mapping + body shape ---------------------------------------

@pytest.mark.parametrize(
    "outcome,code,status",
    [
        ("done", None, 200),
        ("pending_verification", None, 202),
        ("refused", "WRITE_DISABLED", 403),
        ("refused", "WRITE_NOT_ALLOWED", 403),
        ("refused", "DOC_BUSY", 409),
        ("refused", "DOC_STALE", 409),
        ("refused", "DOC_UNKNOWN", 409),
        ("refused", "ITEM_MISMATCH", 409),
        ("refused", "QTY_ABOVE_OUTSTANDING", 409),
        ("vendor_error", None, 502),
        ("mismatch", None, 502),
    ],
)
def test_ac_55_43_outcome_to_status(client, setup, outcome, code, status):
    spy = Spy(outcome=outcome, error_code=code, document={"DocKey": 12008} if outcome == "done" else None)
    _use(spy)
    r = client.post(LINK, json=LINK_BODY, headers=_hdr(setup.plain))
    assert r.status_code == status, r.text
    body = r.json()
    assert body["actionId"] == "act-1"
    assert body["outcome"] == outcome
    assert body["errorCode"] == code
    assert body["document"] == ({"DocKey": 12008} if outcome == "done" else None)


@pytest.mark.parametrize("path,body,name", [
    (LINK, LINK_BODY, "link"),
    (UNLINK, UNLINK_BODY, "unlink"),
    (SPO_UNLINK, SPO_BODY, "spo_unlink"),
])
def test_ac_55_43_each_route_calls_its_service_method_with_resolved_ids(client, setup, path, body, name):
    spy = Spy()
    _use(spy)
    r = client.post(path, json=body, headers=_hdr(setup.plain))
    assert r.status_code == 200, r.text
    assert len(spy.calls) == 1 and spy.calls[0][0] == name
    kw = spy.calls[0][1]
    assert kw["tenant_id"] == DEFAULT_TENANT_ID
    assert kw["company_id"] == setup.company.id
    assert kw["key_id"] == setup.key.id
    assert kw.get("expected_last_modified") is None
    if name == "link":
        assert (kw["po_doc_key"], kw["po_dtl_key"], kw["so_doc_key"], kw["so_dtl_key"]) == (12008, 12017, 11988, 11989)
        assert kw["qty"] == Decimal(10) and isinstance(kw["qty"], Decimal)
    elif name == "unlink":
        assert (kw["po_doc_key"], kw["po_dtl_key"]) == (12008, 12013)
    else:
        assert (kw["spo_doc_key"], kw["spo_dtl_key"]) == (46179074, 46179075)


def test_ac_55_43_qty_is_parsed_from_the_json_text_not_float(client, setup):
    spy = Spy()
    _use(spy)
    r = client.post(LINK, content=json.dumps({**LINK_BODY, "qty": 3.3}), headers={**_hdr(setup.plain), "Content-Type": "application/json"})
    assert r.status_code == 200, r.text
    assert spy.calls[0][1]["qty"] == Decimal("3.3")


def test_ac_55_43_expected_last_modified_is_forwarded(client, setup):
    spy = Spy()
    _use(spy)
    r = client.post(UNLINK, json={**UNLINK_BODY, "expectedLastModified": "2026-11-04T13:39:22.89"}, headers=_hdr(setup.plain))
    assert r.status_code == 200
    assert spy.calls[0][1]["expected_last_modified"] == "2026-11-04T13:39:22.89"


def test_ac_55_43_body_company_ids_are_ignored(client, setup):
    spy = Spy()
    _use(spy)
    r = client.post(UNLINK, json={**UNLINK_BODY, "tenantId": "evil", "companyId": "evil", "tenant_id": "evil"}, headers=_hdr(setup.plain))
    assert r.status_code == 200
    assert spy.calls[0][1]["tenant_id"] == DEFAULT_TENANT_ID
    assert spy.calls[0][1]["company_id"] == setup.company.id


@pytest.mark.parametrize("path,body", [
    (LINK, {k: v for k, v in LINK_BODY.items() if k != "poDtlKey"}),
    (LINK, {**LINK_BODY, "qty": "ten"}),
    (LINK, {**LINK_BODY, "qty": None}),
    (LINK, {**LINK_BODY, "poDocKey": "abc"}),
    (UNLINK, {k: v for k, v in UNLINK_BODY.items() if k != "poDocKey"}),
    (SPO_UNLINK, {k: v for k, v in SPO_BODY.items() if k != "spoDtlKey"}),
    (LINK, {k: v for k, v in LINK_BODY.items() if k != "companyCode"}),
])
def test_ac_55_43_validation_is_422_without_service_call(client, setup, path, body):
    spy = Spy()
    _use(spy)
    r = client.post(path, json=body, headers=_hdr(setup.plain))
    assert r.status_code == 422, r.text
    assert spy.calls == []


def test_ac_55_43_missing_or_bad_api_key_is_401(client, setup):
    spy = Spy()
    _use(spy)
    assert client.post(LINK, json=LINK_BODY).status_code == 401
    assert client.post(LINK, json=LINK_BODY, headers=_hdr("fxa_live_" + "z" * 43)).status_code == 401
    assert spy.calls == []


# ---- AC-55-44: company resolution ---------------------------------------------------

def test_ac_55_44_unknown_company_code_404_no_requests_no_row(client, db, session_factory, setup):
    service, fake = _real_service(db, session_factory)
    _use(service)
    r = client.post(LINK, json={**LINK_BODY, "companyCode": "NOPE"}, headers=_hdr(setup.plain))
    assert r.status_code == 404
    assert fake.get_calls == [] and fake.put_calls == [] and _no_action_rows(db)


def test_ac_55_44_ambiguous_company_code_409(client, db, session_factory, setup):
    _company(db, database="AED_GW_2")  # second company, same code SRT, same tenant
    service, fake = _real_service(db, session_factory)
    _use(service)
    r = client.post(LINK, json=LINK_BODY, headers=_hdr(setup.plain))
    assert r.status_code == 409
    assert "AMBIGUOUS_COMPANY" in r.text
    assert fake.get_calls == [] and fake.put_calls == [] and _no_action_rows(db)


def test_ac_55_44_company_outside_key_scope_403(client, db, session_factory):
    mine = _company(db, code="MINE", database="AED_MINE")
    theirs = _company(db, code="THEIRS", database="AED_THEIRS")
    _row, plain = _key(db, [mine.id], scopes=["write_back"])
    service, fake = _real_service(db, session_factory)
    _use(service)
    r = client.post(LINK, json={**LINK_BODY, "companyCode": "THEIRS"}, headers=_hdr(plain))
    assert r.status_code == 403
    assert "COMPANY_NOT_ALLOWED" in r.text
    assert fake.get_calls == [] and fake.put_calls == [] and _no_action_rows(db)


def test_ac_55_44_other_tenants_company_with_same_code_is_unreachable(client, db):
    _other_tenant(db)
    a = _company(db, code="SRT", database="AED_A")
    b = _company(db, OTHER_TENANT, code="SRT", database="AED_B")
    _row, plain_a = _key(db, [a.id], scopes=["write_back"])
    spy = Spy()
    _use(spy)
    r = client.post(UNLINK, json=UNLINK_BODY, headers=_hdr(plain_a))
    assert r.status_code == 200
    kw = spy.calls[0][1]
    assert kw["tenant_id"] == DEFAULT_TENANT_ID and kw["company_id"] == a.id != b.id


def test_ac_55_44_key_of_tenant_a_cannot_name_tenant_b_company_id(db):
    _other_tenant(db)
    b = _company(db, OTHER_TENANT, code="SRT", database="AED_B")
    with pytest.raises(Exception):
        PullKeyService(db).issue(DEFAULT_TENANT_ID, name="x", company_ids=[b.id])


# ---- AC-55-40/41: scopes ----------------------------------------------------------------

def test_ac_55_40_key_created_without_scopes_defaults_to_pull(db):
    c = _company(db)
    row, _ = PullKeyService(db).issue(DEFAULT_TENANT_ID, name="old", company_ids=[c.id])
    db.expire_all()
    stored = db.get(AcPullApiKey, row.id)
    assert stored.scopes == ["pull"]


def test_ac_55_40_pull_only_key_is_403_scope_required_on_every_write_route(client, db, session_factory):
    c = _company(db)
    _row, plain = _key(db, [c.id])  # default scopes ["pull"]
    service, fake = _real_service(db, session_factory)
    _use(service)
    for path, body in ((LINK, LINK_BODY), (UNLINK, UNLINK_BODY), (SPO_UNLINK, SPO_BODY)):
        r = client.post(path, json=body, headers=_hdr(plain))
        assert r.status_code == 403, (path, r.text)
        assert "SCOPE_REQUIRED" in r.text
    assert fake.get_calls == [] and fake.put_calls == [] and _no_action_rows(db)


def test_ac_55_40_write_back_only_key_passes_scope_check(client, db):
    c = _company(db)
    _row, plain = _key(db, [c.id], scopes=["write_back"])
    spy = Spy()
    _use(spy)
    assert client.post(LINK, json=LINK_BODY, headers=_hdr(plain)).status_code == 200


def test_ac_55_40_pull_routes_still_work_for_a_pull_key(client, db):
    c = _company(db)
    _row, plain = _key(db, [c.id])
    r = client.post(
        f"{PREFIX}/snapshots", json={"companyCode": "SRT", "entity": "products"}, headers=_hdr(plain)
    )
    # Not a scope refusal: it is whatever the pull path answers (409 PULL_NOT_ENABLED, no task).
    assert r.status_code != 401 and "SCOPE_REQUIRED" not in r.text
    assert r.status_code in (200, 202, 409)


# ---- AC-55-40/45: operator key issue -----------------------------------------------------

def _login(client, email="demo@example.com", password="demo1234"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _limited(db, keys, email):
    role = Role(tenant_id=DEFAULT_TENANT_ID, name=f"Limited {email}", description="")
    role.permissions = [p for p in PermissionRepository(db).list_all() if p.key in keys]
    db.add(role)
    db.flush()
    user = User(
        tenant_id=DEFAULT_TENANT_ID, email=email, password=hash_password("limited1234"),
        name="Limited", status=UserStatus.ACTIVE.value, email_verified_at=func.now(),
    )
    user.roles = [role]
    db.add(user)
    db.commit()


def test_ac_55_41_issue_default_scopes_is_pull(client, db):
    c = _company(db)
    r = client.post("/autocount/pull/keys", json={"name": "k", "companyIds": [c.id]}, headers=_login(client))
    assert r.status_code == 201, r.text
    assert r.json()["key"]["scopes"] == ["pull"]


def test_ac_55_41_issue_with_write_back_as_admin(client, db):
    c = _company(db)
    r = client.post(
        "/autocount/pull/keys",
        json={"name": "k", "companyIds": [c.id], "scopes": ["pull", "write_back"]},
        headers=_login(client),
    )
    assert r.status_code == 201, r.text
    assert sorted(r.json()["key"]["scopes"]) == ["pull", "write_back"]
    stored = db.get(AcPullApiKey, r.json()["key"]["id"])
    assert sorted(stored.scopes) == ["pull", "write_back"]


@pytest.mark.parametrize("scopes", [["admin"], ["write"], [""], "write_back", [1]])
def test_ac_55_41_unknown_scope_is_422_and_no_key(client, db, scopes):
    c = _company(db)
    before = db.query(AcPullApiKey).count()
    r = client.post(
        "/autocount/pull/keys", json={"name": "k", "companyIds": [c.id], "scopes": scopes},
        headers=_login(client),
    )
    assert r.status_code == 422, r.text
    db.expire_all()
    assert db.query(AcPullApiKey).count() == before


def test_ac_55_41_write_back_scope_needs_companies_manage(client, db):
    c = _company(db)
    _limited(db, {"autocount.pull.manage"}, "pullonly-s55@example.com")
    headers = _login(client, "pullonly-s55@example.com", "limited1234")
    before = db.query(AcPullApiKey).count()
    r = client.post(
        "/autocount/pull/keys",
        json={"name": "k", "companyIds": [c.id], "scopes": ["write_back"]}, headers=headers,
    )
    assert r.status_code == 403, r.text
    db.expire_all()
    assert db.query(AcPullApiKey).count() == before
    # the plain pull key is still allowed for that user
    ok = client.post("/autocount/pull/keys", json={"name": "k2", "companyIds": [c.id]}, headers=headers)
    assert ok.status_code == 201, ok.text
    assert ok.json()["key"]["scopes"] == ["pull"]


def test_ac_55_41_list_includes_scopes(client, db):
    c = _company(db)
    _key(db, [c.id], scopes=["pull", "write_back"])
    r = client.get("/autocount/pull/keys", headers=_login(client))
    assert r.status_code == 200
    assert any(sorted(k["scopes"]) == ["pull", "write_back"] for k in r.json())


# ---- AC-55-04 / 45: end to end with the real service ------------------------------------

def _e2e(client, db, session_factory, setup, put_mode="apply"):
    _stage(db, setup.company, "purchase_order", _load("po_202602_S0007.json"))
    _stage(db, setup.company, "sales_order", _load("so_SO389293.json"))
    service, fake = _real_service(db, session_factory)
    fake.put_mode = put_mode
    _use(service)
    r = client.post(LINK, json=LINK_BODY, headers=_hdr(setup.plain))
    return r, fake


def test_ac_55_43_end_to_end_link_done(client, db, session_factory, setup):
    r, fake = _e2e(client, db, session_factory, setup)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "done" and body["errorCode"] is None
    assert any(row["DtlKey"] == 12017 for row in body["document"]["Details"])
    assert len(fake.put_calls) == 1


def test_ac_55_04_response_and_row_never_hold_the_key_or_hash(client, db, session_factory, setup):
    r, _fake = _e2e(client, db, session_factory, setup)
    assert setup.plain not in r.text
    assert setup.key.key_hash not in r.text
    db.expire_all()
    row = db.get(AcWriteAction, r.json()["actionId"])
    assert row.key_id == setup.key.id
    dump = json.dumps({c.name: getattr(row, c.name) for c in AcWriteAction.__table__.columns}, default=str)
    for secret in (setup.plain, setup.key.key_hash, *SECRETS.values()):
        assert secret not in dump


def test_ac_55_04_refused_response_has_no_key_material(client, db, session_factory, setup):
    r, _fake = _e2e(client, db, session_factory, setup, put_mode="vendor_error")
    assert r.status_code == 502
    assert setup.plain not in r.text and setup.key.key_hash not in r.text


def test_ac_55_45_write_disabled_company_is_403_through_the_route(client, db, session_factory):
    c = _company(db, write=False)
    _row, plain = _key(db, [c.id], scopes=["write_back"])
    service, fake = _real_service(db, session_factory)
    _use(service)
    r = client.post(LINK, json=LINK_BODY, headers=_hdr(plain))
    assert r.status_code == 403, r.text
    assert r.json()["errorCode"] == "WRITE_DISABLED"
    assert fake.get_calls == [] and fake.put_calls == []
