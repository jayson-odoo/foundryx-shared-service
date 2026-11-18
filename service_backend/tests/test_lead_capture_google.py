"""Lead Capture R2 part 1 (card 68a, plan 64 AC-64-40/41/44): Google Ads lead
form receiver + guided paste path.

Google only ever POSTs to us on this path, so no Google call is mocked: the
bodies follow Google's documented lead form webhook
(https://developers.google.com/google-ads/webhook/docs/implementation).
Fake data only.
"""
from __future__ import annotations

import json
import logging

import pytest

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from app.secrets import decrypt_secret
from modules.lead_capture.models import (
    SOURCE_DISCONNECTED,
    SOURCE_LIVE,
    SOURCE_WAITING_FOR_TEST,
    LcSource,
)

from tests.test_lead_capture_prototype import (  # noqa: F401 - pytest fixtures
    TENANT_B,
    _fake_realtime,
    _key,
    _leads,
    _login,
    _register,
    _second_tenant,
    lc,
    posts,
)

GOOGLE_LEAD = "TeSter-123-ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GOOGLE_FORM = 40000000001


def _google_body(key: str, *, lead_id: str = GOOGLE_LEAD, is_test: bool = True, extra_columns=None) -> dict:
    columns = [
        {"column_id": "FULL_NAME", "column_name": "Full Name", "string_value": "Test User"},
        {"column_id": "EMAIL", "column_name": "User Email", "string_value": "google.test@example.com"},
        {"column_id": "PHONE_NUMBER", "column_name": "User Phone", "string_value": "+60120000001"},
    ]
    columns += extra_columns or []
    return {
        "lead_id": lead_id,
        "api_version": "1.0",
        "form_id": GOOGLE_FORM,
        "campaign_id": 50000000001,
        "adgroup_id": 60000000001,
        "creative_id": 70000000001,
        "gcl_id": "gclid-test-0001",
        "google_key": key,
        "is_test": is_test,
        "user_column_data": columns,
    }


def _create(client, headers) -> dict:
    res = client.post("/lead-capture/sources/google", json={}, headers=headers)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["url"].endswith(f"/public/lead-capture/in/{body['url'].rsplit('/', 1)[-1]}")
    return body


def _post(client, url_or_key: str, body) -> "object":
    source_key = url_or_key.rsplit("/", 1)[-1]
    data = body if isinstance(body, (bytes, str)) else json.dumps(body)
    return client.post(
        f"/public/lead-capture/in/{source_key}", content=data, headers={"Content-Type": "application/json"}
    )


def _source(session_factory, source_id: str) -> LcSource:
    db = session_factory()
    try:
        return db.query(LcSource).filter(LcSource.id == source_id).one()
    finally:
        db.close()


# ── R1 create ───────────────────────────────────────────────────────────────

def test_create_google_source_gives_url_and_key_once(client, lc):
    headers = _login(client)
    made = _create(client, headers)
    assert len(made["key"]) >= 32 and made["source"]["platform"] == "google"
    row = _source(lc, made["source"]["id"])
    assert row.platform == "google" and row.mode == "guided" and row.status == SOURCE_WAITING_FOR_TEST
    assert row.source_key and made["url"].endswith(row.source_key)
    # the key is stored encrypted, never plain, and never echoed by a read
    assert made["key"] not in (row.credentials_encrypted or "")
    assert decrypt_secret(row.credentials_encrypted)["googleKey"] == made["key"]
    listed = client.get("/lead-capture/sources", headers=headers).json()["data"]
    assert made["key"] not in json.dumps(listed)


def test_gateway_creates_google_source_for_its_tenant(client, lc):
    headers = _login(client)
    key = _key(client, headers)
    res = client.post("/api/v1/lead-capture/sources/google", json={}, headers={"Authorization": f"Bearer {key}"})
    assert res.status_code == 201, res.text
    row = _source(lc, res.json()["source"]["id"])
    assert row.tenant_id == DEFAULT_TENANT_ID and row.platform == "google"


# ── R2/R3/R5 receive ────────────────────────────────────────────────────────

def test_test_lead_is_stored_mapped_delivered_and_goes_live(client, lc, posts, caplog):
    caplog.set_level(logging.DEBUG)
    headers = _login(client)
    _register(client, _key(client, headers))
    made = _create(client, headers)

    res = _post(client, made["url"], _google_body(made["key"]))
    assert res.status_code == 200, res.text

    leads = _leads(lc)
    assert len(leads) == 1
    lead = leads[0]
    assert lead.platform == "google" and lead.platform_lead_id == GOOGLE_LEAD and lead.is_test is True
    assert lead.form_id == str(GOOGLE_FORM)
    assert lead.email == "google.test@example.com" and lead.phone_e164 == "+60120000001"
    stored = decrypt_secret(lead.fields_encrypted)["fields"]
    assert stored["name"] == "Test User" and stored["email"] == "google.test@example.com"
    assert lead.attribution_json["campaignId"] == "50000000001"
    assert lead.attribution_json["adgroupId"] == "60000000001"
    assert lead.attribution_json["creativeId"] == "70000000001"
    assert lead.attribution_json["gclid"] == "gclid-test-0001"
    # the Google key never lands in the stored raw body or a log line
    assert made["key"] not in json.dumps(decrypt_secret(lead.raw_encrypted))
    for secret in (made["key"], "google.test@example.com", "+60120000001"):
        assert secret not in caplog.text

    assert _source(lc, made["source"]["id"]).status == SOURCE_LIVE
    assert len(posts) == 1
    sent = json.loads(posts[0]["body"])
    assert sent["type"] == "lead.created" and sent["data"]["isTest"] is True
    assert sent["data"]["platform"] == "google"


def test_real_lead_before_any_test_also_goes_live(client, lc, posts):
    headers = _login(client)
    made = _create(client, headers)
    assert _post(client, made["url"], _google_body(made["key"], is_test=False)).status_code == 200
    assert _leads(lc)[0].is_test is False
    assert _source(lc, made["source"]["id"]).status == SOURCE_LIVE


def test_repeat_lead_id_stores_once(client, lc, posts):
    headers = _login(client)
    made = _create(client, headers)
    body = _google_body(made["key"])
    assert _post(client, made["url"], body).status_code == 200
    assert _post(client, made["url"], body).status_code == 200
    assert len(_leads(lc)) == 1


def test_custom_question_goes_to_notes_and_counts_unmapped(client, lc, posts):
    headers = _login(client)
    made = _create(client, headers)
    extra = [{"column_name": "What is your budget?", "string_value": "Under 10k"}]
    assert _post(client, made["url"], _google_body(made["key"], extra_columns=extra)).status_code == 200
    fields = decrypt_secret(_leads(lc)[0].fields_encrypted)["fields"]
    assert "What is your budget?: Under 10k" in (fields["notes"] or "")
    src = client.get("/lead-capture/sources", headers=headers).json()["data"][0]
    assert src["needsMapping"][0]["formId"] == str(GOOGLE_FORM)


# ── R2 refusals ─────────────────────────────────────────────────────────────

def test_wrong_and_unknown_key_are_the_same_403_and_store_nothing(client, lc):
    headers = _login(client)
    made = _create(client, headers)
    wrong = _post(client, made["url"], _google_body("wrong-key"))
    missing = _post(client, made["url"], {k: v for k, v in _google_body("x").items() if k != "google_key"})
    unknown = _post(client, "no-such-source-key", _google_body(made["key"]))
    assert wrong.status_code == missing.status_code == unknown.status_code == 403
    assert wrong.json() == unknown.json() == missing.json()
    assert wrong.json()["error"]["code"] == "invalid_key"
    assert _leads(lc) == []


def test_bad_keys_are_throttled_per_ip_but_a_right_key_is_not(client, lc, posts, monkeypatch):
    monkeypatch.setattr(settings, "throttle_lead_gateway_max_fails", 3)
    headers = _login(client)
    made = _create(client, headers)
    codes = [_post(client, made["url"], _google_body("wrong")).status_code for _ in range(5)]
    assert codes[:3] == [403, 403, 403] and codes[-1] == 429
    over = _post(client, made["url"], _google_body("wrong"))
    assert "Retry-After" in over.headers
    assert _post(client, made["url"], _google_body(made["key"])).status_code == 200


@pytest.mark.parametrize("raw", [b"not json", b"[]", json.dumps({"google_key": "k"}).encode()])
def test_malformed_body_is_400(client, lc, raw):
    headers = _login(client)
    made = _create(client, headers)
    if raw == json.dumps({"google_key": "k"}).encode():
        raw = json.dumps({"google_key": made["key"]}).encode()  # right key, no lead_id
    res = _post(client, made["url"], raw)
    assert res.status_code == 400 and res.json()["error"]["code"] == "invalid_body"
    assert _leads(lc) == []


def test_oversized_body_is_refused(client, lc):
    headers = _login(client)
    made = _create(client, headers)
    big = [{"column_name": "Notes", "string_value": "x" * 70_000}]
    res = _post(client, made["url"], _google_body(made["key"], extra_columns=big))
    assert res.status_code in (400, 413)
    assert _leads(lc) == []


def test_disconnected_source_is_410(client, lc):
    headers = _login(client)
    made = _create(client, headers)
    res = client.delete(f"/lead-capture/sources/{made['source']['id']}", headers=headers)
    assert res.status_code == 204, res.text
    assert _source(lc, made["source"]["id"]).status == SOURCE_DISCONNECTED
    assert _post(client, made["url"], _google_body(made["key"])).status_code == 410
    assert _leads(lc) == []


def test_module_off_for_tenant_stores_nothing(client, lc):
    from app.services.app_store_service import AppStoreService

    headers = _login(client)
    made = _create(client, headers)
    db = lc()
    try:
        AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "lead_capture")
        db.commit()
    finally:
        db.close()
    res = _post(client, made["url"], _google_body(made["key"]))
    assert res.status_code == 403 and res.json()["error"]["code"] == "service_not_enabled"
    assert _leads(lc) == []


# ── R8 rotate ───────────────────────────────────────────────────────────────

def test_rotate_key_kills_the_old_key_at_once(client, lc, posts):
    headers = _login(client)
    made = _create(client, headers)
    res = client.post(f"/lead-capture/sources/{made['source']['id']}/rotate-key", headers=headers)
    assert res.status_code == 200, res.text
    new = res.json()
    assert new["key"] != made["key"] and new["url"] == made["url"]
    assert _post(client, made["url"], _google_body(made["key"])).status_code == 403
    assert _post(client, made["url"], _google_body(new["key"])).status_code == 200
    history = client.get(f"/lead-capture/sources/{made['source']['id']}/history", headers=headers).json()
    assert any(row["action"] == "key_rotated" for row in history["data"])


def test_rotate_key_of_an_unknown_source_is_404(client, lc):
    headers = _login(client)
    res = client.post("/lead-capture/sources/not-a-source/rotate-key", headers=headers)
    assert res.status_code == 404


def test_gateway_rotate_is_tenant_scoped(client, lc):
    headers = _login(client)
    made = _create(client, headers)
    _second_tenant(lc, allow_sharing=False)
    db = lc()
    try:
        from modules.lead_capture.services import key_service

        _row, other_key = key_service.issue(db, TENANT_B, name="Other", created_by=None)
        db.commit()
    finally:
        db.close()
    res = client.post(
        f"/api/v1/lead-capture/sources/{made['source']['id']}/rotate-key",
        headers={"Authorization": f"Bearer {other_key}"},
    )
    assert res.status_code == 404
    assert _post(client, made["url"], _google_body(made["key"])).status_code == 200
