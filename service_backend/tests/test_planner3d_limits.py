"""PLANNER-3D-S3 follow-up red tests: input size limits, download headers, stored error length."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from tests.planner3d_helpers import (  # noqa: F401 - pytest fixtures
    claim,
    finish,
    finished_model_job,
    job_count,
    file_count,
    p3,
    put_output,
    scene_mask_arrays,
    array_png,
    staff,
    submit_model,
    submit_render,
    worker_token,
)


def _wide_png(w=5000, h=10) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 0, 0)).save(buf, "PNG")
    return buf.getvalue()


def _tall_png(w=10, h=5000) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 0, 0)).save(buf, "PNG")
    return buf.getvalue()


@pytest.mark.parametrize("field", ["scene"])
@pytest.mark.parametrize("big", [_wide_png, _tall_png])
def test_render_inputs_above_4096_px_per_side_are_refused(client, staff, p3, field, big):
    # field is kept in the id: scene and mask are both oversize here, as the images must match in size
    before = job_count(p3)
    files_before = file_count(p3)
    png = big()
    trio = {"scene": png, "mask": png, "depth": png}
    res = submit_render(client, staff, **trio)
    assert res.status_code == 422, res.text
    assert job_count(p3) == before
    assert file_count(p3) == files_before


def test_render_inputs_at_4096_px_are_accepted_control(client, staff, p3):
    png = _wide_png(4096, 10)
    res = submit_render(client, staff, scene=png, mask=png, depth=png)
    assert res.status_code == 202, res.text
    small = submit_render(client, staff)
    assert small.status_code == 202, small.text


@pytest.mark.parametrize("big", [_wide_png, _tall_png])
def test_worker_render_output_above_4096_px_per_side_is_refused(client, staff, p3, big):
    job_id = submit_render(client, staff).json()["id"]
    assert claim(client, ["render"]).status_code == 200
    before = file_count(p3, job_id)
    res = put_output(client, job_id, "render.png", big(), role="render")
    assert res.status_code == 422, res.text
    assert file_count(p3, job_id) == before


def test_staff_file_download_is_sent_as_attachment_with_stored_name(client, staff, p3):
    job_id, cands = finished_model_job(client, staff)
    res = client.get(f"/planner3d/jobs/{job_id}/files/candidate-1.glb", headers=staff)
    assert res.status_code == 200
    assert res.headers["content-disposition"] == 'attachment; filename="candidate-1.glb"'


def test_finish_failed_error_message_is_stored_at_most_200_chars(client, staff, p3):
    job_id = submit_model(client, staff).json()["id"]
    assert claim(client, ["model"]).status_code == 200
    res = finish(client, job_id, status="failed", error={"code": "worker_failed", "message": "x" * 500})
    assert res.status_code == 200, res.text
    detail = client.get(f"/planner3d/jobs/{job_id}", headers=staff).json()
    assert detail["error"]["code"] == "worker_failed"
    assert 0 < len(detail["error"]["message"]) <= 200
