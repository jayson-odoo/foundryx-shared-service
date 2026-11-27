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


def _coloured(rgba, metallic=0.0, mesh=None):
    m = mesh if mesh is not None else _box()
    m.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(baseColorFactor=rgba, metallicFactor=metallic))
    return m


def _object_pixels(png):
    a = _arr(png).reshape(-1, 3).astype(int)
    return a[(a != 255).any(axis=1)]


def test_a_red_material_renders_red_dominant_pixels():
    px = _object_pixels(render_views(_coloured([255, 0, 0, 255]))["front"])
    interior = px[px[:, 0] > 120]
    assert len(interior) > 1000
    assert (interior[:, 0] > interior[:, 1] * 2).all() and (interior[:, 0] > interior[:, 2] * 2).all()


def test_default_material_stays_grey():
    px = _object_pixels(render_views(_box())["front"])
    assert (abs(px[:, 0] - px[:, 1]) < 3).all() and (abs(px[:, 1] - px[:, 2]) < 3).all()


def test_a_metallic_part_has_a_brighter_highlight_than_a_dielectric_one():
    grey = [60, 60, 60, 255]
    dielectric = _object_pixels(render_views(_coloured(grey, 0.0, trimesh.creation.icosphere(subdivisions=3)))["three_quarter"])
    metal = _object_pixels(render_views(_coloured(grey, 1.0, trimesh.creation.icosphere(subdivisions=3)))["three_quarter"])
    assert metal.max() > dielectric.max()
    assert metal.std() > dielectric.std()  # a reflection gradient, not a flat tone


def test_a_scene_with_two_materials_shows_both_colours():
    red = _coloured([255, 0, 0, 255], 0.0, trimesh.creation.box(extents=(0.5, 0.5, 0.5)))
    blue = _coloured([0, 0, 255, 255], 0.0, trimesh.creation.box(extents=(0.5, 0.5, 0.5)))
    blue.apply_translation((1.0, 0, 0))
    scene = trimesh.Scene()
    scene.add_geometry(red, node_name="a", geom_name="a")
    scene.add_geometry(blue, node_name="b", geom_name="b")
    px = _object_pixels(render_views(scene)["front"])
    assert ((px[:, 0] > 150) & (px[:, 2] < 60)).sum() > 500
    assert ((px[:, 2] > 150) & (px[:, 0] < 60)).sum() > 500


def test_explicit_materials_win_and_coloured_render_is_deterministic():
    scene = trimesh.Scene()
    scene.add_geometry(_box(), node_name="p", geom_name="p")
    a = render_views(scene, materials={"p": ((0.0, 1.0, 0.0), 0.0)})
    assert a == render_views(scene, materials={"p": ((0.0, 1.0, 0.0), 0.0)})
    px = _object_pixels(a["front"])
    assert ((px[:, 1] > 120) & (px[:, 0] < 60)).sum() > 500


def test_a_white_part_gets_a_dark_silhouette_edge():
    px = _object_pixels(render_views(_coloured([255, 255, 255, 255]))["front"])
    assert px.min() < 140


def test_glb_materials_reads_factors_from_the_json_chunk_only():
    from planner3d_worker.raster import glb_materials

    scene = trimesh.Scene()
    scene.add_geometry(_coloured([255, 0, 0, 255], 0.0), node_name="seat", geom_name="seat")
    tap = _coloured([200, 200, 200, 255], 1.0, trimesh.creation.box())
    scene.add_geometry(tap, node_name="tap", geom_name="tap")
    mats = glb_materials(scene.export(file_type="glb"))
    assert mats["seat"][0][0] == 1.0 and mats["seat"][1] == 0.0
    assert mats["tap"][1] == 1.0
    assert glb_materials(b"not a glb") == {}


def test_engine_render_uses_the_glb_colours_when_materials_are_skipped():
    import io as _io

    from planner3d_worker.raster import glb_materials

    scene = trimesh.Scene()
    scene.add_geometry(_coloured([255, 0, 0, 255], 0.0), node_name="seat", geom_name="seat")
    data = scene.export(file_type="glb")
    loaded = trimesh.load(_io.BytesIO(data), file_type="glb", force="scene", skip_materials=True)
    px = _object_pixels(render_views(loaded, materials=glb_materials(data))["front"])
    assert ((px[:, 0] > 120) & (px[:, 1] < 60)).sum() > 500


def test_a_white_part_reads_white_under_the_studio_rig():
    for view in ("front", "side", "three_quarter"):
        a = _arr(render_views(_coloured([245, 245, 245, 255]))[view]).reshape(-1, 3).astype(int)
        px = a[(a != 255).any(axis=1)]
        lit = px[px.min(axis=1) >= 150]  # drops the dark outline pixels
        # faces turned away from the key light in the three-quarter view sit lower than the straight views
        assert lit.mean() >= (230 if view != "three_quarter" else 205), view
        assert lit.min() >= 170, view


def test_vertex_colours_win_over_a_material_that_has_no_colour():
    import io as _io

    import numpy as np

    from planner3d_worker.raster import glb_materials

    m = trimesh.creation.box(extents=(1.2, 0.75, 0.6))
    m.apply_translation((0, 0.375, 0))
    m.visual = trimesh.visual.ColorVisuals(m, vertex_colors=np.tile([10, 10, 10, 255], (len(m.vertices), 1)))
    scene = trimesh.Scene()
    scene.add_geometry(m, node_name="p", geom_name="p")
    data = scene.export(file_type="glb")
    loaded = trimesh.load(_io.BytesIO(data), file_type="glb", force="scene", skip_materials=True)
    px = _object_pixels(render_views(loaded, materials=glb_materials(data))["front"])
    assert (px.max(axis=1) < 120).sum() > 1000


def test_linear_base_colour_is_encoded_to_srgb_for_display():
    # linear 0.214 is sRGB 0.5 (value 128): a mid grey factor must not render dark
    px = _object_pixels(render_views(_coloured([55, 55, 55, 255]))["front"])  # 55/255 = 0.2157 linear
    assert 110 <= px.max() <= 140
