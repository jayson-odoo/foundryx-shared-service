"""Sprint-5/10 S5a review round 3 - BLOCKER B2 (require/drop must use the
formula engine's own STRICT boolean coercion, never a second permissive
dialect) plus the remaining SHOULD-FIX/nit items that land in the same
files: S1 (a malformed non-dict ``combine`` must still reach
``validate_combine``'s own "must be an object" 422), S2 (``distinctOf`` +
``combine`` together is a 422, not a silent runtime no-op), S4
(``preview_http`` must 422, never 500, on a runtime ``FormulaError`` from a
drop rule) and N2 (a duplicate ``round[].measure`` is a 422).

Reviewer's own two proofs (B2), reproduced exactly:

* ``require`` of ``concat(d, "x")`` (a plain string result, no comparison)
  under the OLD permissive ``_truthy`` excluded NOTHING (any non-empty
  string coerced ``True``) - the exact opposite of what a require gate is
  for.
* ``drop`` of the SAME shape of formula DROPPED EVERY GROUP, for the
  identical reason.

Both must now fail CLOSED through ``formula.to_bool_strict`` - the SAME
coercion ``not``/``and``/``or``/``if`` already use.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT, ENTITY_WAREHOUSE
from modules.autocount.http_source.combine import (
    CombineDropError,
    apply_combine,
    validate_combine,
)
from modules.autocount.models import AcCompany
from modules.autocount.services.etl_service import EtlService, EtlValidationError

# ── B2: the reviewer's own two live proofs, at the bare apply_combine seam ──

_STRING_COLUMN_COMBINE: Dict[str, Any] = {
    "computed": [],
    "require": [{"name": "r", "formula": 'concat(d, "x")', "reason": "not_boolean"}],
    "measure": "d",
    "groupBy": ["g"],
    "measures": [{"source": "d", "op": "first", "alias": "d_first"}],
    "carry": [],
    "round": [],
    "drop": [],
}


def test_require_of_a_non_boolean_formula_excludes_the_row_never_admits_everything():
    """The OLD `_truthy` coerced any non-empty string True, so `require`
    excluded NOTHING. `to_bool_strict` must fail closed instead - the row
    is excluded with reason `require_error`, exactly like a raising
    formula (AC-10-77's own symmetry rule)."""
    result = apply_combine([{"g": "A", "d": "hello"}], _STRING_COLUMN_COMBINE)
    assert result.rows == [], result.rows
    assert result.metadata["excludedCount"] == 1, result.metadata
    assert result.metadata["excludedRows"][0]["reason"] == "require_error"


_DROP_STRING_COLUMN_COMBINE: Dict[str, Any] = {
    "computed": [],
    "require": [],
    "measure": "g",
    "groupBy": ["g"],
    "measures": [{"source": "d", "op": "first", "alias": "d_first"}],
    "carry": [],
    "round": [],
    "drop": [{"name": "bad", "formula": 'concat(d_first, "x")'}],
}


def test_drop_of_a_non_boolean_formula_raises_never_silently_drops_every_group():
    """The OLD `_truthy` coerced any non-empty string True, so EVERY group
    was dropped. `to_bool_strict` must fail closed instead - a named task
    error (`CombineDropError`, AC-10-79's "never a silent keep" rule
    extended to "never a silent DROP" either), carrying the failing rule's
    index/name, never a silent drop of every group."""
    rows = [{"g": "A", "d": "x"}, {"g": "B", "d": "y"}]
    with pytest.raises(CombineDropError) as exc_info:
        apply_combine(rows, _DROP_STRING_COLUMN_COMBINE)
    assert exc_info.value.index == 0
    assert exc_info.value.rule_name == "bad"


# KILL TEST (for the reviewer) - restore the permissive coercion (re-add
# `_truthy` and swap it back into both loops) and BOTH tests above flip:
# the require test's row survives (`result.rows` non-empty / no exclusion)
# and the drop test raises nothing (every group vanishes silently instead
# of `CombineDropError`). Every OTHER `test_s10_s5a_combine_apply.py`
# assertion is written with genuine comparison/`or` formulas (already real
# booleans) and stays green either way, proving this is additive.


def test_a_require_result_that_is_a_number_also_fails_closed():
    combine = {
        "computed": [], "require": [{"name": "r", "formula": "qty", "reason": "bad"}],
        "measure": "qty", "groupBy": ["g"],
        "measures": [{"source": "qty", "op": "sum", "alias": "total"}],
        "carry": [], "round": [], "drop": [],
    }
    result = apply_combine([{"g": "A", "qty": 5}], combine)
    assert result.rows == []
    assert result.metadata["excludedRows"][0]["reason"] == "require_error"


# ── AC-10-76's own save-time rule: a SAMPLE-evaluated non-boolean result
# 422s a require/drop formula ────────────────────────────────────────────


def test_validate_combine_422s_a_require_formula_that_samples_non_boolean():
    combine = {**_STRING_COLUMN_COMBINE}
    sample = [{"g": "A", "d": "hello"}, {"g": "B", "d": "world"}]
    errors = validate_combine(combine, ["g", "d"], sample=sample)
    assert "combine.require[0].formula" in errors, errors


def test_validate_combine_422s_a_drop_formula_that_samples_non_boolean():
    combine = {**_DROP_STRING_COLUMN_COMBINE}
    sample = [{"g": "A", "d": "x"}, {"g": "B", "d": "y"}]
    errors = validate_combine(combine, ["g", "d"], sample=sample)
    assert "combine.drop[0].formula" in errors, errors


def test_validate_combine_accepts_a_genuinely_boolean_require_drop_pair_with_a_sample():
    combine = {
        "computed": [],
        "require": [{"name": "r", "formula": "qty > 0", "reason": "non_positive"}],
        "measure": "qty", "groupBy": ["g"],
        "measures": [{"source": "qty", "op": "sum", "alias": "total"}],
        "carry": [], "round": [],
        "drop": [{"name": "zero", "formula": "total == 0"}],
    }
    sample = [{"g": "A", "qty": 5}, {"g": "B", "qty": 3}]
    errors = validate_combine(combine, ["g", "qty"], sample=sample)
    assert errors == {}, errors


def test_validate_combine_without_a_sample_skips_the_boolean_check_unchanged():
    """No sample (the real task-save path, which stores no row DATA, only
    column NAMES) - the boolean-type check is a structural no-op, mirroring
    every other "accepted un-checked when never previewed" rule this
    validator already applies."""
    combine = {**_STRING_COLUMN_COMBINE}
    errors = validate_combine(combine, ["g", "d"])
    assert "combine.require[0].formula" not in errors, errors


def test_validate_combine_boolean_sample_check_does_not_mask_a_structural_error():
    """A structurally invalid combine (an unknown group-by column) must
    surface ITS OWN error, never also run the sample-based check (which
    could otherwise pile on a confusing second, unrelated message)."""
    combine = {**_STRING_COLUMN_COMBINE, "groupBy": ["not_a_column"]}
    sample = [{"g": "A", "d": "hello"}]
    errors = validate_combine(combine, ["g", "d"], sample=sample)
    assert "combine.groupBy[0]" in errors, errors


# ── N2: a duplicate round[].measure is a 422 ─────────────────────────────


def test_validate_combine_rejects_a_duplicate_round_measure():
    combine = {
        "computed": [], "require": [], "measure": "v", "groupBy": ["g"],
        "measures": [{"source": "v", "op": "sum", "alias": "total"}],
        "carry": [],
        "round": [
            {"measure": "total", "mode": "half_up", "dp": 0},
            {"measure": "total", "mode": "half_up", "dp": 2},
        ],
        "drop": [],
    }
    errors = validate_combine(combine, ["g", "v"])
    assert "combine.round[1].measure" in errors, errors
    assert "combine.round[0].measure" not in errors, errors


# ── S1: a malformed non-dict `combine` must still 422 as "must be an
# object", never silently vanish ─────────────────────────────────────────


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


def test_a_non_dict_combine_surfaces_the_must_be_an_object_422(db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    raw = _raw(connectionId=conn.id, combine=[])  # deliberately malformed
    with pytest.raises(EtlValidationError) as exc_info:
        EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, raw)
    assert "combine" in exc_info.value.field_errors, exc_info.value.field_errors
    assert exc_info.value.field_errors["combine"] == (
        "The combine step must be an object."
    )


def test_a_non_dict_combine_never_reaches_persistence(db):
    """The malformed save must be rejected outright - a LATER, clean save
    with no `combine` key at all must find nothing stored (never a
    half-written `combine` from the rejected attempt)."""
    conn = _open_connection(db)
    company = _company(db, conn.id)
    bad_raw = _raw(connectionId=conn.id, combine="not even a list")
    with pytest.raises(EtlValidationError):
        EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, bad_raw)

    clean_raw = _raw(connectionId=conn.id)
    view = EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, clean_raw)
    assert view.source_config.get("combine") is None, view.source_config


# ── S2: distinctOf + combine together is a 422 ───────────────────────────


def _combine_for_group(group_by=("Code",)) -> Dict[str, Any]:
    return {
        "computed": [], "require": [], "measure": group_by[0], "groupBy": list(group_by),
        "measures": [{"source": group_by[0], "op": "count", "alias": "n"}],
        "carry": [], "round": [], "drop": [],
    }


def test_distinct_of_and_combine_together_is_a_named_422(db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    raw = _raw(
        connectionId=conn.id, keyFields=[], distinctOf=["Code"], combine=_combine_for_group(),
    )
    with pytest.raises(EtlValidationError) as exc_info:
        EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, raw)
    assert "combine" in exc_info.value.field_errors, exc_info.value.field_errors


def test_combine_alone_still_saves_clean_without_distinct_of(db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    raw = _raw(connectionId=conn.id, keyFields=[], combine=_combine_for_group())
    view = EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, raw)
    assert view.source_config["combine"] == _combine_for_group()


# ── S3: any combine EDIT (not only groupBy) demotes an ACTIVE task ──────


def test_changing_a_measures_only_field_demotes_an_active_task(db):
    from modules.autocount.models import ETL_STATUS_ACTIVE, ETL_STATUS_DRAFT
    from modules.autocount.repositories import EntityConfigRepository
    from datetime import datetime, timezone

    conn = _open_connection(db)
    company = _company(db, conn.id)
    raw = _raw(connectionId=conn.id, keyFields=[], combine=_combine_for_group())
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, raw)

    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE)
    config.last_preview_at = datetime(2026, 9, 20, tzinfo=timezone.utc)
    config.result_columns = ["Code", "Name"]
    db.commit()
    activated = EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE)
    assert activated.etl_status == ETL_STATUS_ACTIVE

    # SAME groupBy, DIFFERENT measures op - AC-10-80's own text: this
    # changes the ROW HASH of every combined row, so it must demote too,
    # not only a groupBy (identity) change.
    changed_combine = {
        **_combine_for_group(), "measures": [{"source": "Code", "op": "sum", "alias": "n"}],
    }
    raw2 = _raw(connectionId=conn.id, keyFields=[], combine=changed_combine)
    updated = EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, raw2)
    assert updated.etl_status == ETL_STATUS_DRAFT, (
        "a measures-only combine edit changes the row hash of every "
        "combined row (AC-10-80) and must demote an ACTIVE task, exactly "
        "like a groupBy edit does"
    )


# ── S4: preview_http 422s (never 500s) on a runtime FormulaError from a
# drop rule that the sample-based type check could not have caught (the
# formula IS boolean-typed; it raises on a genuinely non-numeric value on
# ONE grouped row, a data fault the sample check explicitly does not treat
# as a type-inference signal) ─────────────────────────────────────────────


@pytest.fixture
def client_headers(client):
    response = client.post(
        "/auth/login", json={"email": "demo@example.com", "password": "demo1234"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_preview_http_422s_a_runtime_drop_error_instead_of_500ing(client, client_headers, db):
    import httpx
    from app.main import app
    from modules.autocount.http_client import get_http_transport

    conn = _open_connection(db)
    rows = [{"tag": "10"}, {"tag": "oops"}]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "TotalCount": len(rows), "Page": 1, "PageSize": 50, "TotalPages": 1, "Data": rows,
        })

    combine = {
        "computed": [], "require": [], "measure": "tag", "groupBy": ["tag"],
        "measures": [{"source": "tag", "op": "count", "alias": "n"}],
        "carry": [], "round": [],
        "drop": [{"name": "big", "formula": "number(tag) > 5"}],
    }
    app.dependency_overrides[get_http_transport] = lambda: httpx.Client(
        transport=httpx.MockTransport(handler)
    )
    try:
        response = client.post(
            "/autocount/http/preview",
            json={"connectionId": conn.id, "path": "/itembypage", "combine": combine},
            headers=client_headers,
        )
    finally:
        app.dependency_overrides.pop(get_http_transport, None)

    # sprint-5/11 (AC-11-21/22/25) - a runtime drop-formula error is
    # discovered only AFTER the network fetch (over the sampled rows), so it
    # is now a FAILED job (never a synchronous 422 - the walk itself moved
    # off-request), carrying the SAME per-field message on `fieldErrors`.
    assert response.status_code == 202, response.text
    poll = client.get(f"/autocount/previews/{response.json()['jobId']}", headers=client_headers)
    assert poll.status_code == 200, poll.text
    body = poll.json()
    assert body["status"] == "failed", body
    field_errors = body["fieldErrors"]
    assert "combine.drop[0].formula" in field_errors, field_errors
