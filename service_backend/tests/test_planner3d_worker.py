"""PLANNER-3D-S3 red tests: the worker pull API (AC-S3-03..09, 12, 13).

Written before any implementation exists; contract = Phase 1 block in
documentation/plans/planner3d-s3-gpu-worker.md.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tests.planner3d_helpers import (  # noqa: F401 - pytest fixtures
    OTHER_WORKER,
    WORKER,
    WORKER_TOKEN,
    age_job,
    array_png,
    claim,
    err_code,
    file_count,
    finish,
    finished_model_job,
    glb_bytes,
    jpeg_bytes,
    p3,
    png_bytes,
    put_output,
    scene_mask_arrays,
    sha,
    staff,
    staff_b,
    submit_model,
    submit_render,
    worker_headers,
    worker_token,
)


# ── AC-S3-03 worker auth ────────────────────────────────────────────────────

def test_ac03_claim_without_token_is_401_and_claims_nothing(client, staff, p3):
    job_id = submit_model(client, staff).json()["id"]
    res = client.post("/planner3d/worker/claim", json={"kinds": ["model"]}, headers={"X-Planner3d-Worker": WORKER})
    assert res.status_code == 401
    assert client.get(f"/planner3d/jobs/{job_id}", headers=staff).json()["status"] == "queued"


def test_ac03_claim_with_wrong_token_is_401_and_claims_nothing(client, staff, p3):
    job_id = submit_model(client, staff).json()["id"]
    res = client.post(
        "/planner3d/worker/claim", json={"kinds": ["model"]}, headers=worker_headers(token="not-the-token")
    )
    assert res.status_code == 401
    assert client.get(f"/planner3d/jobs/{job_id}", headers=staff).json()["status"] == "queued"


def test_ac03_unset_server_hash_is_401_even_with_a_token(client, staff, p3, monkeypatch):
    from app.config import settings

    job_id = submit_model(client, staff).json()["id"]
    for unset in ("", None):
        monkeypatch.setattr(settings, "planner3d_worker_token_sha256", unset, raising=False)
        res = claim(client)
        assert res.status_code == 401, unset
    assert client.get(f"/planner3d/jobs/{job_id}", headers=staff).json()["status"] == "queued"


def test_ac03_correct_token_is_accepted_control(client, staff, p3):
    submit_model(client, staff)
    assert claim(client).status_code == 200


def test_ac03_every_worker_route_requires_the_token(client, staff, p3):
    job_id = submit_model(client, staff).json()["id"]
    assert claim(client).status_code == 200
    bad = {"Authorization": "Bearer nope", "X-Planner3d-Worker": WORKER}
    base = f"/planner3d/worker/jobs/{job_id}"
    assert client.get(f"{base}/inputs/photo-1.png", headers=bad).status_code == 401
    assert client.post(f"{base}/heartbeat", json={"progress": 1}, headers=bad).status_code == 401
    assert client.put(f"{base}/outputs/candidate-1.glb", content=glb_bytes(), headers=bad).status_code == 401
    assert client.post(f"{base}/finish", json={"status": "failed"}, headers=bad).status_code == 401


# ── AC-S3-04 / 05 claim ─────────────────────────────────────────────────────

def test_ac04_empty_queue_is_204(client, p3):
    res = claim(client)
    assert res.status_code == 204 and res.content == b""


def test_ac04_claim_returns_contract_shape_and_marks_running(client, staff, p3):
    job_id = submit_model(client, staff).json()["id"]
    res = claim(client)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["jobId"] == job_id and body["kind"] == "model"
    assert body["params"] == {"dimensionsMm": {"length": 1200, "width": 600, "height": 800}}
    assert body["inputs"] == [
        {"role": "photo", "name": "photo-1.png", "mime": "image/png", "size": len(png_bytes()), "sha256": sha(png_bytes())}
    ]
    detail = client.get(f"/planner3d/jobs/{job_id}", headers=staff).json()
    assert detail["status"] == "running" and detail["startedAt"] is not None


def test_ac04_ac05_oldest_queued_job_is_handed_out_first(client, staff, p3):
    a = submit_model(client, staff).json()["id"]
    b = submit_model(client, staff).json()["id"]
    c = submit_model(client, staff).json()["id"]
    now = datetime.now(timezone.utc)
    # insertion order is a, b, c; age says b (oldest), a, c
    age_job(p3, b, created_at=now - timedelta(hours=3))
    age_job(p3, a, created_at=now - timedelta(hours=2))
    age_job(p3, c, created_at=now - timedelta(hours=1))
    got = [claim(client).json()["jobId"] for _ in range(3)]
    assert got == [b, a, c]
    assert claim(client).status_code == 204


def test_ac04_two_claims_never_get_the_same_job(client, staff, p3):
    only = submit_model(client, staff).json()["id"]
    first = claim(client, name=WORKER)
    second = claim(client, name=OTHER_WORKER)
    assert first.status_code == 200 and first.json()["jobId"] == only
    assert second.status_code == 204
    other = submit_model(client, staff).json()["id"]
    third = claim(client, name=OTHER_WORKER)
    assert third.json()["jobId"] == other != only


def test_ac04_claim_respects_requested_kinds(client, staff, p3):
    model_id = submit_model(client, staff).json()["id"]
    render_id = submit_render(client, staff).json()["id"]
    assert claim(client, ["render"]).json()["jobId"] == render_id
    assert claim(client, ["render"]).status_code == 204
    assert claim(client, ["model"]).json()["jobId"] == model_id


def test_ac04_claim_stamps_worker_name(client, staff, p3):
    job_id = submit_model(client, staff).json()["id"]
    claim(client, name=OTHER_WORKER)
    # only the stamped worker can read the inputs
    assert client.get(f"/planner3d/worker/jobs/{job_id}/inputs/photo-1.png", headers=worker_headers(OTHER_WORKER)).status_code == 200
    assert client.get(f"/planner3d/worker/jobs/{job_id}/inputs/photo-1.png", headers=worker_headers(WORKER)).status_code == 404


def test_ac05_jobs_queued_while_no_worker_polls_are_served_later_in_order(client, staff, p3):
    ids = [submit_model(client, staff).json()["id"] for _ in range(2)]
    now = datetime.now(timezone.utc)
    age_job(p3, ids[0], created_at=now - timedelta(days=1))
    age_job(p3, ids[1], created_at=now - timedelta(hours=1))
    for i in ids:
        assert client.get(f"/planner3d/jobs/{i}", headers=staff).json()["status"] == "queued"
    assert [claim(client).json()["jobId"] for _ in ids] == ids


# ── AC-S3-06 input download ─────────────────────────────────────────────────

def test_ac06_held_job_input_downloads_bytes(client, staff, p3):
    job_id = submit_model(client, staff).json()["id"]
    claim(client)
    res = client.get(f"/planner3d/worker/jobs/{job_id}/inputs/photo-1.png", headers=worker_headers())
    assert res.status_code == 200 and res.content == png_bytes()
    assert client.get(f"/planner3d/worker/jobs/{job_id}/inputs/missing.png", headers=worker_headers()).status_code == 404


def test_ac06_queued_unclaimed_job_input_is_404(client, staff, p3):
    job_id = submit_model(client, staff).json()["id"]
    res = client.get(f"/planner3d/worker/jobs/{job_id}/inputs/photo-1.png", headers=worker_headers())
    assert res.status_code == 404


def test_ac06_other_workers_job_input_is_404(client, staff, p3):
    job_id = submit_model(client, staff).json()["id"]
    claim(client, name=WORKER)
    res = client.get(f"/planner3d/worker/jobs/{job_id}/inputs/photo-1.png", headers=worker_headers(OTHER_WORKER))
    assert res.status_code == 404


def test_ac06_finished_job_input_is_404(client, staff, p3):
    job_id, _ = finished_model_job(client, staff)
    res = client.get(f"/planner3d/worker/jobs/{job_id}/inputs/photo-1.png", headers=worker_headers())
    assert res.status_code == 404


# ── AC-S3-07 outputs ────────────────────────────────────────────────────────

def _running_model(client, staff):
    job_id = submit_model(client, staff).json()["id"]
    assert claim(client, ["model"]).status_code == 200
    return job_id


def test_ac07_output_upload_stores_and_sha256_is_computed_by_ss(client, staff, p3):
    job_id = _running_model(client, staff)
    data = glb_bytes("one")
    res = client.put(
        f"/planner3d/worker/jobs/{job_id}/outputs/candidate-1.glb",
        params={"role": "candidate"},
        content=data,
        headers={**worker_headers(), "X-Sha256": "0" * 64},  # a client-claimed hash must be ignored
    )
    assert res.status_code == 201, res.text
    assert res.json() == {"name": "candidate-1.glb", "size": len(data), "sha256": sha(data)}
    files = client.get(f"/planner3d/jobs/{job_id}", headers=staff).json()["files"]
    out = [f for f in files if f["direction"] == "out"]
    assert out == [{"direction": "out", "role": "candidate", "name": "candidate-1.glb",
                    "mime": out[0]["mime"], "size": len(data), "sha256": sha(data)}]
    got = client.get(f"/planner3d/jobs/{job_id}/files/candidate-1.glb", headers=staff)
    assert got.status_code == 200 and got.content == data


def test_ac07_non_glb_bytes_under_a_glb_name_is_422_and_stores_nothing(client, staff, p3):
    job_id = _running_model(client, staff)
    before = file_count(p3, job_id)
    for body in (png_bytes(), b"just some text", b""):
        res = put_output(client, job_id, "candidate-1.glb", body, role="candidate")
        assert res.status_code == 422, body[:8]
    assert file_count(p3, job_id) == before
    assert client.get(f"/planner3d/jobs/{job_id}/files/candidate-1.glb", headers=staff).status_code == 404


def test_ac07_name_not_allowed_for_the_kind_is_422(client, staff, p3):
    job_id = _running_model(client, staff)
    before = file_count(p3, job_id)
    for name in ("candidate-4.glb", "candidate-0.glb", "render.png", "model.glb", "evil.glb"):
        res = put_output(client, job_id, name, glb_bytes(), role="candidate")
        assert res.status_code in (404, 422), name
    assert file_count(p3, job_id) == before


def test_ac07_candidate_json_is_accepted_and_bad_json_is_422(client, staff, p3):
    job_id = _running_model(client, staff)
    assert put_output(client, job_id, "candidate-1.json", b'{"bbox_mm": [1200, 600, 800]}', role="report").status_code == 201
    assert put_output(client, job_id, "candidate-2.json", b"\x89PNG\r\n\x1a\n", role="report").status_code == 422


def test_ac07_upload_to_a_job_this_worker_does_not_hold_is_404(client, staff, p3):
    job_id = _running_model(client, staff)
    res = put_output(client, job_id, "candidate-1.glb", glb_bytes(), role="candidate", worker=OTHER_WORKER)
    assert res.status_code == 404
    assert file_count(p3, job_id) == 1  # only the photo input


def test_ac07_oversize_json_is_refused_and_stores_nothing(client, staff, p3):
    job_id = _running_model(client, staff)
    big = b'{"x": "' + b"a" * (1024 * 1024 + 10) + b'"}'
    res = put_output(client, job_id, "candidate-1.json", big, role="report")
    assert res.status_code in (413, 422)
    assert file_count(p3, job_id) == 1


# ── AC-S3-08 heartbeat + lease ──────────────────────────────────────────────

def test_ac08_heartbeat_updates_progress(client, staff, p3):
    job_id = _running_model(client, staff)
    res = client.post(f"/planner3d/worker/jobs/{job_id}/heartbeat", json={"progress": 55}, headers=worker_headers())
    assert res.status_code == 200
    assert client.get(f"/planner3d/jobs/{job_id}", headers=staff).json()["progress"] == 55


def test_ac08_stale_running_job_is_requeued_on_next_claim_with_attempt_plus_one(client, staff, p3):
    job_id = _running_model(client, staff)
    age_job(p3, job_id, heartbeat_minutes_ago=11)
    res = claim(client, name=OTHER_WORKER)
    assert res.status_code == 200 and res.json()["jobId"] == job_id
    detail = client.get(f"/planner3d/jobs/{job_id}", headers=staff).json()
    assert detail["attempts"] == 1 and detail["status"] == "running"
    # the first worker lost the lease: it no longer reads inputs
    assert client.get(f"/planner3d/worker/jobs/{job_id}/inputs/photo-1.png", headers=worker_headers(WORKER)).status_code == 404


def test_ac08_fresh_lease_is_not_requeued_control(client, staff, p3):
    job_id = _running_model(client, staff)
    age_job(p3, job_id, heartbeat_minutes_ago=5)
    assert claim(client, name=OTHER_WORKER).status_code == 204
    detail = client.get(f"/planner3d/jobs/{job_id}", headers=staff).json()
    assert detail["attempts"] == 0 and detail["status"] == "running"


def test_ac08_third_lost_attempt_fails_with_worker_lost(client, staff, p3):
    job_id = _running_model(client, staff)
    age_job(p3, job_id, heartbeat_minutes_ago=11, attempts=2)
    assert claim(client, name=OTHER_WORKER).status_code == 204
    detail = client.get(f"/planner3d/jobs/{job_id}", headers=staff).json()
    assert detail["status"] == "failed" and detail["attempts"] == 3
    assert detail["error"]["code"] == "worker_lost"


# ── AC-S3-09 finish ─────────────────────────────────────────────────────────

def test_ac09_model_finish_with_two_candidates_succeeds_and_stores_metrics(client, staff, p3):
    job_id = _running_model(client, staff)
    for i in (1, 2):
        assert put_output(client, job_id, f"candidate-{i}.glb", glb_bytes(str(i)), role="candidate").status_code == 201
    res = finish(client, job_id, gpuSeconds=42.5, peakRssMb=6123)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "succeeded" and body["gpuSeconds"] == 42.5 and body["peakRssMb"] == 6123
    assert body["finishedAt"] is not None
    detail = client.get(f"/planner3d/jobs/{job_id}", headers=staff).json()
    assert detail["gpuSeconds"] == 42.5 and detail["peakRssMb"] == 6123


def test_ac09_model_finish_with_one_or_zero_candidates_does_not_succeed(client, staff, p3):
    for n in (0, 1):
        job_id = _running_model(client, staff)
        for i in range(1, n + 1):
            put_output(client, job_id, f"candidate-{i}.glb", glb_bytes(), role="candidate")
        res = finish(client, job_id)
        if res.status_code == 200:
            assert res.json()["status"] == "failed"
        else:
            assert res.status_code == 422
        assert client.get(f"/planner3d/jobs/{job_id}", headers=staff).json()["status"] != "succeeded"


def test_ac09_finish_failed_carries_error_and_metrics(client, staff, p3):
    job_id = _running_model(client, staff)
    res = finish(client, job_id, status="failed", error={"code": "memory_cap", "message": "child over 8 GB"}, gpuSeconds=3, peakRssMb=8200)
    assert res.status_code == 200
    detail = client.get(f"/planner3d/jobs/{job_id}", headers=staff).json()
    assert detail["status"] == "failed"
    assert detail["error"] == {"code": "memory_cap", "message": "child over 8 GB"}
    assert detail["peakRssMb"] == 8200 and detail["gpuSeconds"] == 3


def test_ac09_finish_by_a_worker_that_does_not_hold_the_job_is_404(client, staff, p3):
    job_id = _running_model(client, staff)
    assert finish(client, job_id, status="failed", worker=OTHER_WORKER).status_code == 404
    assert client.get(f"/planner3d/jobs/{job_id}", headers=staff).json()["status"] == "running"


def test_ac09_finish_bad_status_is_422(client, staff, p3):
    job_id = _running_model(client, staff)
    assert finish(client, job_id, status="banana").status_code == 422


# ── AC-S3-12 render paste-back ──────────────────────────────────────────────

def _running_render(client, staff):
    job_id = submit_render(client, staff).json()["id"]
    assert claim(client, ["render"]).status_code == 200
    return job_id


def _render_png(change_product: bool, change_background: bool = True) -> bytes:
    scene, _ = scene_mask_arrays()
    out = scene.copy()
    if change_background:
        out.paste((30, 30, 30), (4, 0, 8, 8))  # right half is background (mask red == 0)
    if change_product:
        out.putpixel((0, 0), (121, 120, 120))  # one product pixel, one level
    return array_png(out)


def test_ac12_render_with_untouched_product_succeeds(client, staff, p3):
    job_id = _running_render(client, staff)
    assert put_output(client, job_id, "render.png", _render_png(False), role="render").status_code == 201
    assert put_output(client, job_id, "diff.json", b'{"changed_pixels": 0}', role="diff").status_code == 201
    res = finish(client, job_id)
    assert res.status_code == 200 and res.json()["status"] == "succeeded", res.text
    got = client.get(f"/planner3d/jobs/{job_id}/files/render.png", headers=staff)
    assert got.status_code == 200 and got.content == _render_png(False)


def test_ac12_render_that_changes_a_product_pixel_fails_product_changed(client, staff, p3):
    job_id = _running_render(client, staff)
    put_output(client, job_id, "render.png", _render_png(True), role="render")
    # the worker claims all is fine; SS must not believe it
    put_output(client, job_id, "diff.json", b'{"changed_pixels": 0}', role="diff")
    res = finish(client, job_id, status="succeeded")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "failed" and body["error"]["code"] == "product_changed"
    assert client.get(f"/planner3d/jobs/{job_id}", headers=staff).json()["error"]["code"] == "product_changed"


def test_ac12_render_success_without_render_png_does_not_succeed(client, staff, p3):
    job_id = _running_render(client, staff)
    res = finish(client, job_id)
    if res.status_code == 200:
        assert res.json()["status"] == "failed"
    else:
        assert res.status_code == 422


def test_ac12_jpeg_render_output_is_refused(client, staff, p3):
    job_id = _running_render(client, staff)
    res = put_output(client, job_id, "render.png", jpeg_bytes(), role="render")
    assert res.status_code == 422
    assert file_count(p3, job_id) == 3  # only the three inputs


# ── AC-S3-13 cancel seen by the worker ──────────────────────────────────────

def test_ac13_upload_after_cancel_is_refused_and_finish_does_not_revive(client, staff, p3):
    job_id = _running_model(client, staff)
    client.post(f"/planner3d/jobs/{job_id}/cancel", headers=staff)
    res = put_output(client, job_id, "candidate-1.glb", glb_bytes(), role="candidate")
    assert res.status_code in (404, 409)
    finish(client, job_id)
    assert client.get(f"/planner3d/jobs/{job_id}", headers=staff).json()["status"] == "cancelled"
