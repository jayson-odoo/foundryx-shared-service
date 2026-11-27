"""PLANNER-3D-S1 red tests: the tenant gateway the CRM client calls.

Contract: documentation/planner3d/module-contract.md 2, 3.1-3.3, 3.5, 3.7, 5; behaviour card
documentation/plans/planner3d-s1-gateway-card.md (crew answers: (a) on all five). The CRM side is
sorento-crm ``planner_ss_client.py`` (PR #2789): ``POST {base}/uploads`` part ``file`` -> ``id``;
``POST {base}/models`` JSON + ``Idempotency-Key`` -> ``id``; ``GET {base}/jobs/{id}`` ->
``status`` + ``result.files[{role, name, url, size, sha256}]``. The worker is driven through
its real pull API (the "mock" is the test acting as the worker).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from tests.planner3d_helpers import (  # noqa: F401 - pytest fixtures
    B_EMAIL,
    PW,
    TENANT_B,
    TENANT_B_SLUG,
    VIEW_EMAIL,
    claim,
    err_code,
    finish,
    glb_bytes,
    jpeg_bytes,
    login,
    p3,
    png_bytes,
    put_output,
    sha,
    staff,
    staff_b,
    webp_bytes,
    worker_headers,
    worker_token,
)

BASE = "/api/v1/planner3d"
DIMS = {"length": 700.0, "width": 380.0, "height": 780.0}


# ── helpers ─────────────────────────────────────────────────────────────────

def issue_key(client, staff_headers, name="CRM") -> str:
    res = client.post("/planner3d/keys", json={"name": name}, headers=staff_headers)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["key"].startswith("fx3_live_")
    return body["key"]


def bearer(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def upload(client, key, data=None, mime="image/png"):
    return client.post(f"{BASE}/uploads", files={"file": ("photo", data or png_bytes(), mime)}, headers=bearer(key))


def create(client, key, upload_ids, *, idem="crm-job-1", body=None):
    payload = body or {
        "productCode": "ZZT-1",
        "uploadIds": upload_ids,
        "dimensionsMm": dict(DIMS),
        "company": "SRT",
    }
    headers = bearer(key)
    if idem:
        headers["Idempotency-Key"] = idem
    return client.post(f"{BASE}/models", json=payload, headers=headers)


def run_worker(client, job_id, n=2, status="succeeded"):
    got = claim(client, ["model"])
    assert got.status_code == 200 and got.json()["jobId"] == job_id, got.text
    if status == "succeeded":
        for i in range(1, n + 1):
            res = put_output(client, job_id, f"candidate-{i}.glb", glb_bytes(f"c{i}"), role="candidate")
            assert res.status_code == 201, res.text
            put_output(client, job_id, f"candidate-{i}.json", b'{"ok": true}', role="report")
        return finish(client, job_id)
    return finish(client, job_id, status="failed", error={"code": "worker_failed", "message": "boom"})


@pytest.fixture
def key(client, staff):
    return issue_key(client, staff)


@pytest.fixture
def key_b(client, staff_b):
    return issue_key(client, staff_b, "CRM B")


# ── keys: issue, mask, revoke (staff) ───────────────────────────────────────

def test_key_is_shown_once_then_masked(client, staff):
    full = issue_key(client, staff)
    listed = client.get("/planner3d/keys", headers=staff).json()["data"]
    assert len(listed) == 1
    row = listed[0]
    assert row["keyMasked"] == f"fx3_live_****{full[-4:]}"
    assert "key" not in row and full not in json.dumps(listed)
    assert row["revokedAt"] is None and row["name"] == "CRM"


def test_key_routes_need_the_keys_permission(client, p3):
    viewer = login(client, VIEW_EMAIL)
    assert client.get("/planner3d/keys", headers=viewer).status_code == 403
    assert client.post("/planner3d/keys", json={"name": "x"}, headers=viewer).status_code == 403


def test_revoked_key_answers_401(client, staff, key):
    assert upload(client, key).status_code == 201
    key_id = client.get("/planner3d/keys", headers=staff).json()["data"][0]["id"]
    assert client.delete(f"/planner3d/keys/{key_id}", headers=staff).status_code == 204
    res = upload(client, key)
    assert res.status_code == 401
    assert err_code(res) == "invalid_api_key"


def test_a_tenant_cannot_revoke_another_tenants_key(client, staff, staff_b, key):
    key_id = client.get("/planner3d/keys", headers=staff).json()["data"][0]["id"]
    assert client.delete(f"/planner3d/keys/{key_id}", headers=staff_b).status_code == 404
    assert upload(client, key).status_code == 201


# ── gateway auth ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer"}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer fx3_live_nope"},
     {"Authorization": "Bearer fxl_live_wrongscheme000000"}],
)
def test_missing_or_bad_key_is_401_envelope(client, p3, headers):
    res = client.get(f"{BASE}/jobs/anything", headers=headers)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_api_key"


def test_failed_keys_from_one_ip_are_throttled(client, p3, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "throttle_planner3d_gateway_max_fails", 2)
    for _ in range(2):
        assert client.get(f"{BASE}/jobs/x", headers=bearer("fx3_live_bad00000000000")).status_code == 401
    res = client.get(f"{BASE}/jobs/x", headers=bearer("fx3_live_bad00000000000"))
    assert res.status_code == 429 and res.json()["error"]["code"] == "rate_limited"
    assert res.headers.get("Retry-After")


def test_per_key_request_budget(client, key, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "throttle_planner3d_gateway_key_max_requests", 2)
    assert client.get(f"{BASE}/jobs/x", headers=bearer(key)).status_code == 404
    assert client.get(f"{BASE}/jobs/x", headers=bearer(key)).status_code == 404
    res = client.get(f"{BASE}/jobs/x", headers=bearer(key))
    assert res.status_code == 429 and res.json()["error"]["code"] == "rate_limited"


def test_module_not_active_is_403(client, p3, key):
    from app.services.app_store_service import AppStoreService
    from app.models import DEFAULT_TENANT_ID

    db = p3()
    try:
        AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "planner3d")
        db.commit()
    finally:
        db.close()
    res = upload(client, key)
    assert res.status_code == 403 and res.json()["error"]["code"] == "service_not_enabled"


def test_wrong_tenant_key_sees_404_for_jobs_and_uploads(client, key, key_b):
    upl = upload(client, key).json()["id"]
    job = create(client, key, [upl]).json()["id"]
    res = client.get(f"{BASE}/jobs/{job}", headers=bearer(key_b))
    assert res.status_code == 404 and res.json()["error"]["code"] == "not_found"
    res = create(client, key_b, [upl], idem="b-1")
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_request"


def test_every_call_is_audited_without_payload(client, p3, key):
    from modules.planner3d.models import P3ApiAudit

    upload(client, key)
    db = p3()
    try:
        rows = db.query(P3ApiAudit).all()
        assert [(r.method, r.route, r.status_code) for r in rows] == [("POST", f"{BASE}/uploads", 201)]
    finally:
        db.close()


# ── uploads ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("data,mime", [(png_bytes(), "image/png"), (jpeg_bytes(), "image/jpeg"), (webp_bytes(), "image/webp")])
def test_upload_happy_path(client, key, data, mime):
    res = upload(client, key, data, "application/octet-stream")  # declared type is ignored
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["id"].startswith("upl_")
    assert body["mime"] == mime and body["size"] == len(data) and body["sha256"] == sha(data)
    assert body["expiresAt"].endswith("Z")


def test_upload_wrong_type_is_415(client, key):
    res = upload(client, key, b"%PDF-1.4 not an image", "image/png")
    assert res.status_code == 415 and res.json()["error"]["code"] == "unsupported_file"


def test_upload_over_cap_is_413(client, key, monkeypatch):
    from modules.planner3d.services import gateway_service

    monkeypatch.setattr(gateway_service, "UPLOAD_CAP", 50)
    res = upload(client, key, png_bytes() + b"\0" * 100)
    assert res.status_code == 413 and res.json()["error"]["code"] == "file_too_large"


def test_upload_without_file_part_is_rejected(client, key):
    res = client.post(f"{BASE}/uploads", files={"other": ("x", b"y", "text/plain")}, headers=bearer(key))
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] == "invalid_request"


# ── create model job ────────────────────────────────────────────────────────

def test_create_model_job_matches_the_crm_contract_and_feeds_the_worker(client, key):
    upl = upload(client, key, jpeg_bytes()).json()["id"]
    res = create(client, key, [upl])
    assert res.status_code == 202, res.text
    job = res.json()
    assert job["id"] and job["kind"] == "model" and job["status"] == "queued"
    assert job["input"] == {"productCode": "ZZT-1", "company": "SRT", "uploadIds": [upl], "dimensionsMm": DIMS}
    assert job["result"] == {"files": []} and job["error"] is None
    got = claim(client, ["model"])
    assert got.status_code == 200
    body = got.json()
    assert body["jobId"] == job["id"]
    assert body["params"]["dimensionsMm"] == DIMS
    assert [i["name"] for i in body["inputs"]] == ["photo-1.jpg"]
    data = client.get(f"/planner3d/worker/jobs/{job['id']}/inputs/photo-1.jpg", headers=worker_headers())
    assert data.status_code == 200 and data.content == jpeg_bytes()


def test_idempotent_repeat_returns_the_first_job(client, key):
    upl = upload(client, key).json()["id"]
    first = create(client, key, [upl], idem="same")
    again = create(client, key, [upl], idem="same")
    assert first.status_code == 202 and again.status_code == 200
    assert again.json()["id"] == first.json()["id"]


def test_same_idempotency_key_different_body_is_409(client, key):
    upl = upload(client, key).json()["id"]
    assert create(client, key, [upl], idem="same").status_code == 202
    other = {"productCode": "ZZT-2", "uploadIds": [upl], "dimensionsMm": dict(DIMS), "company": "SRT"}
    res = create(client, key, [upl], idem="same", body=other)
    assert res.status_code == 409 and res.json()["error"]["code"] == "idempotency_conflict"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.update(uploadIds=[]),
        lambda b: b.update(uploadIds=["upl_nope"]),
        lambda b: b.update(dimensionsMm={"length": 0, "width": 1, "height": 1}),
        lambda b: b.pop("dimensionsMm"),
        lambda b: b.update(productCode=""),
        lambda b: b.update(productCode="x" * 101),
    ],
)
def test_create_validation_is_422(client, key, mutate):
    upl = upload(client, key).json()["id"]
    body = {"productCode": "ZZT-1", "uploadIds": [upl], "dimensionsMm": dict(DIMS), "company": None}
    mutate(body)
    res = create(client, key, [upl], idem=None, body=body)
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "invalid_request"


def test_more_than_three_photos_is_422(client, key):
    ids = [upload(client, key).json()["id"] for _ in range(4)]
    res = create(client, key, ids, idem=None)
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_request"


def test_expired_upload_is_422(client, p3, key):
    from modules.planner3d.models import P3Upload

    upl = upload(client, key).json()["id"]
    db = p3()
    try:
        db.get(P3Upload, upl).expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()
    res = create(client, key, [upl], idem=None)
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_request"


def test_queue_full_is_429(client, key, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "planner3d_max_queued_jobs", 1)
    upl = upload(client, key).json()["id"]
    assert create(client, key, [upl], idem="a").status_code == 202
    res = create(client, key, [upl], idem="b")
    assert res.status_code == 429 and res.json()["error"]["code"] == "queue_full"


# ── get job: states + signed candidate links ────────────────────────────────

def _job(client, key, job_id):
    res = client.get(f"{BASE}/jobs/{job_id}", headers=bearer(key))
    assert res.status_code == 200, res.text
    return res.json()


def test_job_moves_queued_running_succeeded_with_candidate_links(client, key):
    upl = upload(client, key).json()["id"]
    job_id = create(client, key, [upl]).json()["id"]
    assert _job(client, key, job_id)["status"] == "queued"
    got = claim(client, ["model"])
    assert got.status_code == 200
    assert _job(client, key, job_id)["status"] == "running"
    for i in (1, 2):
        put_output(client, job_id, f"candidate-{i}.glb", glb_bytes(f"c{i}"), role="candidate")
    assert finish(client, job_id).status_code == 200
    job = _job(client, key, job_id)
    assert job["status"] == "succeeded" and job["progress"] == 100
    files = job["result"]["files"]
    assert [(f["role"], f["name"]) for f in files] == [("candidate", "candidate-1.glb"), ("candidate", "candidate-2.glb")]
    for i, f in enumerate(files, start=1):
        assert f["size"] == len(glb_bytes(f"c{i}")) and f["sha256"] == sha(glb_bytes(f"c{i}"))
        assert f["mime"] == "model/gltf-binary" and f["expiresAt"].endswith("Z")
        url = urlparse(f["url"])
        assert url.scheme in ("http", "https") and url.netloc
        res = client.get(f"{url.path}?{url.query}")  # no key
        assert res.status_code == 200 and res.content == glb_bytes(f"c{i}")
        assert res.headers["content-security-policy"] == "sandbox"
        assert res.headers["x-content-type-options"] == "nosniff"


def test_signed_link_tampered_or_expired_is_404(client, key, monkeypatch):
    upl = upload(client, key).json()["id"]
    job_id = create(client, key, [upl]).json()["id"]
    run_worker(client, job_id)
    url = urlparse(_job(client, key, job_id)["result"]["files"][0]["url"])
    q = parse_qs(url.query)
    exp, sig = q["exp"][0], q["sig"][0]
    assert client.get(f"{url.path}?exp={exp}&sig={'0' * len(sig)}").status_code == 404
    assert client.get(f"{url.path}?exp={int(exp) + 10}&sig={sig}").status_code == 404
    assert client.get(url.path).status_code in (404, 422)
    from modules.planner3d.services import signed_files

    past = int(datetime.now(timezone.utc).timestamp()) - 5
    file_id = url.path.rsplit("/", 1)[-1]
    assert client.get(f"{url.path}?exp={past}&sig={signed_files._sig(file_id, past)}").status_code == 404


def test_failed_and_cancelled_jobs(client, key, staff):
    upl = upload(client, key).json()["id"]
    job_id = create(client, key, [upl], idem="f").json()["id"]
    run_worker(client, job_id, status="failed")
    job = _job(client, key, job_id)
    assert job["status"] == "failed" and job["result"] == {"files": []}
    assert job["error"] == {"code": "worker_failed", "message": "boom"}
    other = create(client, key, [upl], idem="c").json()["id"]
    assert client.post(f"/planner3d/jobs/{other}/cancel", headers=staff).status_code == 200
    assert _job(client, key, other)["status"] == "cancelled"


# ── model.candidates_ready push ─────────────────────────────────────────────

@pytest.fixture
def sent(monkeypatch):
    from app.services import webhook_post
    from modules.planner3d.services import events_service

    calls = []

    def fake_post(url, *, content, headers, timeout):
        calls.append({"url": url, "body": content, "headers": headers})
        return webhook_post.PostReply(status_code=200)

    monkeypatch.setattr(events_service, "_post", fake_post)
    monkeypatch.setattr(events_service, "_check_address", lambda url, budget: budget)
    return calls


def add_receiver(client, staff_headers, url="https://crm.example.test/api/v1/public/planner/events"):
    res = client.post(
        "/planner3d/receivers", json={"url": url, "events": ["model.candidates_ready"]}, headers=staff_headers
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["secret"].startswith("whsec_")
    return body


def test_finish_pushes_a_signed_candidates_ready_event(client, staff, key, sent):
    from modules.planner3d.services import events_service

    receiver = add_receiver(client, staff)
    upl = upload(client, key).json()["id"]
    job_id = create(client, key, [upl]).json()["id"]
    run_worker(client, job_id)
    assert len(sent) == 1
    call = sent[0]
    assert call["url"] == "https://crm.example.test/api/v1/public/planner/events"
    assert call["headers"]["X-Planner3d-Event"] == "model.candidates_ready"
    assert events_service.verify(receiver["secret"], call["headers"]["X-Planner3d-Signature"], call["body"])
    env = json.loads(call["body"])
    assert env["type"] == "model.candidates_ready" and env["id"]
    data = env["data"]
    assert data["jobId"] == job_id and data["status"] == "succeeded"
    assert data["productCode"] == "ZZT-1" and data["company"] == "SRT"
    assert [f["name"] for f in data["files"]] == ["candidate-1.glb", "candidate-2.glb"]
    assert all(f["role"] == "candidate" and f["url"] for f in data["files"])


def test_failed_job_pushes_the_failure(client, staff, key, sent):
    add_receiver(client, staff)
    upl = upload(client, key).json()["id"]
    job_id = create(client, key, [upl]).json()["id"]
    run_worker(client, job_id, status="failed")
    data = json.loads(sent[0]["body"])["data"]
    assert data["status"] == "failed" and data["files"] == []
    assert data["error"]["code"] == "worker_failed"


def test_receiver_secret_shown_once_and_other_tenant_never_receives(client, staff, staff_b, key, sent):
    add_receiver(client, staff_b, url="https://other.example.test/hook")
    listed = client.get("/planner3d/receivers", headers=staff_b).json()["data"]
    assert "secret" not in listed[0]
    upl = upload(client, key).json()["id"]
    run_worker(client, create(client, key, [upl]).json()["id"])
    assert sent == []


def test_receiver_url_must_be_public_https(client, staff):
    res = client.post("/planner3d/receivers", json={"url": "http://crm.example.test/x", "events": ["model.candidates_ready"]}, headers=staff)
    assert res.status_code == 422


# ── unused uploads are removed after 24 hours ───────────────────────────────

def test_unused_uploads_are_purged_and_used_ones_kept(client, p3, key):
    from modules.planner3d.models import P3Upload
    from modules.planner3d.services import gateway_service

    used = upload(client, key).json()["id"]
    unused = upload(client, key).json()["id"]
    create(client, key, [used])
    db = p3()
    try:
        for row in db.query(P3Upload).all():
            row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
        assert gateway_service.purge_unused_uploads(db) == 1
        ids = {r.id for r in db.query(P3Upload).all()}
        assert ids == {used}
    finally:
        db.close()
