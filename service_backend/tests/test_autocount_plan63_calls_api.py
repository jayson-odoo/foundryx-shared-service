"""Plan 63 (RED): the AutoCount calls view API, AC-63-30..33.

``GET {CALLS}`` (JWT, ``autocount.sync.read``, tenant from the JWT only) pages ``ac_api_call_log``
newest first with filters (AND across, OR within a repeated parameter), a server sort on every
column and a 0-based ``page``; ``GET {CALLS}/filter-options``; ``GET {CALLS}/{id}``. Wire is
camelCase with Z-suffixed instants. Every test seeds its own tenant / company / row chain.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import sqlalchemy as sa

from app.models import DEFAULT_TENANT_ID, Role, User, UserStatus
from app.models.tenant import Tenant
from app.repositories.permission_repository import PermissionRepository
from app.security import hash_password
from modules.autocount.models import AcApiCallLog, AcCompany

CALLS = "/autocount/calls"
OTHER_TENANT = "tenant-other-plan63-calls"
T0 = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
MODULE = Path(__file__).resolve().parents[1] / "modules" / "autocount"


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _auth(client, email="demo@example.com", password="demo1234") -> Dict[str, str]:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _limited_user(db, keys: List[str], email: str) -> None:
    perms = PermissionRepository(db)
    role = Role(tenant_id=DEFAULT_TENANT_ID, name=f"Limited {email}", description="")
    role.permissions = [p for p in perms.list_all() if p.key in keys]
    db.add(role)
    db.flush()
    user = User(tenant_id=DEFAULT_TENANT_ID, email=email, password=hash_password("limited1234"), name="Limited",
                status=UserStatus.ACTIVE.value, email_verified_at=sa.func.now())
    user.roles = [role]
    db.add(user)
    db.commit()


def _other_tenant(db) -> None:
    if db.get(Tenant, OTHER_TENANT) is None:
        default = db.get(Tenant, DEFAULT_TENANT_ID)
        db.add(Tenant(id=OTHER_TENANT, slug="other-plan63-calls", name="Other Co", status_id=default.status_id))
        db.commit()


def _company(db, name: str, tenant_id: str = DEFAULT_TENANT_ID) -> AcCompany:
    company = AcCompany(tenant_id=tenant_id, connection_id=str(uuid.uuid4()), database_name=f"DB_{uuid.uuid4().hex[:8]}",
                        company_name=name, name=name, is_active=True, sink_impl="logging")
    db.add(company)
    db.commit()
    return company


def _row(db, company: AcCompany, *, minutes: int = 0, tenant_id: Optional[str] = None, **over: Any) -> str:
    fields: Dict[str, Any] = dict(
        tenant_id=tenant_id or company.tenant_id, company_id=company.id, created_at=T0 + timedelta(minutes=minutes),
        actor="key-1", book="db3", method="PUT", path="/EditSalesOrderbydockey", doc_type="SO", doc_no="SO-1",
        doc_key=1, outcome="ok", response_status=200, response_body="{}", duration_ms=10)
    fields.update(over)
    fields.setdefault("id", str(uuid.uuid4()))
    db.add(AcApiCallLog(**fields))
    db.commit()
    return fields["id"]


def _ids(res) -> List[str]:
    assert res.status_code == 200, res.text
    return [r["id"] for r in res.json()["data"]]


def _get(client, headers, **params) -> Any:
    return client.get(CALLS, headers=headers, params=params)


# ------------------------------------------------------------------ AC-63-30 list, scope, permission

def test_ac_63_30_the_list_is_newest_first_with_the_planned_row_shape(client, db):
    co = _company(db, "Alpha Co")
    old = _row(db, co, minutes=0, doc_no="SO-OLD")
    new = _row(db, co, minutes=30, doc_no="SO-NEW", acting_user_id="u-1", acting_user_name="Una",
               request_id="req-9", error_code=None, response_status=200)
    res = client.get(CALLS, headers=_auth(client))
    assert res.status_code == 200, res.text
    body = res.json()
    assert [r["id"] for r in body["data"]] == [new, old]
    assert body["total"] == 2 and body["page"] == 0
    row = body["data"][0]
    assert set(row) >= {"id", "createdAt", "companyId", "companyName", "book", "actingUserId", "actingUserName",
                        "method", "path", "docType", "docNo", "outcome", "responseStatus", "durationMs",
                        "errorCode", "requestId"}
    assert row["companyName"] == "Alpha Co" and row["companyId"] == co.id
    assert (row["actingUserId"], row["actingUserName"], row["requestId"]) == ("u-1", "Una", "req-9")
    assert row["docNo"] == "SO-NEW" and row["method"] == "PUT" and row["outcome"] == "ok"
    assert row["responseStatus"] == 200 and row["durationMs"] == 10 and row["book"] == "db3"
    assert row["createdAt"].endswith("Z")
    assert "requestJson" not in row and "responseBody" not in row  # detail only


def test_ac_63_30_another_tenants_rows_never_appear(client, db):
    _other_tenant(db)
    mine = _row(db, _company(db, "Mine"), doc_no="SO-MINE")
    theirs_co = _company(db, "Theirs", OTHER_TENANT)
    theirs = _row(db, theirs_co, doc_no="SO-THEIRS")
    res = client.get(CALLS, headers=_auth(client))
    assert _ids(res) == [mine] and res.json()["total"] == 1
    assert theirs not in res.text and "Theirs" not in res.text


def test_ac_63_30_the_tenant_comes_from_the_jwt_never_from_the_query(client, db):
    _other_tenant(db)
    mine = _row(db, _company(db, "Mine"))
    theirs = _row(db, _company(db, "Theirs", OTHER_TENANT))
    hdr = _auth(client)
    for params in ({"tenantId": OTHER_TENANT}, {"tenant_id": OTHER_TENANT}, {"companyId": "x", "tenantId": OTHER_TENANT}):
        res = client.get(CALLS, headers=hdr, params=params)
        ids = [r["id"] for r in res.json()["data"]] if res.status_code == 200 else []
        assert theirs not in ids, params
    assert _ids(client.get(CALLS, headers=hdr, params={"tenantId": OTHER_TENANT})) == [mine]


def test_ac_63_30_no_token_is_401_and_no_permission_is_403(client, db):
    _row(db, _company(db, "Alpha Co"))
    assert client.get(CALLS).status_code == 401
    _limited_user(db, [], "plan63-none@example.com")
    nobody = _auth(client, "plan63-none@example.com", "limited1234")
    assert client.get(CALLS, headers=nobody).status_code == 403
    assert client.get(f"{CALLS}/filter-options", headers=nobody).status_code == 403
    assert client.get(f"{CALLS}/some-id", headers=nobody).status_code == 403


def test_ac_63_30_the_sync_read_permission_alone_is_enough(client, db):
    row = _row(db, _company(db, "Alpha Co"))
    _limited_user(db, ["autocount.sync.read"], "plan63-sync@example.com")
    hdr = _auth(client, "plan63-sync@example.com", "limited1234")
    assert _ids(client.get(CALLS, headers=hdr)) == [row]
    assert client.get(f"{CALLS}/filter-options", headers=hdr).status_code == 200
    assert client.get(f"{CALLS}/{row}", headers=hdr).status_code == 200


def test_ac_63_30_paging_is_zero_based_and_total_counts_every_match(client, db):
    co = _company(db, "Alpha Co")
    ids = [_row(db, co, minutes=m) for m in range(5)]
    newest_first = list(reversed(ids))
    hdr = _auth(client)
    p0 = _get(client, hdr, page=0, pageSize=2)
    p1 = _get(client, hdr, page=1, pageSize=2)
    p2 = _get(client, hdr, page=2, pageSize=2)
    assert _ids(p0) == newest_first[:2] and _ids(p1) == newest_first[2:4] and _ids(p2) == newest_first[4:]
    assert p0.json()["total"] == p1.json()["total"] == 5
    assert (p0.json()["page"], p1.json()["page"], p2.json()["page"]) == (0, 1, 2)
    assert _get(client, hdr, page=0, pageSize=0).status_code == 422
    assert _get(client, hdr, page=-1).status_code == 422


def test_ac_63_30_the_router_holds_no_database_code():
    router = MODULE / "routers" / "calls.py"
    assert router.exists(), "modules/autocount/routers/calls.py is missing"
    text = router.read_text()
    for banned in (".query(", "select(", ".execute(", "session.", "db.add", "db.commit"):
        assert banned not in text, banned
    assert (MODULE / "services" / "call_log_service.py").exists()
    assert (MODULE / "repositories" / "call_log_repository.py").exists()


# ------------------------------------------------------------------ AC-63-31 filters

@pytest.fixture
def dataset(db):
    """Two companies, mixed books / types / outcomes / persons; one more tenant's row for scope."""
    _other_tenant(db)
    a, b = _company(db, "Alpha Co"), _company(db, "Beta Co")
    rows = {
        "r1": _row(db, a, minutes=0, book="db3", doc_type="SO", outcome="ok", acting_user_id="u1", acting_user_name="Una",
                   doc_no="SO-100", request_id="req-100", path="/EditSalesOrderbydockey"),
        "r2": _row(db, a, minutes=60, book="db3", doc_type="QT", outcome="http_error", response_status=500,
                   acting_user_id="u2", acting_user_name="Dan", doc_no="QT-200", request_id="REQ-XYZ",
                   path="/NewQuotation", method="POST"),
        "r3": _row(db, b, minutes=120, book="db1", doc_type="SO", outcome="ok", acting_user_id="u1",
                   acting_user_name="Una", doc_no="SO-300", request_id="req-300", path="/Salesorderbydocno?DocNo=SO-300",
                   method="GET"),
        "r4": _row(db, b, minutes=180, book="db1", doc_type="PO", outcome="timeout", response_status=None,
                   acting_user_id=None, acting_user_name=None, doc_no="PO-400", error_code="WRITE_TIMEOUT"),
        "r5": _row(db, b, minutes=240, book="db3", doc_type="SO", outcome="guard_refused", response_status=None,
                   doc_no="SO-500", error_code="WRITE_NOT_ALLOWED", acting_user_id="u3", acting_user_name="Eve"),
    }
    foreign = _row(db, _company(db, "Elsewhere", OTHER_TENANT), minutes=10, book="db3", doc_type="SO", outcome="ok",
                   acting_user_id="u1", doc_no="SO-100", request_id="req-100")
    return {"a": a, "b": b, "rows": rows, "foreign": foreign}


def _want(ds, *names) -> set:
    return {ds["rows"][n] for n in names}


@pytest.mark.parametrize("params,names", [
    ({"book": "db1"}, ("r3", "r4")),
    ({"book": ["db1", "db3"]}, ("r1", "r2", "r3", "r4", "r5")),
    ({"docType": "SO"}, ("r1", "r3", "r5")),
    ({"docType": ["QT", "PO"]}, ("r2", "r4")),
    ({"outcome": "ok"}, ("r1", "r3")),
    ({"outcome": ["timeout", "guard_refused"]}, ("r4", "r5")),
    ({"person": "u1"}, ("r1", "r3")),
    ({"person": ["u2", "u3"]}, ("r2", "r5")),
    ({"book": "db3", "outcome": "ok"}, ("r1",)),
    ({"book": "db1", "docType": "SO", "outcome": "ok"}, ("r3",)),
    ({"book": "db3", "outcome": ["ok", "http_error"], "person": "u2"}, ("r2",)),
    ({"book": "db1", "outcome": "http_error"}, ()),
])
def test_ac_63_31_value_filters_and_combinations(client, dataset, params, names):
    res = _get(client, _auth(client), **params)
    assert set(_ids(res)) == _want(dataset, *names)
    assert res.json()["total"] == len(names)
    assert dataset["foreign"] not in res.text


def test_ac_63_31_company_filter_single_and_multi(client, dataset):
    hdr = _auth(client)
    a, b = dataset["a"].id, dataset["b"].id
    assert set(_ids(_get(client, hdr, companyId=a))) == _want(dataset, "r1", "r2")
    assert set(_ids(_get(client, hdr, companyId=[a, b]))) == _want(dataset, "r1", "r2", "r3", "r4", "r5")


def test_ac_63_31_a_company_of_another_tenant_matches_nothing(client, db, dataset):
    foreign_company = _company(db, "Ghost", OTHER_TENANT)
    _row(db, foreign_company)
    assert _ids(_get(client, _auth(client), companyId=foreign_company.id)) == []


def test_ac_63_31_date_range_by_instants(client, dataset):
    hdr = _auth(client)
    frm = (T0 + timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
    to = (T0 + timedelta(minutes=150)).isoformat().replace("+00:00", "Z")
    assert set(_ids(_get(client, hdr, dateFrom=frm))) == _want(dataset, "r2", "r3", "r4", "r5")
    assert set(_ids(_get(client, hdr, dateTo=to))) == _want(dataset, "r1", "r2", "r3")
    assert set(_ids(_get(client, hdr, dateFrom=frm, dateTo=to))) == _want(dataset, "r2", "r3")
    assert _ids(_get(client, hdr, dateFrom=to, dateTo=frm)) == []


@pytest.mark.parametrize("term,names", [
    ("SO-100", ("r1",)), ("so-100", ("r1",)), ("req-xyz", ("r2",)), ("REQ-100", ("r1",)),
    ("quotation", ("r2",)), ("SALESORDERBYDOCNO", ("r3",)), ("SO-", ("r1", "r3", "r5")), ("nomatch-zzz", ()),
])
def test_ac_63_31_search_matches_doc_no_request_id_or_path_case_insensitively(client, dataset, term, names):
    res = _get(client, _auth(client), search=term)
    assert set(_ids(res)) == _want(dataset, *names), term
    assert dataset["foreign"] not in res.text


def test_ac_63_31_search_combines_with_filters_by_and(client, dataset):
    assert set(_ids(_get(client, _auth(client), search="SO-", book="db1"))) == _want(dataset, "r3")


def test_ac_63_31_filtered_totals_and_paging_agree(client, dataset):
    hdr = _auth(client)
    p0 = _get(client, hdr, book="db3", page=0, pageSize=2)
    p1 = _get(client, hdr, book="db3", page=1, pageSize=2)
    assert p0.json()["total"] == p1.json()["total"] == 3
    assert set(_ids(p0)) | set(_ids(p1)) == _want(dataset, "r1", "r2", "r5") and len(_ids(p1)) == 1


# ------------------------------------------------------------------ AC-63-32 sort

# wire field -> (column kwarg, values list in "natural ascending" order)
SORTS = {
    "createdAt": ("created_at", None),
    "companyName": ("company", ["c1", "c2", "c3", "c4", "c5"]),
    "book": ("book", ["b1", "b2", "b3", "b4", "b5"]),
    "actingUserName": ("acting_user_name", ["n1", "n2", "n3", "n4", "n5"]),
    "method": ("method", ["DELETE", "GET", "PATCH", "POST", "PUT"]),
    "path": ("path", ["/p1", "/p2", "/p3", "/p4", "/p5"]),
    "docType": ("doc_type", ["PO", "QT", "SO", "SPO", "XX"]),
    "docNo": ("doc_no", ["D1", "D2", "D3", "D4", "D5"]),
    "outcome": ("outcome", ["connect_error", "guard_refused", "http_error", "ok", "timeout"]),
    "responseStatus": ("response_status", [200, 201, 400, 404, 500]),
    "durationMs": ("duration_ms", [5, 15, 25, 35, 45]),
    "errorCode": ("error_code", ["E1", "E2", "E3", "E4", "E5"]),
    "requestId": ("request_id", ["q1", "q2", "q3", "q4", "q5"]),
}


@pytest.fixture
def sortable(db):
    """Five rows whose value order differs per column (rotation by a field-specific stride)."""
    companies = [_company(db, f"c{n}") for n in range(1, 6)]
    by_company = {c.name: c for c in companies}
    strides = {name: [1, 2, 3, 4][i % 4] for i, name in enumerate(SORTS)}
    made: Dict[str, Dict[str, Any]] = {}
    for i in range(5):
        over: Dict[str, Any] = {"minutes": i}
        expected_values: Dict[str, Any] = {}
        for wire, (col, values) in SORTS.items():
            if values is None:
                expected_values[wire] = i
                continue
            value = values[(i * strides[wire]) % 5]
            expected_values[wire] = value
            if col != "company":
                over[col] = value
        company = by_company[expected_values["companyName"]]
        row_id = _row(db, company, **over)
        made[row_id] = expected_values
    return made


def _expected_order(made, wire, desc: bool) -> List[str]:
    return sorted(made, key=lambda rid: made[rid][wire], reverse=desc)


@pytest.mark.parametrize("wire", list(SORTS))
@pytest.mark.parametrize("order", ["asc", "desc"])
def test_ac_63_32_every_column_sorts_asc_and_desc_and_the_order_holds_on_page_two(client, sortable, wire, order):
    hdr = _auth(client)
    expected = _expected_order(sortable, wire, order == "desc")
    full = _ids(_get(client, hdr, sort=wire, order=order, page=0, pageSize=50))
    assert full == expected, (wire, order)
    first = _ids(_get(client, hdr, sort=wire, order=order, page=0, pageSize=2))
    second = _ids(_get(client, hdr, sort=wire, order=order, page=1, pageSize=2))
    third = _ids(_get(client, hdr, sort=wire, order=order, page=2, pageSize=2))
    assert first + second + third == expected, (wire, order)


def test_ac_63_32_the_default_sort_is_newest_first_and_order_defaults_to_desc(client, sortable):
    hdr = _auth(client)
    expected = _expected_order(sortable, "createdAt", True)
    assert _ids(_get(client, hdr)) == expected
    assert _ids(_get(client, hdr, sort="createdAt")) == expected


@pytest.mark.parametrize("bad", ["notAColumn", "tenant_id", "requestJson", "id; drop table x"])
def test_ac_63_32_an_unknown_sort_field_is_422(client, sortable, bad):
    res = _get(client, _auth(client), sort=bad)
    assert res.status_code == 422, res.text


def test_ac_63_32_an_unknown_order_is_422(client, sortable):
    assert _get(client, _auth(client), sort="durationMs", order="sideways").status_code == 422


# ------------------------------------------------------------------ AC-63-33 filter-options and detail

def test_ac_63_33_filter_options_are_the_tenants_distinct_values(client, db, dataset):
    _row(db, dataset["a"], minutes=300, book="db9", doc_type="ZZ", outcome="connect_error",
         acting_user_id="u1", acting_user_name="Una Renamed")
    res = client.get(f"{CALLS}/filter-options", headers=_auth(client))
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) >= {"books", "docTypes", "outcomes", "persons"}
    assert sorted(body["books"]) == ["db1", "db3", "db9"]
    assert sorted(body["docTypes"]) == ["PO", "QT", "SO", "ZZ"]
    assert sorted(body["outcomes"]) == ["connect_error", "guard_refused", "http_error", "ok", "timeout"]
    persons = {p["id"]: p["name"] for p in body["persons"]}
    assert set(persons) == {"u1", "u2", "u3"}
    assert persons["u1"] == "Una Renamed"  # the latest name of a person
    assert len(body["persons"]) == 3  # one entry per person id, rows with no person left out
    assert "Elsewhere" not in res.text


def test_ac_63_33_filter_options_never_list_another_tenants_values(client, db):
    _other_tenant(db)
    _row(db, _company(db, "Theirs", OTHER_TENANT), book="db77", doc_type="TT", outcome="timeout",
         acting_user_id="spy", acting_user_name="Spy")
    _row(db, _company(db, "Mine"), book="db3", doc_type="SO", outcome="ok")
    body = client.get(f"{CALLS}/filter-options", headers=_auth(client)).json()
    assert body["books"] == ["db3"] and body["docTypes"] == ["SO"] and body["outcomes"] == ["ok"]
    assert body["persons"] == []


def test_ac_63_33_filter_options_is_not_swallowed_by_the_id_route(client, db):
    _row(db, _company(db, "Mine"))
    res = client.get(f"{CALLS}/filter-options", headers=_auth(client))
    assert res.status_code == 200 and "books" in res.json()


def test_ac_63_33_detail_returns_the_row_with_request_json_and_response_body(client, db):
    co = _company(db, "Alpha Co")
    rid = _row(db, co, method="PUT", path="/EditSalesOrderbydockey", request_json={"DocKey": 7, "Remark1": "x"},
               response_body='{"DocKey": 7}', response_status=200, doc_no="SO-7", request_id="req-7",
               acting_user_id="u1", acting_user_name="Una")
    res = client.get(f"{CALLS}/{rid}", headers=_auth(client))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == rid and body["docNo"] == "SO-7" and body["companyName"] == "Alpha Co"
    assert body["requestJson"] == {"DocKey": 7, "Remark1": "x"}
    assert body["responseBody"] == '{"DocKey": 7}'
    assert (body["actingUserId"], body["actingUserName"], body["requestId"]) == ("u1", "Una", "req-7")
    assert body["createdAt"].endswith("Z")


def test_ac_63_33_detail_of_a_get_has_no_request_json(client, db):
    rid = _row(db, _company(db, "Alpha Co"), method="GET", request_json=None, response_body="[]")
    body = client.get(f"{CALLS}/{rid}", headers=_auth(client)).json()
    assert body["requestJson"] is None and body["responseBody"] == "[]"


def test_ac_63_33_another_tenants_id_is_404_and_an_unknown_id_is_404(client, db):
    _other_tenant(db)
    theirs = _row(db, _company(db, "Theirs", OTHER_TENANT), request_json={"secret": "theirs"}, response_body="theirs")
    mine = _row(db, _company(db, "Mine"))
    hdr = _auth(client)
    cross = client.get(f"{CALLS}/{theirs}", headers=hdr)
    assert cross.status_code == 404 and "theirs" not in cross.text
    assert client.get(f"{CALLS}/{uuid.uuid4()}", headers=hdr).status_code == 404
    assert client.get(f"{CALLS}/{mine}", headers=hdr).status_code == 200  # control: the route does find a same-tenant row
