"""claude-procedural red tests: software rasteriser (D7)."""
import io

import numpy as np
import trimesh
from PIL import Image

from planner3d_worker.raster import render_views

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _box():
    m = trimesh.creation.box(extents=(1.2, 0.75, 0.6))
    m.apply_translation((0.0, 0.375, 0.0))
    return m


def _arr(png):
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB"))


def test_three_views_are_png_of_the_requested_size():
    views = render_views(_box())
    assert set(views) == {"front", "side", "three_quarter"}
    for png in views.values():
        assert png.startswith(PNG_MAGIC)
        assert Image.open(io.BytesIO(png)).size == (512, 512)


def test_size_parameter_is_honoured():
    for png in render_views(_box(), size=128).values():
        assert Image.open(io.BytesIO(png)).size == (128, 128)


def test_output_is_deterministic():
    assert render_views(_box()) == render_views(_box())


def test_views_differ_from_each_other():
    v = render_views(_box())
    assert len({v["front"], v["side"], v["three_quarter"]}) == 3


def test_the_box_is_drawn_not_a_blank_image():
    for png in render_views(_box()).values():
        a = _arr(png)
        assert len(np.unique(a.reshape(-1, 3), axis=0)) >= 2


def test_empty_mesh_is_handled_without_raising():
    views = render_views(trimesh.Trimesh())
    assert set(views) == {"front", "side", "three_quarter"}
    assert all(png.startswith(PNG_MAGIC) for png in views.values())
