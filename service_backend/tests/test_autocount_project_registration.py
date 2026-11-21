"""Plan 71 (lane AUTOCOUNT-PROJREG-SPO-SS): AutoCount project registration routes.

Spec: ``documentation/plans/sprint-5/71-autocount-project-registration.md`` and its UAC
(``71-...-acceptance-criteria.md``, ids AC-71-xx below). The routes run the REAL
``ProjectRegistrationService`` over an in-memory fake of the four wrapper doors
(``NewProjectReg``, ``EditProjectRegbyProjNo``, ``ProjectRegbyProjNo``,
``ProjectRegbyDate``) behind an ``httpx.MockTransport``: no network. All values are
neutral test data.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional

import httpx
import pytest

from app.config import settings
from app.main import app
from modules.autocount.models import AcApiCallLog, AcWriteAction, AcWriteOperation
from modules.autocount.write_back.client import AutoCountWriteClient
from modules.autocount.write_back.reader import AutoCountDocReader
from tests.test_autocount_write_back_gateway import _hdr, _key
from tests.test_autocount_write_back_primitives import DB3, Harness
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

PREFIX = "/api/v1/autocount/project-registrations"
PROJ = "PPF26110001"
OTHER = "PPF26110002"


# ── a fake of the four wrapper doors ─────────────────────────────────────────

class FakeProjRegVendor:
    """Holds registrations by ProjNo. AutoCount upper-cases SalesAgent / State / Mukim /
    TypeofBuilding and always reads Status back as ``Pending`` (live shape, 21 Nov)."""

    UPPER = ("SalesAgent", "State", "Mukim", "TypeofBuilding")

    def __init__(self) -> None:
        self.store: Dict[str, Dict[str, Any]] = {}
        self.dates: Dict[str, str] = {}
        self.calls: List[Dict[str, Any]] = []
        self.inject: List[Dict[str, Any]] = []
        self.ignore: List[str] = []  # fields the next write keeps as before
        self.transport = httpx.MockTransport(self._handle)

    # ---- helpers
    def seed(self, proj_no: str, record: Optional[Dict[str, Any]] = None, day: str = "20261121") -> Dict[str, Any]:
        rec = {"ProjNo": proj_no, "ProjectTitle": "SEEDED", "Status": "Pending", "SalesAgent": "AGT",
               "Developer": "", "Architect": "", "MainContractor": ""}
        rec.update(record or {})
        self.store[proj_no] = rec
        self.dates[proj_no] = day
        return rec

    def writes(self) -> List[Dict[str, Any]]:
        return [c for c in self.calls if c["method"] != "GET"]

    def gets(self) -> List[Dict[str, Any]]:
        return [c for c in self.calls if c["method"] == "GET"]

    def next(self, method: str, leaf: str, mode: str, **kw: Any) -> None:
        self.inject.append(dict(method=method, leaf=leaf.lower(), mode=mode, **kw))

    def _take(self, method: str, leaf: str) -> Optional[Dict[str, Any]]:
        for inj in self.inject:
            if inj["method"] == method and inj["leaf"] == leaf:
                self.inject.remove(inj)
                return inj
        return None

    def _stored(self, body: Dict[str, Any], before: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        rec = dict(before or {})
        for k, v in body.items():
            if k in self.ignore and before is not None:
                continue
            if k in self.ignore:
                rec[k] = ""
                continue
            rec[k] = v.upper() if k in self.UPPER and isinstance(v, str) else v
        rec["Status"] = "Pending"
        self.ignore = []
        return rec

    # ---- the transport
    def _handle(self, request: httpx.Request) -> httpx.Response:
        leaf = request.url.path.rsplit("/", 1)[-1].lower()
        body = json.loads(request.content) if request.content else None
        call = {"method": request.method, "leaf": leaf, "query": dict(request.url.params), "body": body,
                "headers": dict(request.headers)}
        self.calls.append(call)
        inj = self._take(request.method, leaf)
        if inj and inj["mode"] == "timeout":
            raise httpx.ReadTimeout("injected")
        if inj and inj["mode"] == "fail":
            return httpx.Response(inj.get("status", 500), text=inj.get("text", "boom"))
        if inj and inj["mode"] == "refuse":
            return httpx.Response(400, json={"Message": "An error has occurred.",
                                             "ExceptionMessage": inj.get("text", "Sales agent is not valid."),
                                             "ExceptionType": "AutoCount.AppException"})
        response = self._route(request.method, leaf, call)
        if inj and inj["mode"] == "apply_then_timeout":
            raise httpx.ReadTimeout("injected after apply")
        return response

    def _route(self, method: str, leaf: str, call: Dict[str, Any]) -> httpx.Response:
        if method == "GET" and leaf == "projectregbyprojno":
            rec = self.store.get(call["query"].get("ProjNo", ""))
            return httpx.Response(200, json=[copy.deepcopy(rec)] if rec else [])
        if method == "GET" and leaf == "projectregbydate":
            day = call["query"].get("Date")
            return httpx.Response(200, json=[copy.deepcopy(r) for p, r in self.store.items() if self.dates[p] == day])
        if method == "POST" and leaf == "newprojectreg":
            proj_no = call["body"].get("ProjNo")
            if proj_no in self.store:
                return httpx.Response(400, json={"Message": "An error has occurred.",
                                                 "ExceptionMessage": "Project No already exists."})
            self.store[proj_no] = self._stored(call["body"], None)
            self.dates[proj_no] = "20261121"
            return httpx.Response(200, text=f"ProjNo={proj_no} Created Successful.")
        if method == "PUT" and leaf == "editprojectregbyprojno":
            proj_no = call["body"].get("ProjNo")
            if proj_no not in self.store:
                return httpx.Response(400, json={"Message": "An error has occurred.",
                                                 "ExceptionMessage": "Project No not found."})
            self.store[proj_no] = self._stored(call["body"], self.store[proj_no])
            return httpx.Response(200, text="Done Edit.")
        return httpx.Response(404, text="no such door")


# ── rig ──────────────────────────────────────────────────────────────────────

def _deps():
    from modules.autocount.write_back import deps

    return deps.get_project_registration_service, deps.get_operation_service


class Rig:
    def __init__(self, h: Harness, db) -> None:
        self.h, self.db = h, db
        self.vendor = FakeProjRegVendor()
        h.company.sorento_company_code = "SRT"
        db.commit()
        self.key, self.plain = _key(db, [h.company.id], scopes=["write_back"])
        get_reg, get_ops = _deps()
        app.dependency_overrides[get_reg] = lambda: self.service()
        app.dependency_overrides[get_ops] = lambda: self.ops()

    def factories(self) -> Dict[str, Any]:
        return dict(
            client_factory=lambda url: AutoCountWriteClient(url, transport=self.vendor.transport),
            reader_factory=lambda url: AutoCountDocReader(url, transport=self.vendor.transport),
        )

    def service(self):
        from modules.autocount.write_back.project_registration import ProjectRegistrationService

        return ProjectRegistrationService(self.db, **self.factories())

    def ops(self):
        from modules.autocount.write_back.operations import OperationService

        return OperationService(self.db, **self.h.factories())

    def hdr(self, idem: Optional[str] = "reg-key-1", **extra: str) -> Dict[str, str]:
        out = _hdr(self.plain)
        if idem:
            out["Idempotency-Key"] = idem
        out.update(extra)
        return out


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def h(db, session_factory, monkeypatch):
    return Harness(db, session_factory, monkeypatch)


@pytest.fixture
def switch_on(monkeypatch):
    monkeypatch.setattr(settings, "autocount_project_registration_enabled", True)


@pytest.fixture
def rig(h, db, switch_on):
    yield Rig(h, db)
    app.dependency_overrides.clear()


@pytest.fixture
def rig_off(h, db):
    yield Rig(h, db)
    app.dependency_overrides.clear()


def code(r) -> Optional[str]:
    body = r.json()
    return body.get("errorCode") or body.get("code")


def reg(proj_no: Optional[str] = PROJ, **over: Any) -> Dict[str, Any]:
    """The whole record as the CRM sends it (Part A field list); neutral values."""
    fields = {"projNo": proj_no, "projectTitle": "NEW HOUSE\nLOT 1", "distributorName": "DIST A",
              "salesAgent": "agt", "customerName": "CUSTOMER A", "date": "2026-11-21",
              "typeOfBuilding": "bungalow", "state": "selangor", "mukim": "mukim a", "developer": "",
              "architect": "", "mainContractor": "", "status": "Pending"}
    if proj_no is None:
        fields.pop("projNo")
    fields.update(over)
    return fields


def create_body(proj_no: str = PROJ, **over: Any) -> Dict[str, Any]:
    body = {"companyCode": "SRT", "registration": reg(proj_no)}
    body.update(over)
    return body


def edit_body(**over: Any) -> Dict[str, Any]:
    body = {"companyCode": "SRT", "registration": reg(None, projectTitle="RENAMED")}
    body.update(over)
    return body


# ── AC-71-01..03: the switch (OFF by default) ────────────────────────────────

def test_ac_71_01_switch_is_off_by_default():
    assert settings.autocount_project_registration_enabled is False


@pytest.mark.parametrize("method,path,body", [
    ("post", PREFIX, create_body()),
    ("patch", f"{PREFIX}/{PROJ}", edit_body()),
    ("get", f"{PREFIX}/{PROJ}?companyCode=SRT", None),
    ("get", f"{PREFIX}?companyCode=SRT&date=2026-11-21", None),
])
def test_ac_71_02_switch_off_refuses_every_route_and_sends_nothing(client, rig_off, method, path, body):
    kwargs = {"headers": rig_off.hdr()}
    if body is not None:
        kwargs["json"] = body
    r = getattr(client, method)(path, **kwargs)
    assert r.status_code == 409 and code(r) == "VENDOR_UNSUPPORTED", r.text
    assert r.json()["outcome"] == "refused"
    assert rig_off.vendor.calls == []


def test_ac_71_03_capability_feed_lists_project_registrations(client, rig_off, monkeypatch):
    r = client.get("/api/v1/autocount/write-capabilities?companyCode=SRT", headers=rig_off.hdr(idem=None))
    entries = {(c["op"], c["kind"]): c for c in r.json()["capabilities"]}
    for op in ("create_doc", "edit_doc"):
        e = entries[(op, "project-registrations")]
        assert e["enabled"] is False and e["reasonCode"] == "VENDOR_UNSUPPORTED"
    monkeypatch.setattr(settings, "autocount_project_registration_enabled", True)
    r = client.get("/api/v1/autocount/write-capabilities?companyCode=SRT", headers=rig_off.hdr(idem=None))
    entries = {(c["op"], c["kind"]): c for c in r.json()["capabilities"]}
    for op in ("create_doc", "edit_doc"):
        assert entries[(op, "project-registrations")] == {
            "op": op, "kind": "project-registrations", "enabled": True, "reasonCode": None}


# ── AC-71-10..19: create ─────────────────────────────────────────────────────

def test_ac_71_10_create_needs_an_idempotency_key(client, rig):
    r = client.post(PREFIX, json=create_body(), headers=rig.hdr(idem=None))
    assert r.status_code == 422 and code(r) == "IDEMPOTENCY_KEY_REQUIRED"
    assert rig.vendor.calls == []


def test_ac_71_11_create_reads_first_posts_reads_back_and_answers_done(client, rig):
    r = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "done" and body["errorCode"] is None and body["warnings"] == []
    assert body["changedFields"] == []
    assert body["projNo"] == PROJ and body["operationId"]
    # the registration as AutoCount holds it now (upper-cased by AutoCount: not a mismatch)
    assert body["registration"]["SalesAgent"] == "AGT" and body["registration"]["State"] == "SELANGOR"
    assert body["registration"]["ProjectTitle"] == "NEW HOUSE\nLOT 1"
    steps = [(c["method"], c["leaf"]) for c in rig.vendor.calls]
    assert steps == [("GET", "projectregbyprojno"), ("POST", "newprojectreg"), ("GET", "projectregbyprojno")]
    sent = rig.vendor.writes()[0]["body"]
    assert sent["ProjNo"] == PROJ and sent["TypeofBuilding"] == "bungalow" and sent["MainContractor"] == ""
    assert sent["Date"] == "2026-11-21T00:00:00" and sent["DistributorName"] == "DIST A"
    assert set(sent) == {"ProjNo", "ProjectTitle", "DistributorName", "SalesAgent", "CustomerName", "Date",
                         "TypeofBuilding", "State", "Mukim", "Developer", "Architect", "MainContractor", "Status"}
    assert rig.vendor.gets()[0]["query"] == {"ProjNo": PROJ}


def test_ac_71_12_every_wrapper_call_is_logged_with_trace(client, rig, db):
    headers = rig.hdr(**{"X-Request-ID": "trace-71", "X-Acting-User-Id": "u-7", "X-Acting-User-Name": "Tester"})
    r = client.post(PREFIX, json=create_body(), headers=headers)
    assert r.status_code == 200, r.text
    db.expire_all()
    rows = db.query(AcApiCallLog).order_by(AcApiCallLog.created_at).all()
    assert [(x.method, x.path.split("?")[0]) for x in rows] == [
        ("GET", "/ProjectRegbyProjNo"), ("POST", "/NewProjectReg"), ("GET", "/ProjectRegbyProjNo")]
    for row in rows:
        assert row.request_id == "trace-71" and row.acting_user_id == "u-7" and row.acting_user_name == "Tester"
        assert row.doc_type == "PROJREG" and row.doc_no == PROJ and row.book == "db3"
        assert row.operation_id == r.json()["operationId"]
    action = db.query(AcWriteAction).filter(AcWriteAction.doc_type == "PROJREG").one()
    assert action.action == "create_doc" and action.outcome == "done"
    assert action.request_id == "trace-71" and action.acting_user_id == "u-7"


def test_ac_71_13_existing_projno_is_refused_with_autocounts_record(client, rig):
    rig.vendor.seed(PROJ, {"ProjectTitle": "ALREADY THERE"})
    r = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert r.status_code == 409 and code(r) == "REGISTRATION_EXISTS", r.text
    assert r.json()["outcome"] == "refused"
    assert r.json()["registration"]["ProjectTitle"] == "ALREADY THERE"
    assert rig.vendor.writes() == []


def test_ac_71_14_same_key_same_body_replays_without_a_call(client, rig):
    first = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    n = len(rig.vendor.calls)
    again = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert again.status_code == 200 and again.json() == first.json()
    assert len(rig.vendor.calls) == n


def test_ac_71_15_same_key_other_body_is_a_conflict(client, rig):
    client.post(PREFIX, json=create_body(), headers=rig.hdr())
    r = client.post(PREFIX, json=create_body(OTHER), headers=rig.hdr())
    assert r.status_code == 409 and code(r) == "IDEMPOTENCY_CONFLICT"
    assert OTHER not in rig.vendor.store


def test_ac_71_16_unclear_create_that_landed_is_looked_up_and_done(client, rig):
    rig.vendor.next("POST", "NewProjectReg", "apply_then_timeout")
    r = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert r.status_code == 200 and r.json()["outcome"] == "done", r.text
    assert len(rig.vendor.writes()) == 1


def test_ac_71_17_unclear_create_not_found_is_pending_then_resend_looks_up_first(client, rig, db):
    rig.vendor.next("POST", "NewProjectReg", "timeout")
    r = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert r.status_code == 202 and r.json()["outcome"] == "pending_verification", r.text
    assert code(r) == "WRITE_TIMEOUT"
    before = len(rig.vendor.calls)
    again = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert again.status_code == 200 and again.json()["outcome"] == "done", again.text
    resend = [(c["method"], c["leaf"]) for c in rig.vendor.calls[before:]]
    assert resend[0] == ("GET", "projectregbyprojno")  # looked up before any re-send
    assert resend.count(("POST", "newprojectreg")) == 1


def test_ac_71_18_unclear_create_whose_readback_failed_is_found_on_resend_without_a_second_post(client, rig):
    rig.vendor.next("POST", "NewProjectReg", "apply_then_timeout")
    original = rig.vendor._route
    state = {"posted": False, "failed": False}

    def route(method, leaf, call):  # the first GET after the POST fails
        if method == "POST":
            state["posted"] = True
        if method == "GET" and state["posted"] and not state["failed"]:
            state["failed"] = True
            return httpx.Response(500, text="down")
        return original(method, leaf, call)

    rig.vendor._route = route
    r = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert r.status_code == 202 and r.json()["outcome"] == "pending_verification", r.text
    again = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert again.status_code == 200 and again.json()["outcome"] == "done", again.text
    assert len(rig.vendor.writes()) == 1


def test_ac_71_19_vendor_refusal_is_shown_and_releases_the_key(client, rig):
    rig.vendor.next("POST", "NewProjectReg", "refuse", text="Sales agent is not valid.")
    r = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert r.status_code == 409 and r.json()["outcome"] == "refused" and code(r) == "VENDOR_REFUSED"
    assert r.json()["message"] == "Sales agent is not valid."
    again = client.post(PREFIX, json=create_body(), headers=rig.hdr())  # fixed the cause, try again
    assert again.status_code == 200 and again.json()["outcome"] == "done", again.text


def test_ac_71_20_a_field_autocount_did_not_keep_is_a_warning_with_its_value(client, rig):
    rig.vendor.ignore = ["Mukim", "TypeofBuilding"]
    r = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert r.status_code == 200 and r.json()["outcome"] == "done" and r.json()["errorCode"] is None, r.text
    assert r.json()["warnings"] == ["FIELD_CHANGED"]
    assert r.json()["changedFields"] == [
        {"field": "mukim", "sent": "mukim a", "autocount": ""},
        {"field": "typeOfBuilding", "sent": "bungalow", "autocount": ""},
    ]
    assert "mukim" in r.json()["message"] and r.json()["registration"]["ProjNo"] == PROJ


def test_ac_71_21_body_is_validated_before_any_call(client, rig):
    cases = [
        (create_body(registration=reg("")), 422, "FIELD_REQUIRED"),
        (create_body(registration=reg(None)), 422, "FIELD_REQUIRED"),
        ({"companyCode": "SRT"}, 422, "FIELD_REQUIRED"),
        (create_body(registration=reg(projectTitle={"nested": 1})), 422, "INVALID_REQUEST"),
        (create_body(registration=reg(typeofBuilding="x")), 422, "INVALID_REQUEST"),  # not a known field
        (create_body(registration=reg(date="21/11/2026")), 422, "INVALID_REQUEST"),
        (create_body(registration=["x"]), 422, "INVALID_REQUEST"),
        (create_body(projNo=PROJ), 422, "INVALID_REQUEST"),  # projNo lives inside registration
    ]
    for i, (body, status, err) in enumerate(cases):
        r = client.post(PREFIX, json=body, headers=rig.hdr(idem=f"k-{i}"))
        assert r.status_code == status and code(r) == err, (i, r.text)
    assert rig.vendor.calls == []


def test_ac_71_22_pull_only_key_is_refused(client, rig, db, h):
    _row, plain = _key(db, [h.company.id])
    r = client.post(PREFIX, json=create_body(), headers={**_hdr(plain), "Idempotency-Key": "x"})
    assert r.status_code == 403 and code(r) == "SCOPE_REQUIRED"
    assert rig.vendor.calls == []


def test_ac_71_23_live_book_is_never_written(client, rig, db, h):
    h.conn.config_json = {"baseUrl": DB3.replace("db3", "db1"), "userId": "ADMIN"}
    db.commit()
    r = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert r.status_code == 403 and code(r) == "WRITE_NOT_ALLOWED", r.text
    assert rig.vendor.calls == []


# ── AC-71-30..33: edit ───────────────────────────────────────────────────────

def test_ac_71_30_edit_puts_the_whole_record_and_reads_it_back(client, rig):
    rig.vendor.seed(PROJ)
    r = client.patch(f"{PREFIX}/{PROJ}", json=edit_body(), headers=rig.hdr())
    assert r.status_code == 200 and r.json()["outcome"] == "done", r.text
    assert r.json()["registration"]["ProjectTitle"] == "RENAMED" and r.json()["projNo"] == PROJ
    steps = [(c["method"], c["leaf"]) for c in rig.vendor.calls]
    assert steps == [("GET", "projectregbyprojno"), ("PUT", "editprojectregbyprojno"), ("GET", "projectregbyprojno")]
    put = rig.vendor.writes()[0]
    assert put["body"]["ProjNo"] == PROJ and put["query"] == {}
    assert set(put["body"]) >= {"ProjectTitle", "SalesAgent", "TypeofBuilding", "State", "Mukim", "Developer"}


def test_ac_71_31_edit_of_unknown_projno_is_refused_without_a_put(client, rig):
    r = client.patch(f"{PREFIX}/{PROJ}", json=edit_body(), headers=rig.hdr())
    assert r.status_code == 409 and code(r) == "REGISTRATION_NOT_FOUND", r.text
    assert rig.vendor.writes() == []


def test_ac_71_32_edit_without_key_runs_and_an_unclear_put_is_checked(client, rig):
    rig.vendor.seed(PROJ)
    rig.vendor.next("PUT", "EditProjectRegbyProjNo", "apply_then_timeout")
    r = client.patch(f"{PREFIX}/{PROJ}", json=edit_body(), headers=rig.hdr(idem=None))
    assert r.status_code == 200 and r.json()["outcome"] == "done", r.text


def test_ac_71_33_edit_body_cannot_rename_the_projno(client, rig):
    rig.vendor.seed(PROJ)
    r = client.patch(f"{PREFIX}/{PROJ}", json=edit_body(registration=reg(projNo=OTHER)), headers=rig.hdr())
    assert r.status_code == 422 and code(r) == "INVALID_REQUEST"
    assert rig.vendor.calls == []


# ── AC-71-40..42: reads (for linking back) ───────────────────────────────────

def test_ac_71_40_read_by_projno(client, rig):
    rig.vendor.seed(PROJ, {"ProjectTitle": "LINE 1\nLINE 2"})
    r = client.get(f"{PREFIX}/{PROJ}?companyCode=SRT", headers=rig.hdr(idem=None))
    assert r.status_code == 200 and r.json()["outcome"] == "done" and r.json()["found"] is True, r.text
    assert r.json()["registration"]["ProjectTitle"] == "LINE 1\nLINE 2"
    assert rig.vendor.writes() == []


def test_ac_71_41_read_of_unknown_projno_answers_found_false(client, rig):
    rig.vendor.seed(OTHER)
    r = client.get(f"{PREFIX}/{PROJ}?companyCode=SRT", headers=rig.hdr(idem=None))
    assert r.status_code == 200 and r.json()["outcome"] == "done", r.text
    assert r.json()["found"] is False and r.json()["registration"] is None


def test_ac_71_42_read_by_date_passes_yyyymmdd(client, rig):
    rig.vendor.seed(PROJ, day="20261121")
    rig.vendor.seed(OTHER, day="20261120")
    r = client.get(f"{PREFIX}?companyCode=SRT&date=2026-11-21", headers=rig.hdr(idem=None))
    assert r.status_code == 200 and r.json()["outcome"] == "done", r.text
    assert [x["ProjNo"] for x in r.json()["registrations"]] == [PROJ]
    assert rig.vendor.gets()[0]["leaf"] == "projectregbydate" and rig.vendor.gets()[0]["query"] == {"Date": "20261121"}
    bad = client.get(f"{PREFIX}?companyCode=SRT&date=21/11/2026", headers=rig.hdr(idem=None))
    assert bad.status_code == 422 and code(bad) == "INVALID_REQUEST"


def test_ac_71_43_every_wrapper_call_uses_the_esb_user_agent(client, rig):
    from modules.autocount.http_source.client import USER_AGENT

    client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert rig.vendor.calls and {c["headers"].get("user-agent") for c in rig.vendor.calls} == {USER_AGENT}


def test_ac_71_44_operation_row_is_stored_for_create(client, rig, db):
    r = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    db.expire_all()
    op = db.query(AcWriteOperation).filter(AcWriteOperation.id == r.json()["operationId"]).one()
    assert op.op == "create_doc:PROJREG" and op.status == "done" and op.doc_type == "PROJREG"


def test_ac_71_45_a_pending_create_that_landed_with_a_changed_field_is_done_on_resend(client, rig):
    rig.vendor.ignore = ["DistributorName"]  # AutoCount does not keep one sent field
    rig.vendor.next("POST", "NewProjectReg", "apply_then_timeout")
    original = rig.vendor._route
    state = {"posted": False, "failed": False}

    def route(method, leaf, call):  # the read-back after the POST fails once
        if method == "POST":
            state["posted"] = True
        if method == "GET" and state["posted"] and not state["failed"]:
            state["failed"] = True
            return httpx.Response(500, text="down")
        return original(method, leaf, call)

    rig.vendor._route = route
    r = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert r.status_code == 202, r.text
    again = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert again.status_code == 200 and again.json()["outcome"] == "done", again.text
    assert again.json()["warnings"] == ["FIELD_CHANGED"]
    assert again.json()["changedFields"][0]["field"] == "distributorName"
    assert len(rig.vendor.writes()) == 1
    third = client.post(PREFIX, json=create_body(), headers=rig.hdr())  # done now locks the key
    assert third.json() == again.json() and len(rig.vendor.writes()) == 1


def test_ac_71_45b_a_crashed_create_found_with_other_fields_is_refused_exists(client, rig, db, h):
    from modules.autocount.write_back.project_registration import _hash

    _op_row(db, h, key="reg-key-1", age_seconds=3600, key_id=rig.key.id,  # this key's run died:
            request_hash=_hash("create_doc:PROJREG", create_body()))      # not known if it was sent
    rig.vendor.seed(PROJ, {"ProjectTitle": "SOMEONE ELSE"})
    r = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert r.status_code == 409 and code(r) == "REGISTRATION_EXISTS", r.text
    assert r.json()["registration"]["ProjectTitle"] == "SOMEONE ELSE"
    assert rig.vendor.writes() == []


def test_ac_71_46_a_bare_5xx_on_create_is_checked_not_assumed(client, rig):
    rig.vendor.next("POST", "NewProjectReg", "fail", status=503, text="")
    r = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert r.status_code == 202 and r.json()["outcome"] == "pending_verification", r.text
    again = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert again.status_code == 200 and again.json()["outcome"] == "done", again.text


def test_ac_71_47_edit_difference_is_a_warning_not_a_failure(client, rig):
    rig.vendor.seed(PROJ)
    rig.vendor.ignore = ["Architect"]
    r = client.patch(f"{PREFIX}/{PROJ}", json=edit_body(registration=reg(None, architect="ARCH A")),
                     headers=rig.hdr())
    assert r.status_code == 200 and r.json()["outcome"] == "done", r.text
    assert r.json()["warnings"] == ["FIELD_CHANGED"]
    assert r.json()["changedFields"] == [{"field": "architect", "sent": "ARCH A", "autocount": ""}]


# ── review round 1 (security): lock per ProjNo, masked refusal text, input hygiene ──

def _op_row(db, h, *, key="other-key", age_seconds=0, status="in_progress", key_id=None, request_hash="x"):
    from datetime import datetime, timedelta, timezone

    from app.models import DEFAULT_TENANT_ID
    from modules.autocount.write_back.project_registration import lock_key

    at = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    row = AcWriteOperation(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, key_id=key_id, idempotency_key=key,
        request_hash=request_hash, op="create_doc:PROJREG", doc_type="PROJREG", doc_key=lock_key(PROJ),
        status=status, snapshot_json={"projNo": PROJ}, created_at=at, updated_at=at,
    )
    db.add(row)
    db.commit()
    return row


def test_ac_71_48_another_running_write_of_the_same_projno_is_busy(client, rig, db, h):
    _op_row(db, h)
    r = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert r.status_code == 409 and code(r) == "DOC_BUSY", r.text
    assert rig.vendor.calls == []
    other = client.post(PREFIX, json=create_body(OTHER), headers=rig.hdr(idem="reg-key-2"))
    assert other.status_code == 200, other.text  # another ProjNo is not held


def test_ac_71_49_a_crashed_run_no_longer_holds_the_projno(client, rig, db, h):
    _op_row(db, h, age_seconds=3600)
    r = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert r.status_code == 200 and r.json()["outcome"] == "done", r.text


def test_ac_71_52_a_keyless_edit_waits_for_an_in_flight_write_of_the_same_projno(client, rig, db, h):
    from datetime import datetime, timezone

    from app.models import DEFAULT_TENANT_ID
    from modules.autocount.write_back.project_registration import lock_key

    rig.vendor.seed(PROJ)
    db.add(AcWriteAction(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, action="edit_doc",
                         doc_type="PROJREG", doc_key=lock_key(PROJ), outcome="in_flight",
                         created_at=datetime.now(timezone.utc)))
    db.commit()
    r = client.patch(f"{PREFIX}/{PROJ}", json=edit_body(), headers=rig.hdr(idem=None))
    assert r.status_code == 409 and code(r) == "DOC_BUSY", r.text
    assert rig.vendor.writes() == []


def test_ac_71_53_the_lock_number_is_never_a_real_dockey():
    from modules.autocount.write_back.project_registration import lock_key

    assert 2**62 <= lock_key(PROJ) < 2**63 and lock_key(PROJ) == lock_key(" ppf26110001 ")
    assert lock_key(PROJ) != lock_key(OTHER)


def test_ac_71_54_autocounts_refusal_text_never_carries_the_api_key(client, rig, db, h):
    from app.secrets import encrypt_secret

    h.conn.credentials_json = encrypt_secret({"apiKey": "testkey-999"})
    db.commit()
    rig.vendor.next("POST", "NewProjectReg", "refuse", text="Invalid API key testkey-999 for this book")
    r = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert r.status_code == 409 and code(r) == "VENDOR_REFUSED", r.text
    assert "testkey-999" not in r.text
    db.expire_all()
    op = db.query(AcWriteOperation).filter(AcWriteOperation.id == r.json()["operationId"]).one()
    assert "testkey-999" not in json.dumps(op.result_json)


def test_ac_71_55_input_hygiene(client, rig):
    bad = [
        create_body(registration=reg("PPF2611'0001")),
        create_body(registration=reg("<PPF>")),
        create_body(registration=reg(projectTitle="A\x00B")),
        create_body(registration=reg(state="SEL‮ANGOR")),
    ]
    for i, body in enumerate(bad):
        r = client.post(PREFIX, json=body, headers=rig.hdr(idem=f"bad-{i}"))
        assert r.status_code == 422 and code(r) == "INVALID_REQUEST", (i, r.text)
    assert rig.vendor.calls == []
    ok = client.post(PREFIX, json=create_body(registration=reg(projectTitle="LINE 1\r\nLINE 2\tX")),
                     headers=rig.hdr(idem="ok-1"))
    assert ok.status_code == 200, ok.text
    old = client.post(PREFIX, json=create_body(registration=reg("P/2019-0001")), headers=rig.hdr(idem="ok-2"))
    assert old.status_code == 200, old.text  # AutoCount's own older numbers still pass


def test_ac_71_56_a_number_with_a_slash_reads_and_edits_by_path(client, rig):
    number = "P/2019-0001"
    rig.vendor.seed(number)
    for path in (f"{PREFIX}/{number}", f"{PREFIX}/P%2F2019-0001"):
        r = client.get(f"{path}?companyCode=SRT", headers=rig.hdr(idem=None))
        assert r.status_code == 200 and r.json()["found"] is True, (path, r.text)
    e = client.patch(f"{PREFIX}/{number}", json=edit_body(), headers=rig.hdr(idem=None))
    assert e.status_code == 200 and e.json()["projNo"] == number, e.text


# ── review round 1 (code): the read decides after a non-2xx; case; pending lock; audit row; deadline ──

def test_ac_71_57_a_5xx_with_a_reason_after_the_create_landed_is_done(client, rig):
    original = rig.vendor._route

    def route(method, leaf, call):
        response = original(method, leaf, call)
        if method == "POST":  # applied, then AutoCount answers 500 with a reason
            return httpx.Response(500, json={"Message": "An error has occurred.", "ExceptionMessage": "Timeout expired."})
        return response

    rig.vendor._route = route
    r = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert r.status_code == 200 and r.json()["outcome"] == "done", r.text


def test_ac_71_58_an_edit_refused_that_changed_nothing_is_refused(client, rig):
    rig.vendor.seed(PROJ)
    rig.vendor.next("PUT", "EditProjectRegbyProjNo", "refuse", text="Project title too long.")
    r = client.patch(f"{PREFIX}/{PROJ}", json=edit_body(), headers=rig.hdr())
    assert r.status_code == 409 and code(r) == "VENDOR_REFUSED" and r.json()["message"] == "Project title too long."


def test_ac_71_59_a_lower_case_projno_is_found_when_autocount_upper_cases_it(client, rig):
    original = rig.vendor._stored

    def stored(body, before):
        rec = original(body, before)
        rec["ProjNo"] = rec["ProjNo"].upper()
        return rec

    rig.vendor._stored = stored
    rig.vendor.store.clear()
    lower = "ppf26110009"
    original_route = rig.vendor._route

    def route(method, leaf, call):  # AutoCount stores the number upper-cased and matches either case
        if method == "POST":
            response = original_route(method, leaf, call)
            rig.vendor.store[lower.upper()] = rig.vendor.store.pop(lower)
            rig.vendor.dates[lower.upper()] = "20261121"
            return response
        if method == "GET" and leaf == "projectregbyprojno":
            rec = rig.vendor.store.get(call["query"]["ProjNo"].upper())
            return httpx.Response(200, json=[rec] if rec else [])
        return original_route(method, leaf, call)

    rig.vendor._route = route
    r = client.post(PREFIX, json=create_body(lower), headers=rig.hdr())
    assert r.status_code == 200 and r.json()["outcome"] == "done", r.text
    assert len(rig.vendor.writes()) == 1


def test_ac_71_60_another_keys_pending_create_holds_the_projno(client, rig):
    rig.vendor.next("POST", "NewProjectReg", "timeout")
    first = client.post(PREFIX, json=create_body(), headers=rig.hdr(idem="key-a"))
    assert first.status_code == 202, first.text
    second = client.post(PREFIX, json=create_body(), headers=rig.hdr(idem="key-b"))
    assert second.status_code == 409 and code(second) == "DOC_BUSY", second.text
    assert len(rig.vendor.writes()) == 1  # never a second create while the first is unknown


def test_ac_71_61_the_audit_row_survives_an_internal_error(client, rig, db, monkeypatch):
    from modules.autocount.write_back import project_registration as pr

    def boom(*a, **kw):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(pr.ProjectRegistrationService, "_find", staticmethod(boom))
    r = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert r.json()["errorCode"] == "INTERNAL_ERROR" and r.json()["actionId"]
    db.expire_all()
    row = db.query(AcWriteAction).filter(AcWriteAction.id == r.json()["actionId"]).one()
    assert row.error_code == "INTERNAL_ERROR"


def test_ac_71_62_no_write_past_the_overall_deadline(client, rig, monkeypatch):
    from modules.autocount.write_back import frame

    monkeypatch.setattr(frame, "ACTION_DEADLINE_SECONDS", -1.0)
    r = client.post(PREFIX, json=create_body(), headers=rig.hdr())
    assert r.status_code == 409 and code(r) == "DEADLINE_EXCEEDED", r.text
    assert rig.vendor.writes() == []


def test_ac_71_63_strict_dates(client, rig):
    r = client.get(f"{PREFIX}?companyCode=SRT&date=20261121", headers=rig.hdr(idem=None))
    assert r.status_code == 422 and code(r) == "INVALID_REQUEST"
    r = client.post(PREFIX, json=create_body(registration=reg(date="2026-11-21Tgarbage")), headers=rig.hdr())
    assert r.status_code == 422 and code(r) == "INVALID_REQUEST"
    r = client.post(PREFIX, json=create_body(registration=reg(date="2026-11-21T00:00:00")), headers=rig.hdr())
    assert r.status_code == 200, r.text
    assert rig.vendor.calls == [] or rig.vendor.writes()[0]["body"]["Date"] == "2026-11-21T00:00:00"


def test_ac_71_64_switch_off_wins_over_a_bad_body(client, rig_off):
    r = client.post(PREFIX, json={"companyCode": "SRT", "registration": {"nope": 1}}, headers=rig_off.hdr())
    assert r.status_code == 409 and code(r) == "VENDOR_UNSUPPORTED", r.text


def test_ac_71_65_a_keyless_pending_edit_is_simply_sent_again(client, rig):
    rig.vendor.seed(PROJ)
    rig.vendor.next("PUT", "EditProjectRegbyProjNo", "timeout")
    first = client.patch(f"{PREFIX}/{PROJ}", json=edit_body(), headers=rig.hdr(idem=None))
    assert first.status_code == 202, first.text
    again = client.patch(f"{PREFIX}/{PROJ}", json=edit_body(), headers=rig.hdr(idem=None))
    assert again.status_code == 200 and again.json()["outcome"] == "done", again.text


def test_ac_71_66_a_pending_create_that_landed_does_not_block_an_edit(client, rig):
    rig.vendor.next("POST", "NewProjectReg", "apply_then_timeout")
    original = rig.vendor._route
    state = {"posted": False, "failed": False}

    def route(method, leaf, call):
        if method == "POST":
            state["posted"] = True
        if method == "GET" and state["posted"] and not state["failed"]:
            state["failed"] = True
            return httpx.Response(500, text="down")
        return original(method, leaf, call)

    rig.vendor._route = route
    assert client.post(PREFIX, json=create_body(), headers=rig.hdr()).status_code == 202
    e = client.patch(f"{PREFIX}/{PROJ}", json=edit_body(), headers=rig.hdr(idem="edit-1"))
    assert e.status_code == 200 and e.json()["outcome"] == "done", e.text
