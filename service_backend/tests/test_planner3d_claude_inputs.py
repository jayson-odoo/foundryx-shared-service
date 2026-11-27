"""claude-procedural engine red tests: optional drawing, category and product code on
POST /planner3d/jobs/models (plan planner3d-claude-procedural-engine.md, D9)."""
from __future__ import annotations

from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD  # noqa: F401
from tests.planner3d_helpers import (  # noqa: F401 - pytest fixtures
    DIMS,
    err_code,
    file_count,
    job_count,
    jpeg_bytes,
    p3,
    png_bytes,
    staff,
    webp_bytes,
    worker_token,
)

BASE = {"dimensionsMm": {"length": 1200, "width": 600, "height": 800}}


def _submit(client, staff, data=None, drawing=None):
    files = [("photos", ("a.png", png_bytes(), "image/png"))]
    if drawing is not None:
        files.append(("drawing", drawing))
    return client.post("/planner3d/jobs/models", files=files, data={**DIMS, **(data or {})}, headers=staff)


def test_drawing_category_and_product_code_are_stored(client, staff, p3):
    res = _submit(
        client, staff,
        data={"categoryCode": "SRTWC", "categoryName": "Water closets", "productCode": "SRTWC286-SH"},
        drawing=("plan.png", png_bytes(), "image/png"),
    )
    assert res.status_code == 202, res.text
    job = res.json()
    assert job["params"] == {
        **BASE,
        "category": {"code": "SRTWC", "name": "Water closets"},
        "productCode": "SRTWC286-SH",
    }
    ins = {f["name"]: f for f in job["files"] if f["direction"] == "in"}
    assert set(ins) == {"photo-1.png", "drawing.png"}
    assert ins["drawing.png"]["role"] == "drawing"


def test_drawing_extension_follows_sniffed_type(client, staff, p3):
    res = _submit(client, staff, drawing=("d.bin", jpeg_bytes(), "application/octet-stream"))
    assert res.status_code == 202, res.text
    names = [f["name"] for f in res.json()["files"] if f["role"] == "drawing"]
    assert names == ["drawing.jpg"]
    res = _submit(client, staff, drawing=("d.bin", webp_bytes(), "application/octet-stream"))
    assert [f["name"] for f in res.json()["files"] if f["role"] == "drawing"] == ["drawing.webp"]


def test_fake_drawing_is_422_drawing_type_and_stores_nothing(client, staff, p3):
    jobs, files = job_count(p3), file_count(p3)
    res = _submit(client, staff, drawing=("plan.png", b"this is not an image at all", "image/png"))
    assert res.status_code == 422, res.text
    assert err_code(res) == "drawing_type"
    assert job_count(p3) == jobs and file_count(p3) == files


def test_oversize_drawing_is_413_and_stores_nothing(client, staff, p3):
    jobs, files = job_count(p3), file_count(p3)
    big = png_bytes() + b"\0" * (20 * 1024 * 1024 + 1)
    res = _submit(client, staff, drawing=("plan.png", big, "image/png"))
    assert res.status_code == 413, res.text
    assert job_count(p3) == jobs and file_count(p3) == files


def test_without_the_new_fields_params_are_unchanged(client, staff, p3):
    res = _submit(client, staff)
    assert res.status_code == 202, res.text
    job = res.json()
    assert job["params"] == BASE
    assert [f["role"] for f in job["files"] if f["direction"] == "in"] == ["photo"]


def test_category_name_without_code_adds_no_category(client, staff, p3):
    res = _submit(client, staff, data={"categoryName": "Water closets"})
    assert res.status_code == 202, res.text
    assert "category" not in res.json()["params"]


def test_product_code_alone_is_stored(client, staff, p3):
    res = _submit(client, staff, data={"productCode": "SRTWT5903"})
    assert res.status_code == 202, res.text
    assert res.json()["params"] == {**BASE, "productCode": "SRTWT5903"}


def test_field_length_limits_are_422(client, staff, p3):
    assert _submit(client, staff, data={"categoryCode": "x" * 65}).status_code == 422
    assert _submit(client, staff, data={"categoryCode": "A", "categoryName": "n" * 129}).status_code == 422
    assert _submit(client, staff, data={"productCode": "p" * 65}).status_code == 422
