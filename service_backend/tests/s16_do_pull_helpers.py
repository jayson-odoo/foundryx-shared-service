"""Shared builders for the sprint-5/16 (AutoCount pull gateway `delivery_orders`
snapshot, BL-SS-286) red tests. Not a test file itself (no `test_` prefix).

`conftest.py` scopes its autouse sleep / DNS / live-network guards by FILENAME
(`test_(autocount|s10_|s11_|s13_|s14_)`), which does NOT match `test_s16_*`,
so the `s16_isolation` autouse fixture below re-provides all three; each s16
test file imports it (`from .s16_do_pull_helpers import s16_isolation`).

Vendor stubbing: the DO build resolves its vendor half through
`modules.autocount.doc_feed.runner` (`resolve_vendor`), which builds
`HttpApiClient` from ITS OWN import. `VendorStub.install` monkeypatches
`modules.autocount.doc_feed.runner.HttpApiClient` to a factory returning a
real `HttpApiClient` over an `httpx.MockTransport`. ONLY the
`/deliveryorderbydocdate` door is routed: any other path (the CRM contract
probe, `/itembypage`, `/deliveryorderbyLastModified`, ...) is recorded in
`stub.unrouted` and raises `AssertionError`.
"""
from __future__ import annotations

import copy
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.doc_feed.clock import MYT, yyyymmdd
from modules.autocount.models import AcCompany, AcDocFeed

from .s14_doc_feed_helpers import (
    BOOK,
    VENDOR_BASE_URL,
    JsonRoute,
    autocount_connection,
    load_fixture,
    sorento_connection,
)

GATEWAY_PREFIX = "/api/v1/autocount"
DO_DOOR = "/deliveryorderbydocdate"
GRN_DOOR = "/goodsreceivenotebydocdate"
ENTITY_DO = "delivery_orders"
ENTITY_GRN = "goods_receive_notes"
BASE_PATH_PREFIX = "/api/db1"

_PUBLIC_DNS_STUB_IP = "8.8.8.8"


# ── isolation (sleep / DNS / live network) ───────────────────────────────────


@pytest.fixture(autouse=True)
def s16_isolation(monkeypatch):
    """No real sleep (retry ladders), a stubbed resolver (the SSRF re-check on
    `hapi.sorento.cc.cd`), and the lane rule: no test may touch the network."""
    import socket

    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    def _stub_getaddrinfo(host, *_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_PUBLIC_DNS_STUB_IP, 0))]

    monkeypatch.setattr("socket.getaddrinfo", _stub_getaddrinfo)

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


# ── dates (MYT calendar days, the vendor's DocDate) ──────────────────────────


def today_myt() -> date:
    return datetime.now(timezone.utc).astimezone(MYT).date()


def day_ago(n: int) -> date:
    return today_myt() - timedelta(days=n)


def iso(d: date) -> str:
    return d.isoformat()


# ── vendor records ───────────────────────────────────────────────────────────


def fixture_records() -> List[Dict[str, Any]]:
    """The two raw DO records of `do-vendor-day.json` (55120 with 2 Details,
    55121 with 1)."""
    return load_fixture("do-vendor-day.json")


def do_rec(
    doc_key: Any, doc_no: Any, doc_date: str, last_modified: str, **extra: Any,
) -> Dict[str, Any]:
    """A full raw DO cloned from fixture record 0 with the identity fields
    replaced (2 Details, both re-keyed)."""
    rec = copy.deepcopy(fixture_records()[0])
    rec["DocKey"] = doc_key
    rec["DocNo"] = doc_no
    rec["DocDate"] = doc_date
    rec["LastModified"] = last_modified
    for detail in rec["Details"]:
        detail["DocKey"] = doc_key
    rec.update(extra)
    return rec


def tiny_rec(i: int, doc_date: str = "2026-09-28T00:00:00") -> Dict[str, Any]:
    return {
        "DocKey": i, "DocNo": f"DO-{i}", "DocDate": doc_date,
        "LastModified": "2026-09-28T10:00:00.000", "Details": [],
    }


# ── the vendor stub ──────────────────────────────────────────────────────────


class VendorStub:
    """Routes ONLY `/deliveryorderbydocdate`. `day_fn(day)` answers per
    requested `DocDate` day with a list (200 JSON), an `httpx.Response`, a
    `JsonRoute`, or an Exception instance (raised inside the transport)."""

    def __init__(
        self, day_fn: Optional[Callable[[date], Any]] = None, *, door: str = DO_DOOR,
    ) -> None:
        self.day_fn = day_fn or (lambda _day: [])
        self.door = door
        self.requests: List[httpx.Request] = []
        self.paths: List[str] = []
        self.days: List[date] = []
        self.unrouted: List[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        rel = path[len(BASE_PATH_PREFIX):] if path.startswith(BASE_PATH_PREFIX) else path
        self.requests.append(request)
        self.paths.append(rel)
        if rel != self.door:
            self.unrouted.append(rel)
            raise AssertionError(
                f"s16 vendor stub: only {self.door} is routed, got {request.method} {request.url}"
            )
        day = datetime.strptime(request.url.params["DocDate"], "%Y%m%d").date()
        self.days.append(day)
        answer = self.day_fn(day)
        if isinstance(answer, httpx.Response):
            return answer
        if isinstance(answer, JsonRoute):
            return httpx.Response(answer.status_code, json=answer.json_body, headers=answer.headers)
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(200, json=answer)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=self.transport())

    def install(self, monkeypatch) -> "VendorStub":
        import modules.autocount.doc_feed.runner as runner_module
        from modules.autocount.http_source.client import HttpApiClient as RealClient

        stub_client = self.client()
        monkeypatch.setattr(
            runner_module, "HttpApiClient",
            lambda base_url, **_kw: RealClient(base_url, transport=stub_client),
        )
        return self

    @property
    def yyyymmdd_days(self) -> List[str]:
        return [yyyymmdd(d) for d in self.days]


# ── env builders ─────────────────────────────────────────────────────────────


def make_company(
    db, *, tenant_id: str = DEFAULT_TENANT_ID, code: Optional[str] = "SRT",
    database_name: str = "AED_SORENTO", active: bool = True, wired_sink: bool = False,
    ac_connection=None,
):
    """One AcCompany with an autocount open-REST connection. NO entity config
    of any kind is seeded (AC-16-08). `wired_sink=True` also wires a Sorento
    consumer sink (used to prove a DO build never touches it)."""
    from modules.autocount.models import SINK_IMPL_SORENTO

    conn = ac_connection or autocount_connection(db, tenant_id)
    rec = AcCompany(
        tenant_id=tenant_id, connection_id=conn.id, database_name=database_name,
        company_name="Sorento", name="Sorento", is_active=active, sorento_company_code=code,
    )
    if wired_sink:
        sink_conn = sorento_connection(db, tenant_id)
        rec.sink_impl = SINK_IMPL_SORENTO
        rec.sink_connection_id = sink_conn.id
    db.add(rec)
    db.flush()
    db.commit()
    db.refresh(rec)
    return rec, conn


def add_feed(
    db, company, conn, *, tenant_id: Optional[str] = None, feed: str = ENTITY_DO,
    mode: str = "off", book: str = BOOK, **columns: Any,
) -> AcDocFeed:
    row = AcDocFeed(
        tenant_id=tenant_id or company.tenant_id, company_id=company.id, feed=feed,
        connection_id=conn.id if conn is not None else None, book=book, mode=mode, **columns,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def issue_key(db, company_ids: List[str], *, tenant_id: str = DEFAULT_TENANT_ID) -> str:
    from modules.autocount.services.pull_key_service import PullKeyService

    _key, plaintext = PullKeyService(db).issue(
        tenant_id, name="s16 do pull key", company_ids=company_ids,
    )
    return plaintext


def build_env(
    db, monkeypatch, *, day_fn: Optional[Callable[[date], Any]] = None,
    code: str = "SRT", mode: str = "off", with_feed: bool = True,
    wired_sink: bool = False, feed_columns: Optional[Dict[str, Any]] = None,
    database_name: str = "AED_SORENTO", feed: str = ENTITY_DO,
) -> SimpleNamespace:
    """company + connection + DO feed row + a key scoped to the company + the
    installed vendor stub."""
    company, conn = make_company(
        db, code=code, wired_sink=wired_sink, database_name=database_name,
    )
    feed_row = (
        add_feed(db, company, conn, feed=feed, mode=mode, **(feed_columns or {}))
        if with_feed else None
    )
    key = issue_key(db, [company.id])
    door = GRN_DOOR if feed == ENTITY_GRN else DO_DOOR
    stub = VendorStub(day_fn, door=door).install(monkeypatch)
    return SimpleNamespace(company=company, conn=conn, feed=feed_row, key=key, stub=stub)


# ── HTTP helpers ─────────────────────────────────────────────────────────────


def post_build(
    client, key: str, *, company_code: str = "SRT", entity: str = ENTITY_DO, **scope: Any,
):
    body: Dict[str, Any] = {"companyCode": company_code, "entity": entity}
    body.update(scope)
    return client.post(f"{GATEWAY_PREFIX}/snapshots", json=body, headers={"X-API-Key": key})


def get_header(client, key: str, snapshot_id: str):
    return client.get(f"{GATEWAY_PREFIX}/snapshots/{snapshot_id}", headers={"X-API-Key": key})


def get_rows(client, key: str, snapshot_id: str, **params: Any):
    return client.get(
        f"{GATEWAY_PREFIX}/snapshots/{snapshot_id}/rows", params=params,
        headers={"X-API-Key": key},
    )


def stored_rows(db, snapshot_id: str) -> list:
    from modules.autocount.models import AcPullSnapshotRow

    db.expire_all()
    return (
        db.query(AcPullSnapshotRow)
        .filter(AcPullSnapshotRow.snapshot_id == snapshot_id)
        .order_by(AcPullSnapshotRow.row_index)
        .all()
    )


def stored_snapshot(db, snapshot_id: str):
    from modules.autocount.models import AcPullSnapshot

    db.expire_all()
    return db.get(AcPullSnapshot, snapshot_id)


def defer_jobs(monkeypatch) -> None:
    """Make `JobService.enqueue` a no-op: the snapshot stays `building` (the
    job row exists, is never run) - the only way to hold a build in flight
    under this suite's eager job execution."""
    from app.jobs.service import JobService

    monkeypatch.setattr(JobService, "enqueue", lambda self, job_id: None)
