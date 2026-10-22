"""Plan 33 (SS-INTEGRATION-ALERT) - the settings + incident wire, RED tests.

AC-33-11 (the four alert settings on PUT/GET etl-task) and AC-33-12
(``openIncident`` on GET etl-task and on the company detail's entity rows).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import AcSyncRun
from tests.test_autocount_etl_task_routes import (  # noqa: F401 - fixtures
    OTHER_TENANT,
    QUERY,
    _auth,
    _clean_runtime,
    _company,
    _config_row,
    _limited_user,
    _other_tenant,
    _url,
    consumer,
    rig,
)

DEFAULTS = {
    "alertsEnabled": True,
    "alertAfterFailedRuns": 2,
    "alertStaleMultiple": 3,
    "alertEmails": [],
}


def _source_config(sql_id: str) -> Dict[str, Any]:
    return {
        "connectionId": sql_id,
        "query": QUERY,
        "keyColumns": ["acc_no"],
        "watermarkColumn": None,
        "comparedColumns": [],
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileAt": "02:00",
    }


def _put(client, company_id: str, sql_id: str, headers=None, **alert: Any):
    return client.put(
        _url(company_id),
        json={"sourceConfig": _source_config(sql_id), **alert},
        headers=headers or _auth(client),
    )


def _open_incident(db, company_id: str, *, tenant_id: str = DEFAULT_TENANT_ID):
    from modules.autocount.models import AcTaskIncident

    config = _config_row(db, type("C", (), {"id": company_id}), tenant_id)
    incident = AcTaskIncident(
        tenant_id=tenant_id,
        company_id=company_id,
        entity_config_id=config.id,
        entity_type=config.entity_type,
        reason="consecutive",
        opened_at=datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc),
        first_failure_at=datetime(2026, 8, 30, 11, 40, tzinfo=timezone.utc),
        failed_runs=14,
        last_error="AutoCount answered HTTP 502 on page 3.",
        last_notified_at=datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc),
        notices_sent=1,
    )
    db.add(incident)
    db.commit()
    return incident


# ── AC-33-11 settings ────────────────────────────────────────────────────────


def test_ac_33_11_absent_keys_read_as_the_defaults(client, rig):
    company_id, _sql = rig
    body = client.get(_url(company_id), headers=_auth(client)).json()
    for key, value in DEFAULTS.items():
        assert body[key] == value, key


def test_ac_33_11_put_saves_the_four_fields_and_echoes_them(client, session_factory, rig):
    company_id, sql_id = rig
    response = _put(
        client, company_id, sql_id,
        alertsEnabled=False, alertAfterFailedRuns=5, alertStaleMultiple=6,
        alertEmails=["ops@example.com", "boss@example.com"],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["alertsEnabled"] is False
    assert body["alertAfterFailedRuns"] == 5
    assert body["alertStaleMultiple"] == 6
    assert body["alertEmails"] == ["ops@example.com", "boss@example.com"]

    # persisted beside the schedule in source_config, and read back by GET
    db = session_factory()
    stored = _config_row(db, type("C", (), {"id": company_id})).source_config
    db.close()
    assert stored["alertsEnabled"] is False
    assert stored["alertAfterFailedRuns"] == 5
    assert stored["alertStaleMultiple"] == 6
    assert stored["alertEmails"] == ["ops@example.com", "boss@example.com"]
    again = client.get(_url(company_id), headers=_auth(client)).json()
    assert again["alertAfterFailedRuns"] == 5 and again["alertsEnabled"] is False


def test_ac_33_11_omitting_the_fields_keeps_the_stored_values(client, rig):
    company_id, sql_id = rig
    assert _put(client, company_id, sql_id, alertAfterFailedRuns=7).status_code == 200
    again = _put(client, company_id, sql_id)
    assert again.status_code == 200, again.text
    assert again.json()["alertAfterFailedRuns"] == 7


def test_ac_33_11_the_boundaries_are_accepted(client, rig):
    company_id, sql_id = rig
    low = _put(client, company_id, sql_id, alertAfterFailedRuns=1, alertStaleMultiple=2,
               alertEmails=[])
    assert low.status_code == 200, low.text
    high = _put(
        client, company_id, sql_id, alertAfterFailedRuns=20, alertStaleMultiple=48,
        alertEmails=[f"u{i}@example.com" for i in range(10)],
    )
    assert high.status_code == 200, high.text
    assert high.json()["alertAfterFailedRuns"] == 20
    assert len(high.json()["alertEmails"]) == 10


def _assert_422_naming(response, field: str) -> None:
    assert response.status_code == 422, response.text
    assert field in response.text, response.text


def test_ac_33_11_failed_runs_in_a_row_out_of_range_is_a_422_naming_the_field(client, rig):
    company_id, sql_id = rig
    for bad in (0, 21, -1):
        _assert_422_naming(
            _put(client, company_id, sql_id, alertAfterFailedRuns=bad), "alertAfterFailedRuns"
        )


def test_ac_33_11_stale_multiple_out_of_range_is_a_422_naming_the_field(client, rig):
    company_id, sql_id = rig
    for bad in (1, 49, 0):
        _assert_422_naming(
            _put(client, company_id, sql_id, alertStaleMultiple=bad), "alertStaleMultiple"
        )


def test_ac_33_11_more_than_ten_also_email_addresses_is_a_422(client, rig):
    company_id, sql_id = rig
    emails = [f"u{i}@example.com" for i in range(11)]
    _assert_422_naming(_put(client, company_id, sql_id, alertEmails=emails), "alertEmails")


def test_ac_33_11_an_invalid_also_email_address_is_a_422(client, rig):
    company_id, sql_id = rig
    _assert_422_naming(
        _put(client, company_id, sql_id, alertEmails=["ok@example.com", "not-an-email"]),
        "alertEmails",
    )


def test_ac_33_11_a_non_boolean_alerts_enabled_is_a_422(client, rig):
    company_id, sql_id = rig
    _assert_422_naming(
        _put(client, company_id, sql_id, alertsEnabled="sometimes"), "alertsEnabled"
    )


def test_ac_33_11_a_rejected_save_stores_nothing(client, session_factory, rig):
    company_id, sql_id = rig
    assert _put(client, company_id, sql_id, alertAfterFailedRuns=4).status_code == 200
    assert _put(client, company_id, sql_id, alertAfterFailedRuns=99).status_code == 422
    assert (
        client.get(_url(company_id), headers=_auth(client)).json()["alertAfterFailedRuns"] == 4
    )


def test_ac_33_11_saving_the_alert_settings_needs_manage(client, session_factory, rig):
    company_id, sql_id = rig
    db = session_factory()
    _limited_user(db, ["autocount.companies.read"], "readonly-s33@example.com")
    db.close()
    limited = _auth(client, "readonly-s33@example.com", "limited1234")
    response = _put(client, company_id, sql_id, headers=limited, alertAfterFailedRuns=3)
    assert response.status_code == 403
    assert (
        client.get(_url(company_id), headers=_auth(client)).json()["alertAfterFailedRuns"] == 2
    )


# ── AC-33-12 openIncident ────────────────────────────────────────────────────


def test_ac_33_12_open_incident_is_null_when_there_is_none(client, rig):
    company_id, _sql = rig
    assert client.get(_url(company_id), headers=_auth(client)).json()["openIncident"] is None
    detail = client.get(f"/autocount/companies/{company_id}", headers=_auth(client)).json()
    customer = [e for e in detail["entities"] if e["entityType"] == "customer"][0]
    assert customer["openIncident"] is None


def test_ac_33_12_the_etl_task_carries_the_open_incident(client, session_factory, rig):
    company_id, _sql = rig
    db = session_factory()
    _open_incident(db, company_id)
    db.close()
    incident = client.get(_url(company_id), headers=_auth(client)).json()["openIncident"]
    assert incident is not None
    assert incident["reason"] == "consecutive"
    assert incident["failedRuns"] == 14
    assert incident["lastError"] == "AutoCount answered HTTP 502 on page 3."
    assert incident["firstFailureAt"].startswith("2026-08-30T11:40:00")
    assert incident["firstFailureAt"].endswith("Z")
    assert incident["openedAt"].startswith("2026-08-30T12:00:00")
    assert incident["openedAt"].endswith("Z")


def test_ac_33_12_the_company_detail_entity_row_carries_the_open_incident(
    client, session_factory, rig
):
    company_id, _sql = rig
    db = session_factory()
    _open_incident(db, company_id)
    db.close()
    detail = client.get(f"/autocount/companies/{company_id}", headers=_auth(client)).json()
    rows = {e["entityType"]: e for e in detail["entities"]}
    assert rows["customer"]["openIncident"]["failedRuns"] == 14
    assert rows["customer"]["openIncident"]["reason"] == "consecutive"
    others = [e for key, e in rows.items() if key != "customer"]
    assert others and all(e["openIncident"] is None for e in others)


def test_ac_33_12_a_closed_incident_is_not_reported(client, session_factory, rig):
    company_id, _sql = rig
    db = session_factory()
    incident = _open_incident(db, company_id)
    incident.closed_at = datetime(2026, 8, 30, 13, 0, tzinfo=timezone.utc)
    incident.close_reason = "recovered"
    db.commit()
    db.close()
    assert client.get(_url(company_id), headers=_auth(client)).json()["openIncident"] is None


def test_ac_33_12_another_tenants_incident_is_never_reported(client, session_factory, rig):
    company_id, _sql = rig
    db = session_factory()
    _other_tenant(db)
    theirs = _company(db, tenant_id=OTHER_TENANT, database_name="THEIRS_S33")
    _open_incident(db, theirs.id, tenant_id=OTHER_TENANT)
    db.close()
    # my own integration shows nothing
    assert client.get(_url(company_id), headers=_auth(client)).json()["openIncident"] is None
    # and their company is not reachable (and so not enumerable) from my tenant
    assert client.get(_url(theirs.id), headers=_auth(client)).status_code == 404
    assert client.get(f"/autocount/companies/{theirs.id}", headers=_auth(client)).status_code == 404


def test_ac_33_12_a_same_id_incident_row_of_another_tenant_does_not_leak(
    client, session_factory, rig
):
    """The incident lookup is tenant-scoped: a row carrying MY entity_config_id
    but ANOTHER tenant's tenant_id must not surface."""
    company_id, _sql = rig
    db = session_factory()
    _other_tenant(db)
    incident = _open_incident(db, company_id)
    incident.tenant_id = OTHER_TENANT
    db.commit()
    db.close()
    assert client.get(_url(company_id), headers=_auth(client)).json()["openIncident"] is None
