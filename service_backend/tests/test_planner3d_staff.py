"""PLANNER-3D-S3 red tests: the staff router (AC-S3-01, 02, 10, 11, 13).

Written before any implementation exists; they test the Phase 1 contract block
in documentation/plans/planner3d-s3-gpu-worker.md.
"""
from __future__ import annotations

import pytest

from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD  # noqa: F401
from tests.planner3d_helpers import (  # noqa: F401 - pytest fixtures
    DIMS,
    EXPORTS,
    NONE_EMAIL,
    SIX,
    VIEW_EMAIL,
    claim,
    err_code,
    file_count,
    finish,
    finished_model_job,
    glb_bytes,
    job_count,
    jpeg_bytes,
    login,
    p3,
    png_bytes,
    put_output,
    sha,
    staff,
    staff_b,
    submit_model,
    submit_render,
    webp_bytes,
    worker_token,
)


# ── AC-S3-01 submit a model job ─────────────────────────────────────────────

def test_ac01_submit_model_happy_returns_202_queued_job(client, staff, p3):
    res = submit_model(
        client,
        staff,
        photos=[("a.png", png_bytes(), "image/png"), ("b.jpg", jpeg_bytes(), "image/jpeg"), ("c.webp", webp_bytes(), "image/webp")],
    )
    assert res.status_code == 202, res.text
    job = res.json()
    assert job["kind"] == "model" and job["status"] == "queued"
    assert job["params"] == {"dimensionsMm": {"length": 1200, "width": 600, "height": 800}}
    assert job["error"] is None and job["attempts"] == 0
    ins = [f for f in job["files"] if f["direction"] == "in"]
    assert [f["name"] for f in ins] == ["photo-1.png", "photo-2.jpg", "photo-3.webp"]
    assert all(f["role"] == "photo" and f["size"] > 0 and len(f["sha256"]) == 64 for f in ins)
    assert ins[0]["sha256"] == sha(png_bytes())


def test_ac01_fourth_photo_is_422_and_stores_nothing(client, staff, p3):
    photos = [(f"{i}.png", png_bytes(), "image/png") for i in range(4)]
    res = submit_model(client, staff, photos=photos)
    assert res.status_code == 422
    assert job_count(p3) == 0 and file_count(p3) == 0


def test_ac01_text_renamed_png_is_422_and_stores_nothing(client, staff, p3):
    res = submit_model(client, staff, photos=[("fake.png", b"this is not an image at all", "image/png")])
    assert res.status_code == 422
    assert job_count(p3) == 0 and file_count(p3) == 0


@pytest.mark.parametrize("missing", ["lengthMm", "widthMm", "heightMm"])
def test_ac01_missing_dimension_is_422_and_stores_nothing(client, staff, p3, missing):
    data = {k: v for k, v in DIMS.items() if k != missing}
    res = submit_model(client, staff, data=data)
    assert res.status_code == 422
    assert job_count(p3) == 0 and file_count(p3) == 0


@pytest.mark.parametrize("bad", ["0", "-5", "abc"])
def test_ac01_non_positive_dimension_is_422(client, staff, p3, bad):
    res = submit_model(client, staff, data={**DIMS, "lengthMm": bad})
    assert res.status_code == 422
    assert job_count(p3) == 0


def test_ac01_zero_photos_is_422(client, staff, p3):
    res = client.post("/planner3d/jobs/models", data=DIMS, headers=staff)
    assert res.status_code == 422
    assert job_count(p3) == 0


# ── render submit (PNG only) ────────────────────────────────────────────────

def test_ac12_submit_render_happy(client, staff, p3):
    res = submit_render(client, staff, prompt="sunny", seed=7)
    assert res.status_code == 202, res.text
    job = res.json()
    assert job["kind"] == "render" and job["status"] == "queued"
    assert job["params"] == {"prompt": "sunny", "seed": 7}
    ins = {f["name"]: f for f in job["files"] if f["direction"] == "in"}
    assert set(ins) == {"scene.png", "mask.png", "depth.png"}
    assert all(ins[n]["role"] == n for n in ins)


def test_ac12_submit_render_seed_is_optional(client, staff, p3):
    job = submit_render(client, staff).json()
    assert job["params"]["prompt"] == "a sunny room" and job["params"]["seed"] is None


def test_ac12_submit_render_jpeg_scene_is_422_and_stores_nothing(client, staff, p3):
    res = submit_render(client, staff, scene=jpeg_bytes())
    assert res.status_code == 422
    assert job_count(p3) == 0 and file_count(p3) == 0


def test_ac12_submit_render_prompt_over_300_chars_is_422(client, staff, p3):
    res = submit_render(client, staff, prompt="x" * 301)
    assert res.status_code == 422
    assert job_count(p3) == 0


# ── AC-S3-02 permissions ────────────────────────────────────────────────────

def test_ac02_submit_without_manage_is_403(client, p3):
    viewer = login(client, VIEW_EMAIL)
    assert submit_model(client, viewer).status_code == 403
    assert job_count(p3) == 0


def test_ac02_render_submit_without_manage_is_403(client, p3):
    viewer = login(client, VIEW_EMAIL)
    assert submit_render(client, viewer).status_code == 403


def test_ac02_viewer_can_list_and_read_detail_and_download(client, staff, p3):
    job = submit_model(client, staff).json()
    viewer = login(client, VIEW_EMAIL)
    assert client.get("/planner3d/jobs", headers=viewer).status_code == 200
    assert client.get(f"/planner3d/jobs/{job['id']}", headers=viewer).status_code == 200
    assert client.get(f"/planner3d/jobs/{job['id']}/files/photo-1.png", headers=viewer).status_code == 200


def test_ac02_no_view_permission_is_403_on_list_detail_download(client, staff, p3):
    job = submit_model(client, staff).json()
    nobody = login(client, NONE_EMAIL)
    assert client.get("/planner3d/jobs", headers=nobody).status_code == 403
    assert client.get(f"/planner3d/jobs/{job['id']}", headers=nobody).status_code == 403
    assert client.get(f"/planner3d/jobs/{job['id']}/files/photo-1.png", headers=nobody).status_code == 403


def test_ac02_viewer_cannot_approve_or_cancel(client, staff, p3):
    job_id, _ = finished_model_job(client, staff)
    viewer = login(client, VIEW_EMAIL)
    res = client.post(f"/planner3d/jobs/{job_id}/approve", json={"candidate": "candidate-1.glb"}, headers=viewer)
    assert res.status_code == 403
    queued = submit_model(client, staff).json()["id"]
    assert client.post(f"/planner3d/jobs/{queued}/cancel", headers=viewer).status_code == 403


def test_ac02_unauthenticated_is_401(client, p3):
    assert client.get("/planner3d/jobs").status_code == 401


# ── AC-S3-02 tenant isolation ───────────────────────────────────────────────

def test_ac02_tenant_b_list_is_empty_and_detail_download_are_404(client, staff, staff_b, p3):
    job = submit_model(client, staff).json()
    listed = client.get("/planner3d/jobs", headers=staff_b)
    assert listed.status_code == 200 and listed.json() == {"items": [], "total": 0}
    assert client.get(f"/planner3d/jobs/{job['id']}", headers=staff_b).status_code == 404
    assert client.get(f"/planner3d/jobs/{job['id']}/files/photo-1.png", headers=staff_b).status_code == 404


def test_ac02_tenant_b_cannot_approve_or_cancel_tenant_a_job(client, staff, staff_b, p3):
    job_id, _ = finished_model_job(client, staff)
    res = client.post(f"/planner3d/jobs/{job_id}/approve", json={"candidate": "candidate-1.glb"}, headers=staff_b)
    assert res.status_code == 404
    assert client.post(f"/planner3d/jobs/{job_id}/cancel", headers=staff_b).status_code == 404
    # control: tenant A is untouched and can still approve
    ok = client.post(f"/planner3d/jobs/{job_id}/approve", json={"candidate": "candidate-1.glb"}, headers=staff)
    assert ok.status_code == 202


def test_ac02_list_is_newest_first_with_filters(client, staff, p3):
    first = submit_model(client, staff).json()["id"]
    second = submit_render(client, staff).json()["id"]
    from datetime import datetime, timedelta, timezone

    from tests.planner3d_helpers import age_job

    now = datetime.now(timezone.utc)
    age_job(p3, first, created_at=now - timedelta(minutes=5))
    age_job(p3, second, created_at=now)
    body = client.get("/planner3d/jobs", headers=staff).json()
    assert body["total"] == 2 and [j["id"] for j in body["items"]] == [second, first]
    only = client.get("/planner3d/jobs", params={"kind": "model"}, headers=staff).json()
    assert [j["id"] for j in only["items"]] == [first]
    none = client.get("/planner3d/jobs", params={"status": "succeeded"}, headers=staff).json()
    assert none["total"] == 0


def test_ac02_download_returns_bytes_with_stored_mime(client, staff, p3):
    job = submit_model(client, staff, photos=[("x.jpg", jpeg_bytes(), "image/jpeg")]).json()
    res = client.get(f"/planner3d/jobs/{job['id']}/files/photo-1.jpg", headers=staff)
    assert res.status_code == 200
    assert res.content == jpeg_bytes() and res.headers["content-type"].startswith("image/jpeg")
    assert client.get(f"/planner3d/jobs/{job['id']}/files/nope.png", headers=staff).status_code == 404


# ── AC-S3-10 approve ────────────────────────────────────────────────────────

def test_ac10_approve_queues_convert_job_with_model_glb_copy(client, staff, p3):
    job_id, cands = finished_model_job(client, staff)
    res = client.post(f"/planner3d/jobs/{job_id}/approve", json={"candidate": "candidate-2.glb"}, headers=staff)
    assert res.status_code == 202, res.text
    conv = res.json()
    assert conv["kind"] == "convert" and conv["status"] == "queued" and conv["sourceJobId"] == job_id
    ins = [f for f in conv["files"] if f["direction"] == "in"]
    assert [(f["name"], f["role"]) for f in ins] == [("model.glb", "model")]
    assert ins[0]["sha256"] == sha(cands["candidate-2.glb"])
    got = client.get(f"/planner3d/jobs/{conv['id']}/files/model.glb", headers=staff)
    assert got.status_code == 200 and got.content == cands["candidate-2.glb"]
    detail = client.get(f"/planner3d/jobs/{job_id}", headers=staff).json()
    assert detail["approvedCandidate"] == "candidate-2.glb"


def test_ac10_double_approve_is_409_and_queues_one_convert(client, staff, p3):
    job_id, _ = finished_model_job(client, staff)
    body = {"candidate": "candidate-1.glb"}
    assert client.post(f"/planner3d/jobs/{job_id}/approve", json=body, headers=staff).status_code == 202
    again = client.post(f"/planner3d/jobs/{job_id}/approve", json={"candidate": "candidate-3.glb"}, headers=staff)
    assert again.status_code == 409
    converts = client.get("/planner3d/jobs", params={"kind": "convert"}, headers=staff).json()
    assert converts["total"] == 1


def test_ac10_unknown_candidate_is_422_and_queues_nothing(client, staff, p3):
    job_id, _ = finished_model_job(client, staff, n_candidates=2)
    res = client.post(f"/planner3d/jobs/{job_id}/approve", json={"candidate": "candidate-3.glb"}, headers=staff)
    assert res.status_code == 422
    assert client.get("/planner3d/jobs", params={"kind": "convert"}, headers=staff).json()["total"] == 0
    detail = client.get(f"/planner3d/jobs/{job_id}", headers=staff).json()
    assert detail["approvedCandidate"] is None


def test_ac10_approve_not_succeeded_model_job_is_409(client, staff, p3):
    queued = submit_model(client, staff).json()["id"]
    res = client.post(f"/planner3d/jobs/{queued}/approve", json={"candidate": "candidate-1.glb"}, headers=staff)
    assert res.status_code == 409
    render = submit_render(client, staff).json()["id"]
    res = client.post(f"/planner3d/jobs/{render}/approve", json={"candidate": "candidate-1.glb"}, headers=staff)
    assert res.status_code == 409


def test_ac10_approve_missing_body_field_is_422(client, staff, p3):
    job_id, _ = finished_model_job(client, staff)
    assert client.post(f"/planner3d/jobs/{job_id}/approve", json={}, headers=staff).status_code == 422


# ── AC-S3-11 finished convert job, downloads by name ────────────────────────

def test_ac11_finished_convert_job_serves_all_six_exports(client, staff, p3):
    job_id, _ = finished_model_job(client, staff)
    conv_id = client.post(
        f"/planner3d/jobs/{job_id}/approve", json={"candidate": "candidate-1.glb"}, headers=staff
    ).json()["id"]
    got = claim(client, ["convert"])
    assert got.status_code == 200 and got.json()["jobId"] == conv_id
    for name in SIX:
        res = put_output(client, conv_id, name, EXPORTS[name], role=name.split(".")[0] + "-" + name.split(".")[1])
        assert res.status_code == 201, (name, res.text)
    done = finish(client, conv_id)
    assert done.status_code == 200 and done.json()["status"] == "succeeded", done.text
    outs = {f["name"] for f in done.json()["files"] if f["direction"] == "out"}
    assert outs == set(SIX)
    for name in SIX:
        res = client.get(f"/planner3d/jobs/{conv_id}/files/{name}", headers=staff)
        assert res.status_code == 200 and res.content == EXPORTS[name], name


# ── AC-S3-13 cancel ─────────────────────────────────────────────────────────

def test_ac13_cancel_queued_job_and_it_is_never_claimed(client, staff, p3):
    job_id = submit_model(client, staff).json()["id"]
    res = client.post(f"/planner3d/jobs/{job_id}/cancel", headers=staff)
    assert res.status_code == 200 and res.json()["status"] == "cancelled"
    assert claim(client).status_code == 204


def test_ac13_cancel_finished_job_is_409(client, staff, p3):
    job_id, _ = finished_model_job(client, staff)
    assert client.post(f"/planner3d/jobs/{job_id}/cancel", headers=staff).status_code == 409


def test_ac13_cancel_running_job_then_heartbeat_is_409_cancelled(client, staff, p3):
    from tests.planner3d_helpers import worker_headers

    job_id = submit_model(client, staff).json()["id"]
    assert claim(client).status_code == 200
    hb = client.post(f"/planner3d/worker/jobs/{job_id}/heartbeat", json={"progress": 10}, headers=worker_headers())
    assert hb.status_code == 200  # control: heartbeat works before the cancel
    assert client.post(f"/planner3d/jobs/{job_id}/cancel", headers=staff).json()["status"] == "cancelled"
    hb = client.post(f"/planner3d/worker/jobs/{job_id}/heartbeat", json={"progress": 20}, headers=worker_headers())
    assert hb.status_code == 409 and err_code(hb) == "cancelled"
