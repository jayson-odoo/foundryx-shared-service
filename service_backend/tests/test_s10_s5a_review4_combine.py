"""Sprint-5/10 S5a review round 4 - closes the confirm-review findings on
the combine engine (`http_source/combine.py`, `services/etl_service.py`,
`sync.py`, `schemas.py`).

BLOCKERS (already closed by rewriting/fixing the round-3 tests directly -
see `test_s10_s5a_review3_row_hash.py`):

* BL-1 - `ENTITY_STOCK_BALANCE` does not exist on this branch yet (S5b is
  RED); the row-hash test's "push vs pull" point is now pinned across two
  entities that DO exist (product, warehouse) instead.
* BL-2 - the "explicit compared field naming a measure alias" save-time
  test used to be vacuous (never-previewed task, `existing_result_columns
  is None`); now stamps a genuinely previewed `result_columns` before the
  save under test.

This file covers the SHOULD-FIXes and the cheap NITs:

* SF-1 - `preview_http` 422s (never 500s) a RUNTIME `TransformError` from a
  numeric measure, keyed to `combine.measures[i].source`.
* SF-2 - `validate_combine(..., sample=...)` 422s a `sum`/`min`/`max`
  measure whose SAMPLE values are non-numeric with no computed cast.
* SF-3 - `CombineDropError`'s own message now names the rule; BOTH sync.py
  runtime sites (the push run, the pull build) fail with a NAMED
  `COMBINE_RULE_FAILED` code instead of falling into the generic
  `SOURCE_PAGE_FAILED`/`Fetch failed: ...` catch-all.
* SF-4 - `EtlTaskView`/`EtlTaskResponse` carry an ADDITIVE
  `combineOutputColumns` (the combine step's own post-group schema),
  alongside `resultColumns`, never replacing it.
* NIT (ii) - a require rule after an earlier FALSY/raising one is never
  sample-type-checked against a row that earlier rule would already have
  excluded at runtime.
* NIT (iii) - a malformed/invalid `combine` never also demands a manual
  `keyFields` pick (the operator meant combine to derive the keys).
* NIT (iv) - an omitted optional `combine` list key (`"round"` not sent at
  all) normalises the same as an explicit empty one (`"round": []`) for
  the S3 active-task demote comparison.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT, ENTITY_WAREHOUSE
from modules.autocount.http_source.combine import (
    CombineDropError,
    CombineMeasureError,
    apply_combine,
    validate_combine,
)
from modules.autocount.models import ETL_STATUS_ACTIVE, ETL_STATUS_DRAFT, AcCompany, AcEntityConfig
from modules.autocount.services.etl_service import EtlService, EtlValidationError

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


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


def _company(db, connection_id: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name="MOCHA",
        company_name="Mocha", name="Mocha", is_active=True, sorento_company_code="MOCHA",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _raw(**overrides: Any) -> Dict[str, Any]:
    raw: Dict[str, Any] = {
        "sourceImpl": "autocount_http",
        "connectionId": None,
        "path": "/warehousebypage",
        "keyFields": ["Code"],
        "watermarkField": None,
        "comparedFields": [],
        "distinctOf": None,
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileHours": None,
        "reconcileAt": "02:00",
    }
    raw.update(overrides)
    return raw


def _combine_for_group(group_by=("Code",)) -> Dict[str, Any]:
    return {
        "computed": [], "require": [], "measure": group_by[0], "groupBy": list(group_by),
        "measures": [{"source": group_by[0], "op": "count", "alias": "n"}],
        "carry": [], "round": [], "drop": [],
    }


# ── SF-1: preview_http 422s (never 500s) a RUNTIME numeric-measure fault ────


@pytest.fixture
def client_headers(client):
    response = client.post(
        "/auth/login", json={"email": "demo@example.com", "password": "demo1234"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_preview_http_422s_a_runtime_blank_measure_source_instead_of_500ing(
    client, client_headers, db
):
    """A blank/absent source on a `sum` measure is explicitly NOT sample-
    checked (SF-2's own "None/blank = skip" rule - blank is not itself
    non-numeric, it may be a genuine per-row miss) but still raises a
    named `TransformError` at RUNTIME (`_coerce_measure_number`'s own
    "is required for a numeric measure but is blank" rule) - exactly the
    gap SF-1 closes: never a bare 500 for a preview."""
    import httpx as httpx_module
    from app.main import app
    from modules.autocount.http_client import get_http_transport

    conn = _open_connection(db)
    rows = [{"g": "A", "n": "10"}, {"g": "B"}]  # row 2 carries NO "n" key at all

    def handler(request: httpx_module.Request) -> httpx_module.Response:
        return httpx_module.Response(200, json={
            "TotalCount": len(rows), "Page": 1, "PageSize": 50, "TotalPages": 1, "Data": rows,
        })

    combine = {
        "computed": [], "require": [], "measure": "n", "groupBy": ["g"],
        "measures": [{"source": "n", "op": "sum", "alias": "total"}],
        "carry": [], "round": [], "drop": [],
    }
    app.dependency_overrides[get_http_transport] = lambda: httpx_module.Client(
        transport=httpx_module.MockTransport(handler)
    )
    try:
        response = client.post(
            "/autocount/http/preview",
            json={"connectionId": conn.id, "path": "/itembypage", "combine": combine},
            headers=client_headers,
        )
    finally:
        app.dependency_overrides.pop(get_http_transport, None)

    # sprint-5/11 (AC-11-21/22/25) - a runtime measure error is discovered
    # only AFTER the network fetch (over the sampled rows), so it is now a
    # FAILED job (never a synchronous 422 - the walk itself moved
    # off-request), carrying the SAME per-field message on `fieldErrors`.
    assert response.status_code == 202, response.text
    poll = client.get(f"/autocount/previews/{response.json()['jobId']}", headers=client_headers)
    assert poll.status_code == 200, poll.text
    body = poll.json()
    assert body["status"] == "failed", body
    field_errors = body["fieldErrors"]
    assert "combine.measures[0].source" in field_errors, field_errors


# ── SF-2: the SAMPLE-based numeric-op check ──────────────────────────────


def test_validate_combine_422s_a_sum_measure_over_a_text_sample_column():
    combine = {
        "computed": [], "require": [], "measure": "qty", "groupBy": ["g"],
        "measures": [{"source": "qty", "op": "sum", "alias": "total"}],
        "carry": [], "round": [], "drop": [],
    }
    sample = [{"g": "A", "qty": "abc"}]
    errors = validate_combine(combine, ["g", "qty"], sample=sample)
    assert "combine.measures[0].source" in errors, errors


def test_validate_combine_accepts_a_sum_measure_over_numeric_sample_strings():
    combine = {
        "computed": [], "require": [], "measure": "qty", "groupBy": ["g"],
        "measures": [{"source": "qty", "op": "sum", "alias": "total"}],
        "carry": [], "round": [], "drop": [],
    }
    sample = [{"g": "A", "qty": "10.50"}, {"g": "B", "qty": 3}]
    errors = validate_combine(combine, ["g", "qty"], sample=sample)
    assert errors == {}, errors


def test_validate_combine_accepts_a_computed_number_cast_measure_source():
    combine = {
        "computed": [{"alias": "qty_num", "formula": "number(qty_text)"}],
        "require": [], "measure": "qty_num", "groupBy": ["g"],
        "measures": [{"source": "qty_num", "op": "sum", "alias": "total"}],
        "carry": [], "round": [], "drop": [],
    }
    sample = [{"g": "A", "qty_text": "10.5"}]
    errors = validate_combine(combine, ["g", "qty_text"], sample=sample)
    assert errors == {}, errors


def test_validate_combine_skips_a_blank_measure_value_in_the_sample_check():
    """Blank/absent is NOT itself a type-inference signal (mirrors
    `_sample_boolean_errors`'s own per-row skip) - left to surface at
    RUNTIME under its own named fault (SF-1's own test above)."""
    combine = {
        "computed": [], "require": [], "measure": "qty", "groupBy": ["g"],
        "measures": [{"source": "qty", "op": "sum", "alias": "total"}],
        "carry": [], "round": [], "drop": [],
    }
    sample = [{"g": "A"}, {"g": "B", "qty": ""}]
    errors = validate_combine(combine, ["g", "qty"], sample=sample)
    assert errors == {}, errors


def test_validate_combine_numeric_sample_check_is_independent_of_the_boolean_one():
    """Both SAMPLE-based checks (require/drop boolean-type, SF-2's numeric
    one) run in the SAME pass and neither masks the other - different
    keys, so both surface together."""
    combine = {
        "computed": [],
        "require": [{"name": "r", "formula": "concat(g, \"x\")", "reason": "not_boolean"}],
        "measure": "qty", "groupBy": ["g"],
        "measures": [{"source": "qty", "op": "sum", "alias": "total"}],
        "carry": [], "round": [], "drop": [],
    }
    sample = [{"g": "A", "qty": "abc"}]
    errors = validate_combine(combine, ["g", "qty"], sample=sample)
    assert "combine.require[0].formula" in errors, errors
    assert "combine.measures[0].source" in errors, errors


# ── SF-3: CombineDropError names the rule; both sync.py sites use a NAMED
# COMBINE_RULE_FAILED code ───────────────────────────────────────────────


def test_combine_drop_error_message_names_the_rule():
    rows = [{"g": "A", "d": "x"}]
    combine = {
        "computed": [], "require": [], "measure": "g", "groupBy": ["g"],
        "measures": [{"source": "d", "op": "first", "alias": "d_first"}],
        "carry": [], "round": [],
        "drop": [{"name": "bad", "formula": 'concat(d_first, "x")'}],
    }
    with pytest.raises(CombineDropError) as exc_info:
        apply_combine(rows, combine)
    assert "Drop rule 'bad'" in str(exc_info.value), str(exc_info.value)
    assert exc_info.value.index == 0
    assert exc_info.value.rule_name == "bad"


def test_combine_measure_error_carries_its_index_and_source():
    rows = [{"g": "A"}]  # "n" is entirely absent
    combine = {
        "computed": [], "require": [], "measure": "n", "groupBy": ["g"],
        "measures": [{"source": "n", "op": "sum", "alias": "total"}],
        "carry": [], "round": [], "drop": [],
    }
    with pytest.raises(CombineMeasureError) as exc_info:
        apply_combine(rows, combine)
    assert exc_info.value.index == 0
    assert exc_info.value.source_name == "n"


_BAD_DROP_COMBINE: Dict[str, Any] = {
    "computed": [], "require": [], "measure": "ItemCode", "groupBy": ["ItemCode"],
    "measures": [{"source": "ItemCode", "op": "first", "alias": "code_first"}],
    "carry": [], "round": [],
    "drop": [{"name": "bad", "formula": 'concat(code_first, "x")'}],
}


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    """Lane rule: no test in this file may touch the network. See
    ``test_s10_s3_snapshot_build_job.py``'s copy of this fixture for the
    full rationale (coordinator finding 2026-09-20)."""
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


def test_a_combine_drop_rule_that_raises_fails_the_push_run_with_a_named_code(db, monkeypatch):
    """End-to-end through the REAL push run handler (mirrors
    ``test_s10_s3_delivery_mode.py``'s own push-run rig), a real
    ``apply_combine`` call raising `CombineDropError` mid-run."""
    import modules.autocount.http_source.source as http_source_module
    from app.jobs.service import JobService
    from modules.autocount.http_source.client import HttpApiClient
    from modules.autocount.repositories import EntityConfigRepository
    from modules.autocount.sync import AUTOCOUNT_SYNC, run_autocount_sync

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1,
                "Data": [{"ItemCode": "A1", "Description": "Item A1"}],
            },
        )

    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub_transport),
    )

    conn = _open_connection(db)
    company = _company(db, conn.id)
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", etl_status=ETL_STATUS_ACTIVE, enabled=True,
        source_config={
            "connectionId": conn.id, "path": "/itembypage",
            "keyFields": ["ItemCode"], "watermarkField": None, "comparedFields": [],
            "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
            "reconcileAt": "02:00", "lookups": [], "combine": _BAD_DROP_COMBINE,
        },
    )
    db.add(config)
    db.commit()

    job = JobService(db).create(
        type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company.id, "entityType": ENTITY_PRODUCT, "mode": "manual"},
    )
    run_autocount_sync(db, job)

    updated = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert updated.last_run_error_code == "COMBINE_RULE_FAILED", updated.last_run_error_code
    assert "Drop rule 'bad'" in (updated.last_run_error or ""), updated.last_run_error


def _fake_source_raising_combine_drop():
    class _FakeSource:
        entity_type = ENTITY_PRODUCT

        def fetch_changes(self, since):
            raise CombineDropError(0, "bad", "Expected a true/false value, got text.")

        def close(self):
            pass

    def factory(ctx, **kwargs):
        return _FakeSource()

    return factory


def test_a_combine_drop_rule_that_raises_fails_the_pull_build_with_a_named_code(db, monkeypatch):
    """Driven at the source-FACTORY seam (mirrors
    ``test_s10_s3_pull_build_error_codes.py`` exactly), isolating
    ``_run_pull_snapshot``'s own except-clause wiring from the reducer's
    internals (already covered by the push-run test above and
    ``test_combine_drop_error_message_names_the_rule``)."""
    import modules.autocount.sync as sync_module
    from modules.autocount.services.pull_service import PullService

    conn = _open_connection(db)
    company = _company(db, conn.id)
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", etl_status=ETL_STATUS_ACTIVE, delivery_mode="pull",
        enabled=True,
        source_config={
            "connectionId": conn.id, "path": "/itembypage",
            "keyFields": ["ItemCode"], "watermarkField": None, "comparedFields": [],
            "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
            "reconcileAt": "02:00", "lookups": [],
        },
        last_preview_at=NOW, result_columns=["ItemCode", "Description"],
    )
    db.add(config)
    db.commit()

    monkeypatch.setattr(
        sync_module, "source_factory", lambda impl: _fake_source_raising_combine_drop()
    )
    snapshot = PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, requested_via="operator", now=NOW,
    )
    db.refresh(snapshot)

    assert snapshot.status == "failed"
    assert snapshot.error_code == "COMBINE_RULE_FAILED", snapshot.error_code
    assert "Drop rule 'bad'" in (snapshot.error or ""), snapshot.error


# ── SF-4: EtlTaskView/EtlTaskResponse carry an ADDITIVE combineOutputColumns ─


def test_task_view_carries_the_combine_output_schema_for_a_combine_carrying_task(db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    raw = _raw(connectionId=conn.id, keyFields=[], combine=_combine_for_group())
    view = EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, raw)
    assert view.combine_output_columns == ["Code", "n"], view.combine_output_columns
    # `resultColumns` (the pre-combine set) is UNCHANGED alongside it.
    assert "n" not in view.result_columns, view.result_columns


def test_task_view_combine_output_columns_is_empty_with_no_combine_step(db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    raw = _raw(connectionId=conn.id, keyFields=["Code"])
    view = EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, raw)
    assert view.combine_output_columns == [], view.combine_output_columns


# ── NIT (ii): a require rule after an excluding one is never sample-type-
# checked against a row that rule would already have thrown out ─────────


_SHORT_CIRCUIT_COMBINE: Dict[str, Any] = {
    "computed": [],
    "require": [
        {"name": "r0", "formula": "kind == 'good'", "reason": "not_good"},
        # `note` is a plain string - genuinely non-boolean whenever it IS
        # evaluated, so this is the "type" signal under test.
        {"name": "r1", "formula": "note", "reason": "bad_type"},
    ],
    "measure": "qty", "groupBy": ["g"],
    "measures": [{"source": "qty", "op": "sum", "alias": "total"}],
    "carry": [], "round": [], "drop": [],
}


def test_a_later_require_rule_is_not_type_checked_against_a_row_an_earlier_rule_excludes():
    sample = [{"g": "A", "kind": "bad", "note": "hello", "qty": 1}]
    errors = validate_combine(
        _SHORT_CIRCUIT_COMBINE, ["g", "kind", "note", "qty"], sample=sample
    )
    assert "combine.require[1].formula" not in errors, errors


def test_a_later_require_rule_is_still_type_checked_against_a_row_that_survives_earlier_ones():
    """Control for the test above - proves the short-circuit is not just a
    blanket suppression of `require[1]`'s own check."""
    sample = [{"g": "A", "kind": "good", "note": "hello", "qty": 1}]
    errors = validate_combine(
        _SHORT_CIRCUIT_COMBINE, ["g", "kind", "note", "qty"], sample=sample
    )
    assert "combine.require[1].formula" in errors, errors


# ── NIT (iii): a malformed combine never also demands a manual keyFields
# pick ────────────────────────────────────────────────────────────────────


def test_a_non_dict_combine_does_not_also_demand_key_fields(db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    raw = _raw(connectionId=conn.id, keyFields=[], combine=[])  # both deliberately empty/bad
    with pytest.raises(EtlValidationError) as exc_info:
        EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, raw)
    assert "combine" in exc_info.value.field_errors, exc_info.value.field_errors
    assert "keyFields" not in exc_info.value.field_errors, exc_info.value.field_errors


def test_an_empty_group_by_combine_does_not_also_demand_key_fields(db):
    """The general case NIT (iii) covers, beyond S1's non-dict shape: a
    submitted DICT `combine` whose own `groupBy` is empty (its own
    `combine.groupBy` 422 already names the problem)."""
    conn = _open_connection(db)
    company = _company(db, conn.id)
    empty_group_by_combine = {**_combine_for_group(), "groupBy": []}
    raw = _raw(connectionId=conn.id, keyFields=[], combine=empty_group_by_combine)
    with pytest.raises(EtlValidationError) as exc_info:
        EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, raw)
    assert "combine.groupBy" in exc_info.value.field_errors, exc_info.value.field_errors
    assert "keyFields" not in exc_info.value.field_errors, exc_info.value.field_errors


def test_no_combine_at_all_still_demands_key_fields(db):
    """Control - the ORDINARY manual-key flow (no `combine` submitted at
    all) is untouched: an empty `keyFields` is still a 422."""
    conn = _open_connection(db)
    company = _company(db, conn.id)
    raw = _raw(connectionId=conn.id, keyFields=[])
    with pytest.raises(EtlValidationError) as exc_info:
        EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, raw)
    assert "keyFields" in exc_info.value.field_errors, exc_info.value.field_errors


# ── NIT (iv): an omitted empty `round` list normalises the same as an
# explicit `[]` for the S3 active-task demote comparison ────────────────


def test_an_omitted_empty_round_list_does_not_demote_an_active_task(db):
    from modules.autocount.repositories import EntityConfigRepository

    conn = _open_connection(db)
    company = _company(db, conn.id)
    combine_with_round = _combine_for_group()  # carries an explicit "round": []
    assert combine_with_round["round"] == []
    raw = _raw(connectionId=conn.id, keyFields=[], combine=combine_with_round)
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, raw)

    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE)
    config.last_preview_at = NOW
    config.result_columns = ["Code", "Name"]
    db.commit()
    activated = EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE)
    assert activated.etl_status == ETL_STATUS_ACTIVE

    # SAME combine, but this save OMITS the "round" key entirely - a
    # legitimately different wire shape for the identical "no rounding"
    # state - must NOT demote.
    combine_without_round = {k: v for k, v in _combine_for_group().items() if k != "round"}
    raw2 = _raw(connectionId=conn.id, keyFields=[], combine=combine_without_round)
    updated = EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, raw2)
    assert updated.etl_status == ETL_STATUS_ACTIVE, (
        "an omitted empty `round` list must normalise the same as an "
        "explicit `[]` - no genuine combine edit occurred, so the task "
        "must not demote"
    )


def test_a_genuine_round_change_still_demotes_an_active_task(db):
    """Control for the test above - proves the normalisation does not
    swallow a REAL edit."""
    from modules.autocount.repositories import EntityConfigRepository

    conn = _open_connection(db)
    company = _company(db, conn.id)
    raw = _raw(connectionId=conn.id, keyFields=[], combine=_combine_for_group())
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, raw)

    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE)
    config.last_preview_at = NOW
    config.result_columns = ["Code", "Name"]
    db.commit()
    activated = EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE)
    assert activated.etl_status == ETL_STATUS_ACTIVE

    changed_combine = {
        **_combine_for_group(), "round": [{"measure": "n", "mode": "half_up", "dp": 0}],
    }
    raw2 = _raw(connectionId=conn.id, keyFields=[], combine=changed_combine)
    updated = EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, raw2)
    assert updated.etl_status == ETL_STATUS_DRAFT
