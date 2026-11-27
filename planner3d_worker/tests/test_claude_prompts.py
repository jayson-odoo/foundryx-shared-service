"""claude-procedural red tests: prompt builders and script extraction (D3, D7)."""
import base64
import io

import pytest
from PIL import Image

from planner3d_worker.claude.prompts import SYSTEM_PROMPT, extract_script, first_turn, refine_turn
from planner3d_worker.claude.routing import Profile

PRIMS = Profile(model="claude-sonnet-5-5", approach="primitives", max_versions=2, effort="medium")
SDF = Profile(model="claude-opus-5-5", approach="sdf", max_versions=3, effort="high")
DIMS = {"length": 1234, "width": 567, "height": 891}


def _png(path, colour):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), colour).save(buf, "PNG")
    path.write_bytes(buf.getvalue())
    return path


def _images(blocks):
    return [b for b in blocks if b["type"] == "image"]


def _text(blocks):
    return "\n".join(b["text"] for b in blocks if b["type"] == "text")


def test_extract_script_takes_the_last_python_block():
    text = "first\n```python\nprint(1)\n```\nthen\n```python\nimport trimesh\nx = 2\n```\nbye"
    assert extract_script(text).strip() == "import trimesh\nx = 2"


def test_extract_script_ignores_other_fences():
    text = "```json\n{}\n```\n```python\ny = 3\n```"
    assert extract_script(text).strip() == "y = 3"


def test_extract_script_without_block_raises_value_error():
    with pytest.raises(ValueError):
        extract_script("no code here")


def test_system_prompt_is_non_empty_text():
    assert isinstance(SYSTEM_PROMPT, str) and len(SYSTEM_PROMPT) > 50


def test_first_turn_has_image_blocks_for_photo_and_drawing_then_text(tmp_path):
    photo = _png(tmp_path / "photo-1.png", (255, 0, 0))
    drawing = _png(tmp_path / "drawing.png", (0, 0, 255))
    blocks = first_turn([photo], drawing, DIMS, {"code": "SRTWC", "name": "Water closets"}, PRIMS)
    imgs = _images(blocks)
    assert len(imgs) == 2
    for b in imgs:
        assert b["source"]["type"] == "base64" and b["source"]["media_type"] == "image/png"
    assert base64.b64decode(imgs[0]["source"]["data"]) == photo.read_bytes()
    assert base64.b64decode(imgs[1]["source"]["data"]) == drawing.read_bytes()
    kinds = [b["type"] for b in blocks]
    assert kinds.index("text") > max(i for i, k in enumerate(kinds) if k == "image")
    text = _text(blocks)
    for needle in ("1234", "567", "891", "Water closets"):
        assert needle in text


def test_first_turn_without_drawing_or_category_has_only_photos(tmp_path):
    photos = [_png(tmp_path / "photo-1.png", (1, 2, 3)), _png(tmp_path / "photo-2.png", (4, 5, 6))]
    blocks = first_turn(photos, None, DIMS, None, PRIMS)
    assert len(_images(blocks)) == 2
    assert "1234" in _text(blocks)


def test_first_turn_names_the_approach(tmp_path):
    photo = _png(tmp_path / "photo-1.png", (1, 2, 3))
    assert "sdf" in _text(first_turn([photo], None, DIMS, None, SDF)).lower()
    assert "primitives" in _text(first_turn([photo], None, DIMS, None, PRIMS)).lower()


def test_refine_turn_carries_renders_measurements_and_error():
    renders = {"front": b"\x89PNG-front", "side": b"\x89PNG-side", "three_quarter": b"\x89PNG-tq"}
    measured = {"length": 1190.5, "width": 604.2, "height": 760.0}
    spec = {"length": 1200, "width": 600, "height": 750}
    blocks = refine_turn(renders, measured, spec, "Traceback: NameError: boom")
    imgs = _images(blocks)
    assert len(imgs) == 3
    assert {base64.b64decode(b["source"]["data"]) for b in imgs} == set(renders.values())
    text = _text(blocks)
    for needle in ("1190.5", "604.2", "760", "1200", "600", "750", "NameError: boom"):
        assert needle in text


def test_refine_turn_without_error_has_no_error_text():
    blocks = refine_turn({"front": b"a"}, {"length": 1, "width": 2, "height": 3}, {"length": 1, "width": 2, "height": 3}, None)
    assert "Traceback" not in _text(blocks)


def test_large_images_are_downscaled_and_kept_small(tmp_path):
    import numpy as np

    rng = np.random.default_rng(1)
    arr = rng.integers(0, 255, (4000, 6000, 3), dtype=np.uint8)
    path = tmp_path / "photo-1.png"
    Image.fromarray(arr).save(path, "PNG")
    blocks = first_turn([path], None, DIMS, None, PRIMS)
    src = _images(blocks)[0]["source"]
    data = base64.b64decode(src["data"])
    assert len(data) < 3_500_000
    img = Image.open(io.BytesIO(data))
    assert max(img.size) <= 1568
    assert src["media_type"] in ("image/jpeg", "image/png")


def test_small_png_is_passed_through_unchanged(tmp_path):
    photo = _png(tmp_path / "photo-1.png", (1, 2, 3))
    imgs = _images(first_turn([photo], None, DIMS, None, PRIMS))
    assert base64.b64decode(imgs[0]["source"]["data"]) == photo.read_bytes()


def test_system_prompt_carries_the_budget_orientation_and_material_rules():
    for needle in ("60,000", "300,000", "filter_taubin", "simplify_quadric_decimation", "Z", "lofted", "roughness 0.3", "metallic 1.0"):
        assert needle in SYSTEM_PROMPT


def test_refine_turn_lists_triangles_parts_and_orientation_first():
    parts = [{"name": "lid", "extentsMm": [400.0, 300.0, 20.0], "centreMm": [0.0, 750.0, 0.0]}]
    spec = {"length": 1, "width": 2, "height": 3}
    text = _text(refine_turn({"front": b"a"}, spec, spec, None, faces=70000, parts=parts, over_budget=True))
    assert "70000" in text and "lid" in text and "400.0 x 300.0 x 20.0" in text
    assert "orientation" in text and "over the 60000" in text.replace(",", "").replace("_", "")


def test_a_huge_pixel_count_is_rejected_before_it_is_decoded(tmp_path):
    from planner3d_worker.claude.prompts import ImageTooLarge

    path = tmp_path / "photo-1.png"
    Image.new("1", (11000, 11000)).save(path, "PNG")  # 121 MP, tiny on disk
    with pytest.raises(ImageTooLarge):
        first_turn([path], None, DIMS, None, PRIMS)


def test_a_60_megapixel_drawing_is_accepted_and_shrunk(tmp_path):
    path = tmp_path / "drawing.png"
    Image.new("L", (8000, 7500), 200).save(path, "PNG")  # 60 MP
    blocks = first_turn([], path, DIMS, None, PRIMS)
    img = Image.open(io.BytesIO(base64.b64decode(_images(blocks)[0]["source"]["data"])))
    assert max(img.size) <= 1568


@pytest.mark.parametrize(
    "text",
    [
        "```python\r\nimport trimesh\r\nx = 1\r\n```\r\n",
        "```py\nx = 1\n```",
        "```Python\nx = 1\n```",
        "- step one:\n    ```python\n    import trimesh\n    if True:\n        x = 1\n    ```\n",
    ],
)
def test_extract_script_handles_fence_variants_and_indented_blocks(text):
    import ast

    ast.parse(extract_script(text))


def test_extract_script_prefers_the_block_that_writes_the_model_over_a_later_snippet():
    text = "```python\nimport trimesh\nm = 1\nm.export('model.glb')\n```\nnote\n```python\nprint('tip')\n```"
    assert "model.glb" in extract_script(text)


def test_extract_script_without_model_glb_takes_the_longest_block():
    text = "```python\na = 1\nb = 2\nc = 3\n```\n```python\nz = 1\n```"
    assert "c = 3" in extract_script(text)
