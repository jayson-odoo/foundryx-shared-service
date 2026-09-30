"""Sprint-5/16 - the public pull gateway's `delivery_orders` snapshot: the
build route, header and rows routes, and the operator routes
(AC-16-01..13, AC-16-40..44). Contract of record:
`documentation/plans/sprint-5/16-autocount-do-pull-snapshot-contract.md`.

RED before the coder: `delivery_orders` is not in
`ENTITY_WIRE_TO_INTERNAL`, so every DO build is a 422 `UNKNOWN_ENTITY`.

ASSUMED NAMES the coder must conform to:

* Wire: entity `delivery_orders`; build body keys `fromDay`, `toDay`, `docNo`;
  the 202 echoes `fromDay`, `toDay`, `docNo` (null when absent); the header
  adds `fromDay`, `toDay`, `docNo`, `book` on every status and `daysRead`,
  `fetchedCount`, `lineCount` on ready; `sourcePageSize` is null; new code
  409 `BUILD_IN_FLIGHT`.
* `modules.autocount.services.pull_gateway_service.ENTITY_WIRE_TO_INTERNAL
  ["delivery_orders"] == "delivery_orders"` (internal key
  `modules.autocount.models.DOC_FEED_DELIVERY_ORDERS`).
* Gate = a `delivery_orders` `ac_doc_feed` row with a connection, looked up
  WITH the tenant; feed `mode` never gates; `ac_entity_config` not consulted.
* Under this suite's eager jobs the build runs INLINE inside the POST, so
  after a 202 a GET of the header already shows the terminal state. A build
  is held `building` by making `JobService.enqueue` a no-op (`defer_jobs`).
* Vendor stubbing: `s16_do_pull_helpers.VendorStub` (only the
  `/deliveryorderbydocdate` door is routed).

Kill tests:
* AC-16-10: remove the scope-equality check in `PullService.request_build`
  (re-attach to ANY building snapshot) and `test_ac_16_10_*` must fail (the
  different-scope POST would answer 202 with the in-flight id, not 409).
* AC-16-11: key the cooldown on (company, entity) only and the
  "different scope within 60 s is allowed" half must fail.
* AC-16-07 tenant test dies if the feed lookup is company-scoped only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import BackgroundJob
from modules.autocount.models import (
    AcEntityConfig,
    AcPullAudit,
    AcPullSnapshot,
)

from .s14_doc_feed_helpers import OTHER_TENANT_ID, auth_headers, autocount_connection, other_tenant
from .s16_do_pull_helpers import (  # noqa: F401 - s16_isolation is an autouse fixture
    ENTITY_DO,
    GATEWAY_PREFIX,
    VendorStub,
    add_feed,
    build_env,
    day_ago,
    defer_jobs,
    do_rec,
    fixture_records,
    get_header,
    get_rows,
    iso,
    issue_key,
    make_company,
    post_build,
    s16_isolation,
    stored_rows,
    stored_snapshot,
    today_myt,
)

NO_SCOPE_KEY_SET = {"snapshotId", "status", "entity", "companyCode", "fromDay", "toDay", "docNo"}
DO_ONLY_HEADER_KEYS = ("fromDay", "toDay", "docNo", "book", "daysRead", "fetchedCount", "lineCount")


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _one_day_records(day):
    """day_fn answering the two fixture DOs (+ one keyless record) on `day`."""
    keyless = {"DocNo": "DO-2609/0199", "Details": []}
    recs = fixture_records()

    def day_fn(d):
        return [recs[1], recs[0], keyless] if d == day else []

    return day_fn


def _assert_flat_error(response, *, status, code, company_code="SRT", entity=ENTITY_DO):
    assert response.status_code == status, response.text
    body = response.json()
    assert "error" not in body
    assert body["code"] == code
    assert body["message"]
    assert body["companyCode"] == company_code
    assert body["entity"] == entity


# ── AC-16-01 / 02 / 03: happy path and scope defaults ────────────────────────


def test_ac_16_01_range_build_answers_202_with_the_documented_envelope(client, db, monkeypatch):
    env = build_env(db, monkeypatch)
    from_day, to_day = day_ago(2), day_ago(1)

    response = post_build(client, env.key, fromDay=iso(from_day), toDay=iso(to_day))

    assert response.status_code == 202, response.text
    body = response.json()
    assert set(body) == NO_SCOPE_KEY_SET
    assert body["snapshotId"]
    assert body["status"] in ("building", "ready")
    assert body["entity"] == "delivery_orders"
    assert body["companyCode"] == "SRT"
    assert body["fromDay"] == iso(from_day)
    assert body["toDay"] == iso(to_day)
    assert body["docNo"] is None
    snap = stored_snapshot(db, body["snapshotId"])
    assert snap.entity_type == "delivery_orders"
    assert snap.requested_via == "gateway"
    assert snap.company_code == env.company.sorento_company_code == "SRT"
    assert snap.company_id == env.company.id
    assert snap.tenant_id == DEFAULT_TENANT_ID


def test_ac_16_02_from_day_alone_defaults_to_day_to_from_day(client, db, monkeypatch):
    env = build_env(db, monkeypatch)
    day = day_ago(3)

    response = post_build(client, env.key, fromDay=iso(day))

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["fromDay"] == iso(day)
    assert body["toDay"] == iso(day)
    assert body["docNo"] is None
    header = get_header(client, env.key, body["snapshotId"]).json()
    assert header["fromDay"] == iso(day)
    assert header["toDay"] == iso(day)


def test_ac_16_03_doc_no_alone_defaults_the_range_to_the_31_myt_days_ending_today(
    client, db, monkeypatch,
):
    env = build_env(db, monkeypatch)

    response = post_build(client, env.key, docNo="DO-2609/0201")

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["toDay"] == iso(today_myt())
    assert body["fromDay"] == iso(day_ago(30))
    assert body["docNo"] == "DO-2609/0201"


# ── AC-16-04: scope validation (422 INVALID_REQUEST naming the field) ───────


@pytest.mark.parametrize(
    "scope_factory, fields",
    [
        pytest.param(lambda: {}, ("fromDay", "docNo"), id="neither-fromDay-nor-docNo"),
        pytest.param(lambda: {"toDay": iso(day_ago(1))}, ("toDay",), id="toDay-without-fromDay"),
        pytest.param(lambda: {"fromDay": "2026/09/29"}, ("fromDay",), id="fromDay-slashes"),
        pytest.param(lambda: {"fromDay": "29-09-2026"}, ("fromDay",), id="fromDay-dmy"),
        pytest.param(lambda: {"fromDay": "2026-13-40"}, ("fromDay",), id="fromDay-impossible-date"),
        pytest.param(lambda: {"fromDay": 20260929}, ("fromDay",), id="fromDay-not-a-string"),
        pytest.param(
            lambda: {"fromDay": iso(day_ago(2)), "toDay": "tomorrow"}, ("toDay",),
            id="toDay-not-a-date",
        ),
        pytest.param(
            lambda: {"fromDay": iso(day_ago(1)), "toDay": iso(day_ago(3))}, ("fromDay", "toDay"),
            id="fromDay-after-toDay",
        ),
        pytest.param(
            lambda: {"fromDay": iso(day_ago(31)), "toDay": iso(today_myt())}, ("fromDay", "toDay"),
            id="range-of-32-days",
        ),
        pytest.param(
            lambda: {"fromDay": iso(day_ago(1)), "toDay": iso(day_ago(-1))}, ("toDay",),
            id="toDay-after-myt-today",
        ),
        pytest.param(lambda: {"fromDay": "2022-12-31"}, ("fromDay",), id="fromDay-before-2023-01-01"),
        pytest.param(
            lambda: {"fromDay": iso(day_ago(1)), "docNo": 123}, ("docNo",), id="docNo-not-a-string",
        ),
        pytest.param(
            lambda: {"fromDay": iso(day_ago(1)), "docNo": "   "}, ("docNo",),
            id="docNo-empty-after-trim",
        ),
        pytest.param(lambda: {"docNo": "D" * 65}, ("docNo",), id="docNo-over-64-chars"),
    ],
)
def test_ac_16_04_bad_scope_is_a_flat_422_invalid_request_naming_the_field(
    client, db, monkeypatch, scope_factory, fields,
):
    env = build_env(db, monkeypatch)

    response = post_build(client, env.key, **scope_factory())

    _assert_flat_error(response, status=422, code="INVALID_REQUEST")
    message = response.json()["message"]
    assert any(field in message for field in fields), message
    db.expire_all()
    assert db.query(AcPullSnapshot).filter(AcPullSnapshot.company_id == env.company.id).count() == 0
    assert env.stub.requests == [], "a rejected scope must never reach the vendor"


def test_ac_16_04_boundaries_are_accepted_31_days_inclusive_and_the_2023_floor(
    client, db, monkeypatch,
):
    env = build_env(db, monkeypatch)

    thirty_one = post_build(
        client, env.key, fromDay=iso(day_ago(30)), toDay=iso(today_myt()),
    )
    assert thirty_one.status_code == 202, thirty_one.text
    assert thirty_one.json()["toDay"] == iso(today_myt())

    floor = post_build(client, env.key, fromDay="2023-01-01", toDay="2023-01-01")
    # the first build for this company is still within its cooldown only when
    # the scope is equal; a different scope is allowed (AC-16-11).
    assert floor.status_code == 202, floor.text
    assert floor.json()["fromDay"] == "2023-01-01"


# ── AC-16-05: scope keys on the other entities ───────────────────────────────


@pytest.mark.parametrize("entity", ["products", "stock_balances"])
@pytest.mark.parametrize(
    "scope",
    [
        pytest.param({"fromDay": "2026-09-01"}, id="fromDay"),
        pytest.param({"toDay": "2026-09-02"}, id="toDay"),
        pytest.param({"docNo": "DO-1"}, id="docNo"),
    ],
)
def test_ac_16_05_a_scope_key_on_a_non_do_entity_is_a_422_invalid_request(
    client, db, monkeypatch, entity, scope,
):
    env = build_env(db, monkeypatch)
    if entity == "products":
        # An ACTIVE pull task exists, so ignoring the key would 202 - the
        # 422 is the only right answer.
        db.add(
            AcEntityConfig(
                tenant_id=DEFAULT_TENANT_ID, company_id=env.company.id, entity_type="product",
                source_impl="autocount_http", etl_status="active", delivery_mode="pull",
                source_config={
                    "connectionId": env.conn.id, "path": "/itembypage", "keyFields": ["ItemCode"],
                    "watermarkField": None, "comparedFields": [], "distinctOf": None,
                    "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
                    "lookups": [],
                },
            )
        )
        db.commit()

    response = post_build(client, env.key, entity=entity, **scope)

    _assert_flat_error(response, status=422, code="INVALID_REQUEST", entity=entity)
    assert list(scope)[0] in response.json()["message"]
    db.expire_all()
    assert db.query(AcPullSnapshot).filter(AcPullSnapshot.company_id == env.company.id).count() == 0


def test_ac_16_05_control_products_without_scope_keys_behaves_exactly_as_before(
    client, db, monkeypatch,
):
    """GREEN both before and after the coder: products stays byte-identical
    (202, no scope keys echoed, still walks the paged `HttpApiSource`)."""
    import httpx
    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.client import HttpApiClient

    env = build_env(db, monkeypatch)
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=env.company.id, entity_type="product",
            source_impl="autocount_http", etl_status="active", delivery_mode="pull",
            source_config={
                "connectionId": env.conn.id, "path": "/itembypage", "keyFields": ["ItemCode"],
                "watermarkField": None, "comparedFields": [], "distinctOf": None,
                "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
                "lookups": [],
            },
        )
    )
    db.commit()
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(
            200, json={"TotalCount": 0, "Page": 1, "PageSize": 1000, "TotalPages": 1, "Data": []},
        )

    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub_transport),
    )

    response = post_build(client, env.key, entity="products")

    assert response.status_code == 202, response.text
    body = response.json()
    assert set(body) == {"snapshotId", "status", "entity", "companyCode"}
    assert body["entity"] == "products"
    assert any(path.endswith("/itembypage") for path in seen), seen
    assert env.stub.requests == [], "products must never touch the DO door"


# ── AC-16-06 ─────────────────────────────────────────────────────────────────


def test_ac_16_06_unknown_entity_message_lists_the_three_wire_entities(client, db, monkeypatch):
    env = build_env(db, monkeypatch)

    response = post_build(client, env.key, entity="widgets")

    _assert_flat_error(response, status=422, code="UNKNOWN_ENTITY", entity="widgets")
    assert response.json()["message"] == (
        "entity must be one of: delivery_orders, products, stock_balances."
    )


def test_ac_16_06_wire_entity_maps_to_the_internal_delivery_orders_key():
    from modules.autocount.models import DOC_FEED_DELIVERY_ORDERS
    from modules.autocount.services.pull_gateway_service import ENTITY_WIRE_TO_INTERNAL

    assert ENTITY_WIRE_TO_INTERNAL["delivery_orders"] == DOC_FEED_DELIVERY_ORDERS == "delivery_orders"


# ── AC-16-07 / 08: gating ────────────────────────────────────────────────────


def test_ac_16_07_no_delivery_orders_feed_row_is_pull_not_enabled(client, db, monkeypatch):
    env = build_env(db, monkeypatch, with_feed=False)

    response = post_build(client, env.key, fromDay=iso(day_ago(1)))

    _assert_flat_error(response, status=409, code="PULL_NOT_ENABLED")
    assert env.stub.requests == []


def test_ac_16_07_a_feed_row_without_a_connection_is_pull_not_enabled(client, db, monkeypatch):
    env = build_env(db, monkeypatch, with_feed=False)
    add_feed(db, env.company, None)

    response = post_build(client, env.key, fromDay=iso(day_ago(1)))

    _assert_flat_error(response, status=409, code="PULL_NOT_ENABLED")


def test_ac_16_07_only_a_goods_receive_notes_feed_row_does_not_open_the_gate(
    client, db, monkeypatch,
):
    env = build_env(db, monkeypatch, with_feed=False)
    add_feed(db, env.company, env.conn, feed="goods_receive_notes")

    response = post_build(client, env.key, fromDay=iso(day_ago(1)))

    _assert_flat_error(response, status=409, code="PULL_NOT_ENABLED")


def test_ac_16_07_a_feed_row_of_another_tenant_for_this_company_id_does_not_open_the_gate(
    client, db, monkeypatch,
):
    """Tenant-scope: the feed lookup is resolved WITH the key's tenant."""
    env = build_env(db, monkeypatch, with_feed=False)
    other = other_tenant(db)
    other_conn = autocount_connection(db, other)
    db.commit()
    add_feed(db, env.company, other_conn, tenant_id=other)

    response = post_build(client, env.key, fromDay=iso(day_ago(1)))

    _assert_flat_error(response, status=409, code="PULL_NOT_ENABLED")


@pytest.mark.parametrize("mode", ["off", "dry_run", "push"])
def test_ac_16_07_the_feed_mode_never_gates_the_build_and_push_active_is_never_raised(
    client, db, monkeypatch, mode,
):
    env = build_env(db, monkeypatch, mode=mode)

    response = post_build(client, env.key, fromDay=iso(day_ago(1)))

    assert response.status_code == 202, response.text
    assert response.json()["entity"] == "delivery_orders"


def test_ac_16_08_entity_config_is_not_consulted_for_delivery_orders(client, db, monkeypatch):
    env = build_env(db, monkeypatch)
    assert db.query(AcEntityConfig).filter(AcEntityConfig.company_id == env.company.id).count() == 0

    response = post_build(client, env.key, fromDay=iso(day_ago(1)))

    assert response.status_code == 202, response.text
    db.expire_all()
    assert db.query(AcEntityConfig).filter(AcEntityConfig.company_id == env.company.id).count() == 0


# ── AC-16-09 / 10 / 11: re-attach, BUILD_IN_FLIGHT, cooldown ────────────────


def test_ac_16_09_same_normalised_scope_reattaches_to_the_building_snapshot(
    client, db, monkeypatch,
):
    env = build_env(db, monkeypatch)
    defer_jobs(monkeypatch)
    day = iso(day_ago(2))

    first = post_build(client, env.key, fromDay=day)
    # `toDay` defaults to `fromDay`, so this is the SAME normalised scope.
    second = post_build(client, env.key, fromDay=day, toDay=day)

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert first.json()["status"] == "building"
    assert second.json()["snapshotId"] == first.json()["snapshotId"]
    db.expire_all()
    assert db.query(AcPullSnapshot).filter(AcPullSnapshot.company_id == env.company.id).count() == 1
    assert (
        db.query(BackgroundJob).filter(BackgroundJob.type == "autocount_pull_snapshot").count() == 1
    ), "a re-attach must not enqueue a second job"
    assert env.stub.requests == []


@pytest.mark.parametrize(
    "other_scope",
    [
        pytest.param({"fromDay": iso(day_ago(2)), "toDay": iso(day_ago(1))}, id="different-toDay"),
        pytest.param({"fromDay": iso(day_ago(3))}, id="different-fromDay"),
        pytest.param({"fromDay": iso(day_ago(2)), "docNo": "DO-2609/0201"}, id="added-docNo"),
        pytest.param({"docNo": "DO-2609/0201"}, id="docNo-only-default-range"),
    ],
)
def test_ac_16_10_a_different_scope_while_building_is_409_build_in_flight(
    client, db, monkeypatch, other_scope,
):
    env = build_env(db, monkeypatch)
    defer_jobs(monkeypatch)
    first = post_build(client, env.key, fromDay=iso(day_ago(2)))
    assert first.status_code == 202, first.text
    in_flight_id = first.json()["snapshotId"]

    second = post_build(client, env.key, **other_scope)

    _assert_flat_error(second, status=409, code="BUILD_IN_FLIGHT")
    assert "snapshotId" not in second.json(), "the in-flight id is deliberately not returned"
    db.expire_all()
    snaps = db.query(AcPullSnapshot).filter(AcPullSnapshot.company_id == env.company.id).all()
    assert [s.id for s in snaps] == [in_flight_id]
    assert snaps[0].status == "building"
    assert snaps[0].error_code is None
    assert (
        db.query(BackgroundJob).filter(BackgroundJob.type == "autocount_pull_snapshot").count() == 1
    ), "the refused request must not enqueue a job"
    assert env.stub.requests == []


def test_ac_16_11_same_scope_within_60s_is_429_but_a_different_scope_is_allowed(
    client, db, monkeypatch,
):
    env = build_env(db, monkeypatch)
    scope_a = {"fromDay": iso(day_ago(2)), "toDay": iso(day_ago(1))}
    first = post_build(client, env.key, **scope_a)
    assert first.status_code == 202, first.text
    assert get_header(client, env.key, first.json()["snapshotId"]).json()["status"] == "ready"

    same = post_build(client, env.key, **scope_a)
    _assert_flat_error(same, status=429, code="TOO_MANY_BUILDS")
    assert same.headers.get("Retry-After")

    different = post_build(client, env.key, fromDay=iso(day_ago(5)), toDay=iso(day_ago(4)))
    assert different.status_code == 202, different.text
    assert different.json()["snapshotId"] != first.json()["snapshotId"]


# ── AC-16-12: existing codes with delivery_orders echoed ────────────────────


def test_ac_16_12_401_invalid_api_key(client, db, monkeypatch):
    build_env(db, monkeypatch)
    response = post_build(client, "fxa_live_" + "z" * 43, fromDay=iso(day_ago(1)))
    _assert_flat_error(response, status=401, code="INVALID_API_KEY")


def test_ac_16_12_403_service_not_enabled(client, db, monkeypatch):
    from app.services.app_store_service import AppStoreService

    env = build_env(db, monkeypatch)
    AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "autocount")
    response = post_build(client, env.key, fromDay=iso(day_ago(1)))
    _assert_flat_error(response, status=403, code="SERVICE_NOT_ENABLED")


def test_ac_16_12_403_company_not_allowed(client, db, monkeypatch):
    env = build_env(db, monkeypatch)
    other_company, _ = make_company(db, code="MCH", database_name="MOCHA")
    key = issue_key(db, [other_company.id])
    response = post_build(client, key, fromDay=iso(day_ago(1)))
    _assert_flat_error(response, status=403, code="COMPANY_NOT_ALLOWED")
    assert env.stub.requests == []


def test_ac_16_12_404_unknown_company(client, db, monkeypatch):
    env = build_env(db, monkeypatch)
    response = post_build(client, env.key, company_code="XYZ", fromDay=iso(day_ago(1)))
    _assert_flat_error(response, status=404, code="UNKNOWN_COMPANY", company_code="XYZ")


def test_ac_16_12_409_ambiguous_company(client, db, monkeypatch):
    env = build_env(db, monkeypatch)
    twin, twin_conn = make_company(db, code="SRT", database_name="AED_TWIN")
    add_feed(db, twin, twin_conn)
    key = issue_key(db, [env.company.id, twin.id])
    response = post_build(client, key, fromDay=iso(day_ago(1)))
    _assert_flat_error(response, status=409, code="AMBIGUOUS_COMPANY")


def test_ac_16_12_company_code_is_trimmed_and_case_insensitive_for_delivery_orders(
    client, db, monkeypatch,
):
    env = build_env(db, monkeypatch)
    response = post_build(client, env.key, company_code=" srt ", fromDay=iso(day_ago(1)))
    assert response.status_code == 202, response.text


# ── AC-16-13: the build audit row ────────────────────────────────────────────


def test_ac_16_13_the_build_audit_row_carries_delivery_orders_and_the_ids(
    client, db, monkeypatch,
):
    env = build_env(db, monkeypatch)

    response = post_build(client, env.key, fromDay=iso(day_ago(1)))

    assert response.status_code == 202, response.text
    db.expire_all()
    rows = (
        db.query(AcPullAudit)
        .filter(AcPullAudit.tenant_id == DEFAULT_TENANT_ID, AcPullAudit.action == "build")
        .all()
    )
    assert len(rows) == 1
    audit = rows[0]
    assert audit.entity_type == "delivery_orders"
    assert audit.company_id == env.company.id
    assert audit.snapshot_id == response.json()["snapshotId"]
    assert audit.key_id
    assert audit.status_code == 202


# ── AC-16-40: header shapes ──────────────────────────────────────────────────


def test_ac_16_40_building_header_carries_the_scope_and_book_and_no_counts(
    client, db, monkeypatch,
):
    env = build_env(db, monkeypatch)
    defer_jobs(monkeypatch)
    built = post_build(client, env.key, fromDay=iso(day_ago(2)), toDay=iso(day_ago(1)), docNo="X-1")

    response = get_header(client, env.key, built.json()["snapshotId"])

    assert response.status_code == 200, response.text
    assert response.json() == {
        "snapshotId": built.json()["snapshotId"], "entity": "delivery_orders",
        "companyCode": "SRT", "status": "building",
        "fromDay": iso(day_ago(2)), "toDay": iso(day_ago(1)), "docNo": "X-1", "book": "db1",
    }


def test_ac_16_40_building_header_shows_progress_once_a_total_is_known(client, db, monkeypatch):
    env = build_env(db, monkeypatch)
    defer_jobs(monkeypatch)
    built = post_build(client, env.key, fromDay=iso(day_ago(3)), toDay=iso(day_ago(1)))
    snap = stored_snapshot(db, built.json()["snapshotId"])
    job = db.get(BackgroundJob, snap.job_id)
    job.progress_done = 1
    job.progress_total = 3
    job.cursor_json = {"stage": "source"}
    db.commit()

    body = get_header(client, env.key, snap.id).json()

    assert body["status"] == "building"
    assert body["progress"] == {"pagesDone": 1, "pagesTotal": 3, "stage": "source"}
    assert body["book"] == "db1"
    assert "recordCount" not in body


def test_ac_16_40_ready_header_has_the_section_3_shape(client, db, monkeypatch):
    day = day_ago(1)
    env = build_env(db, monkeypatch, day_fn=_one_day_records(day))
    built = post_build(client, env.key, fromDay=iso(day_ago(2)), toDay=iso(day))
    assert built.status_code == 202, built.text

    response = get_header(client, env.key, built.json()["snapshotId"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "snapshotId", "entity", "companyCode", "status", "fromDay", "toDay", "docNo", "book",
        "extractedAt", "expiresAt", "recordCount", "complete", "contentHash", "sourcePageSize",
        "daysRead", "fetchedCount", "lineCount", "excludedCount", "excludedRows",
    }
    assert body["snapshotId"] == built.json()["snapshotId"]
    assert body["entity"] == "delivery_orders"
    assert body["companyCode"] == "SRT"
    assert body["status"] == "ready"
    assert body["fromDay"] == iso(day_ago(2))
    assert body["toDay"] == iso(day)
    assert body["docNo"] is None
    assert body["book"] == "db1"
    assert body["recordCount"] == 2
    assert body["complete"] is True
    assert len(body["contentHash"]) == 64
    assert body["sourcePageSize"] is None
    assert body["daysRead"] == 2
    assert body["fetchedCount"] == 3
    assert body["lineCount"] == 3
    assert body["excludedCount"] == 1
    assert body["excludedRows"] == [
        {
            "source_ref": None, "code": "DO-2609/0199", "reason": "missing_doc_key",
            "message": "DocKey is missing or not an integer; the record cannot be identified.",
        }
    ]
    assert body["extractedAt"].endswith("Z") and body["expiresAt"].endswith("Z")


def test_ac_16_40_failed_header_carries_the_fixed_prose_scope_and_book(client, db, monkeypatch):
    from modules.autocount.services.pull_gateway_service import GATEWAY_FAILED_MESSAGES

    from .s14_doc_feed_helpers import JsonRoute

    env = build_env(db, monkeypatch, day_fn=lambda _d: JsonRoute({"message": "down"}, status_code=500))
    built = post_build(client, env.key, fromDay=iso(day_ago(1)))
    assert built.status_code == 202, built.text

    response = get_header(client, env.key, built.json()["snapshotId"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "snapshotId": built.json()["snapshotId"], "entity": "delivery_orders",
        "companyCode": "SRT", "status": "failed",
        "fromDay": iso(day_ago(1)), "toDay": iso(day_ago(1)), "docNo": None, "book": "db1",
        "error": {
            "code": "SOURCE_PAGE_FAILED",
            "message": GATEWAY_FAILED_MESSAGES["SOURCE_PAGE_FAILED"],
        },
    }
    assert "hapi.sorento" not in response.text, "no vendor URL may leak into a failed message"


# ── AC-16-41: products / stock headers untouched ─────────────────────────────


@pytest.mark.parametrize(
    "entity_type, wire", [("product", "products"), ("stock_balance", "stock_balances")],
)
def test_ac_16_41_products_and_stock_headers_carry_none_of_the_do_keys(
    client, db, monkeypatch, entity_type, wire,
):
    from modules.autocount.services.pull_service import SnapshotService

    env = build_env(db, monkeypatch)
    service = SnapshotService(db)
    now = datetime.now(timezone.utc)

    building = service.create_building(
        DEFAULT_TENANT_ID, env.company.id, entity_type,
        company_code="SRT", requested_via="gateway",
    )
    body = get_header(client, env.key, building.id).json()
    assert body["entity"] == wire and body["status"] == "building"
    for key in DO_ONLY_HEADER_KEYS:
        assert key not in body

    service.stamp_ready(
        DEFAULT_TENANT_ID, building, record_count=0, complete=True, content_hash="a" * 64,
        metadata={"excludedCount": 0, "excludedRows": []},
        extracted_at=now, expires_at=now + timedelta(hours=24),
    )
    body = get_header(client, env.key, building.id).json()
    assert body["status"] == "ready"
    for key in DO_ONLY_HEADER_KEYS:
        assert key not in body

    failed = service.create_building(
        DEFAULT_TENANT_ID, env.company.id, entity_type,
        company_code="SRT", requested_via="gateway",
    )
    service.stamp_failed(
        DEFAULT_TENANT_ID, failed, error="boom", error_code="SOURCE_PAGE_FAILED",
    )
    body = get_header(client, env.key, failed.id).json()
    assert body["status"] == "failed"
    for key in DO_ONLY_HEADER_KEYS:
        assert key not in body


# ── AC-16-42: rows ───────────────────────────────────────────────────────────


def test_ac_16_42_rows_page_the_raw_do_dicts_in_row_index_order(client, db, monkeypatch):
    day = day_ago(1)
    env = build_env(db, monkeypatch, day_fn=_one_day_records(day))
    built = post_build(client, env.key, fromDay=iso(day))
    snapshot_id = built.json()["snapshotId"]
    recs = fixture_records()

    full = get_rows(client, env.key, snapshot_id)
    assert full.status_code == 200, full.text
    body = full.json()
    assert body == {
        "snapshotId": snapshot_id, "page": 1, "pageSize": 1000, "totalPages": 1,
        "recordCount": 2, "rows": [recs[0], recs[1]],
    }

    page_one = get_rows(client, env.key, snapshot_id, page=1, pageSize=1).json()
    page_two = get_rows(client, env.key, snapshot_id, page=2, pageSize=1).json()
    assert page_one["rows"] == [recs[0]] and page_one["totalPages"] == 2
    assert page_two["rows"] == [recs[1]] and page_two["pageSize"] == 1

    clamped = get_rows(client, env.key, snapshot_id, pageSize=5000).json()
    assert clamped["pageSize"] == 1000

    past_the_end = get_rows(client, env.key, snapshot_id, page=99)
    assert past_the_end.status_code == 200, past_the_end.text
    assert past_the_end.json()["rows"] == []
    assert past_the_end.json()["recordCount"] == 2
    assert [r.row_index for r in stored_rows(db, snapshot_id)] == [0, 1]


# ── AC-16-43: scoping and expiry ─────────────────────────────────────────────


def _direct_ready_do_snapshot(db, company, *, tenant_id=DEFAULT_TENANT_ID, expires_at=None):
    from modules.autocount.services.pull_service import SnapshotService

    now = datetime.now(timezone.utc)
    service = SnapshotService(db)
    snap = service.create_building(
        tenant_id, company.id, "delivery_orders",
        company_code=company.sorento_company_code, requested_via="gateway",
    )
    return service.stamp_ready(
        tenant_id, snap, record_count=0, complete=True, content_hash="a" * 64,
        metadata={"excludedCount": 0, "excludedRows": []},
        extracted_at=now - timedelta(hours=2), expires_at=expires_at or now + timedelta(hours=22),
    )


def test_ac_16_43_a_do_snapshot_outside_the_keys_company_set_is_404_unknown_snapshot(
    client, db, monkeypatch,
):
    env = build_env(db, monkeypatch)
    other_company, _ = make_company(db, code="MCH", database_name="MOCHA")
    snap = _direct_ready_do_snapshot(db, other_company)

    response = get_header(client, env.key, snap.id)
    rows = get_rows(client, env.key, snap.id)

    assert response.status_code == rows.status_code == 404
    assert response.json()["code"] == rows.json()["code"] == "UNKNOWN_SNAPSHOT"


def test_ac_16_43_a_cross_tenant_do_snapshot_reads_identically_to_unknown(client, db, monkeypatch):
    env = build_env(db, monkeypatch)
    other = other_tenant(db)
    their_company, _ = make_company(db, tenant_id=other, code="MCH", database_name="THEIRS")
    theirs = _direct_ready_do_snapshot(db, their_company, tenant_id=other)

    unknown = get_header(client, env.key, "does-not-exist-at-all")
    cross = get_header(client, env.key, theirs.id)

    assert cross.status_code == unknown.status_code == 404
    assert cross.json() == unknown.json()


def test_ac_16_43_an_expired_do_snapshot_is_410_with_entity_delivery_orders(client, db, monkeypatch):
    env = build_env(db, monkeypatch)
    snap = _direct_ready_do_snapshot(
        db, env.company, expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    for response in (get_header(client, env.key, snap.id), get_rows(client, env.key, snap.id)):
        assert response.status_code == 410, response.text
        body = response.json()
        assert body["code"] == "SNAPSHOT_EXPIRED"
        assert body["entity"] == "delivery_orders"
        assert body["companyCode"] == "SRT"


# ── AC-16-44: operator routes ────────────────────────────────────────────────


def test_ac_16_44_operator_routes_list_and_show_a_do_snapshot(client, db, monkeypatch):
    day = day_ago(1)
    env = build_env(db, monkeypatch, day_fn=_one_day_records(day))
    built = post_build(client, env.key, fromDay=iso(day))
    snapshot_id = built.json()["snapshotId"]
    headers = auth_headers(client)

    listing = client.get(
        "/autocount/pull/snapshots",
        params={"companyId": env.company.id, "entityType": "delivery_orders"},
        headers=headers,
    )
    assert listing.status_code == 200, listing.text
    data = listing.json()
    assert data["total"] == 1
    assert data["data"][0]["id"] == snapshot_id
    assert data["data"][0]["entityType"] == "delivery_orders"
    assert data["data"][0]["status"] == "ready"
    assert data["data"][0]["recordCount"] == 2
    assert data["data"][0]["requestedVia"] == "gateway"

    show = client.get(f"/autocount/pull/snapshots/{snapshot_id}", headers=headers)
    assert show.status_code == 200, show.text
    assert show.json()["entityType"] == "delivery_orders"
    assert show.json()["excludedCount"] == 1

    rows = client.get(f"/autocount/pull/snapshots/{snapshot_id}/rows", headers=headers)
    assert rows.status_code == 200, rows.text
    assert rows.json()["rows"] == [fixture_records()[0], fixture_records()[1]]


def test_ac_16_44_the_operator_build_route_refuses_delivery_orders_with_422(
    client, db, monkeypatch,
):
    env = build_env(db, monkeypatch)
    headers = auth_headers(client)

    response = client.post(
        "/autocount/pull/snapshots",
        json={"companyId": env.company.id, "entityType": "delivery_orders"},
        headers=headers,
    )

    assert response.status_code == 422, response.text
    db.expire_all()
    assert db.query(AcPullSnapshot).filter(AcPullSnapshot.company_id == env.company.id).count() == 0
    assert env.stub.requests == []


# ── PR #103 round 1 ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["DO\x00-1", "DO\n1", "DO\x1f1", "DO\x7f1"])
def test_ac_16_04_a_docno_with_a_control_character_is_a_fixed_422_never_echoed(
    client, db, monkeypatch, bad,
):
    """SEC L1."""
    env = build_env(db, monkeypatch)

    response = post_build(client, env.key, docNo=bad)

    _assert_flat_error(response, status=422, code="INVALID_REQUEST")
    message = response.json()["message"]
    assert "docNo" in message and "control" in message
    assert "DO" not in message.replace("docNo", "")
    assert env.stub.requests == []


def _force_reattach_race(monkeypatch, winner_id):
    """Make the pre-check see nothing, so the INSERT loses to the winner and the
    IntegrityError re-attach path is the one under test."""
    from modules.autocount.repositories import PullSnapshotRepository

    real = PullSnapshotRepository.latest_for_triple
    state = {"calls": 0}

    def fake(self, *args, **kwargs):
        state["calls"] += 1
        return None if state["calls"] == 1 else real(self, *args, **kwargs)

    monkeypatch.setattr(PullSnapshotRepository, "latest_for_triple", fake)


def test_ac_16_10_integrity_race_with_a_different_scope_winner_is_409_build_in_flight(
    client, db, monkeypatch,
):
    """REV should-fix 1: kills deleting the winner scope check in the IntegrityError branch."""
    env = build_env(db, monkeypatch)
    defer_jobs(monkeypatch)
    first = post_build(client, env.key, fromDay=iso(day_ago(2)))
    assert first.status_code == 202, first.text
    _force_reattach_race(monkeypatch, first.json()["snapshotId"])

    second = post_build(client, env.key, fromDay=iso(day_ago(5)))

    _assert_flat_error(second, status=409, code="BUILD_IN_FLIGHT")


def test_ac_16_10_integrity_race_with_the_same_scope_winner_reattaches(
    client, db, monkeypatch,
):
    env = build_env(db, monkeypatch)
    defer_jobs(monkeypatch)
    first = post_build(client, env.key, fromDay=iso(day_ago(2)))
    assert first.status_code == 202, first.text
    _force_reattach_race(monkeypatch, first.json()["snapshotId"])

    second = post_build(client, env.key, fromDay=iso(day_ago(2)))

    assert second.status_code == 202, second.text
    assert second.json()["snapshotId"] == first.json()["snapshotId"]


def test_ac_16_10_scope_equality_compares_docno_trimmed_and_case_insensitively(
    client, db, monkeypatch,
):
    """REV nit 3: re-attach across casing; the echo keeps the caller's casing."""
    env = build_env(db, monkeypatch)
    defer_jobs(monkeypatch)
    first = post_build(client, env.key, docNo="DO-2609/0201")
    assert first.status_code == 202, first.text

    second = post_build(client, env.key, docNo="  do-2609/0201 ")

    assert second.status_code == 202, second.text
    assert second.json()["snapshotId"] == first.json()["snapshotId"]
    assert second.json()["docNo"] == "do-2609/0201"


def test_ac_16_07_a_feed_whose_connection_row_was_deleted_is_pull_not_enabled(
    client, db, monkeypatch,
):
    """REV nit 4: the gate requires the connection to resolve."""
    env = build_env(db, monkeypatch)
    db.delete(env.conn)
    db.commit()

    response = post_build(client, env.key, fromDay=iso(day_ago(1)))

    _assert_flat_error(response, status=409, code="PULL_NOT_ENABLED")
    assert env.stub.requests == []
