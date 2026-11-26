"""Post-processing port of the proof's image_to_3d.py (no torch needed)."""
import numpy as np
import pytest
import trimesh

from planner3d_worker.image_to_3d import scale_to_catalogue, upright_and_forward

W, D, H = 600.0, 400.0, 800.0


def _raw_box(yaw_deg=0.0):
    # TripoSR frame: x front (depth), y left (width), z up (height).
    mesh = trimesh.creation.box(extents=(D / 1000, W / 1000, H / 1000))
    mesh.apply_transform(trimesh.transformations.rotation_matrix(np.radians(yaw_deg), [0, 0, 1]))
    return mesh


def test_ac_s3_23_upright_makes_y_up_with_catalogue_axes():
    mesh, report = upright_and_forward(_raw_box(), W, D, H, None, None)
    ext = mesh.extents
    assert ext[0] == pytest.approx(W / 1000, abs=1e-3)
    assert ext[1] == pytest.approx(H / 1000, abs=1e-3)
    assert ext[2] == pytest.approx(D / 1000, abs=1e-3)
    assert "method" in report and "tilt_deg" in report and "yaw_deg" in report


def test_ac_s3_23_upright_undoes_photographer_yaw():
    mesh, _ = upright_and_forward(_raw_box(yaw_deg=30), W, D, H, None, None)
    ext = mesh.extents
    assert ext[0] == pytest.approx(W / 1000, abs=2e-3)
    assert ext[1] == pytest.approx(H / 1000, abs=2e-3)
    assert ext[2] == pytest.approx(D / 1000, abs=2e-3)


def test_ac_s3_23_manual_override_reports_manual():
    _, report = upright_and_forward(_raw_box(), W, D, H, 0.0, 90.0)
    assert report["method"] == "manual"
    assert report["yaw_deg"] == 90.0


def test_ac_s3_24_scale_to_catalogue_exact_dims_base_centre():
    mesh = trimesh.creation.box(extents=(2.0, 3.0, 1.0))
    mesh.apply_translation([5, 5, 5])
    out, report = scale_to_catalogue(mesh, W, D, H)
    lo, hi = out.bounds
    ext = hi - lo
    assert ext[0] == pytest.approx(W / 1000, abs=1e-3)
    assert ext[1] == pytest.approx(H / 1000, abs=1e-3)
    assert ext[2] == pytest.approx(D / 1000, abs=1e-3)
    assert lo[1] == pytest.approx(0.0, abs=1e-6)
    assert (lo[0] + hi[0]) / 2 == pytest.approx(0.0, abs=1e-6)
    assert (lo[2] + hi[2]) / 2 == pytest.approx(0.0, abs=1e-6)
    assert "max_stretch_pct" in report and "per_axis_stretch_w_h_d" in report


def test_ac_s3_24_pipeline_upright_then_scale():
    mesh, _ = upright_and_forward(_raw_box(yaw_deg=20), W, D, H, None, None)
    mesh, _ = scale_to_catalogue(mesh, W, D, H)
    lo, hi = mesh.bounds
    assert (hi - lo) == pytest.approx([W / 1000, H / 1000, D / 1000], abs=1e-3)
    assert lo[1] == pytest.approx(0.0, abs=1e-6)
