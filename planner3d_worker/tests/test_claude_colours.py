"""Dominant foreground colours of a photo (numpy only, deterministic)."""
from PIL import Image, ImageDraw

from planner3d_worker.claude.colours import photo_colours


def _photo(tmp_path):
    img = Image.new("RGB", (200, 200), (250, 250, 250))
    d = ImageDraw.Draw(img)
    d.rectangle((40, 40, 160, 150), fill=(200, 160, 60))  # brushed gold
    d.ellipse((85, 90, 115, 120), fill=(20, 20, 20))  # dark drain
    path = tmp_path / "p.png"
    img.save(path)
    return path


def test_gold_is_the_dominant_colour_and_white_background_is_ignored(tmp_path):
    cols = photo_colours(_photo(tmp_path))
    assert cols[0]["hex"] == "#c8a03c"
    assert all(c["hex"] != "#fafafa" for c in cols)
    r, g, b = cols[0]["linear"]
    assert abs(r - 0.578) < 0.01 and r > g > b  # linear, not sRGB


def test_the_dark_part_is_listed_and_the_result_is_deterministic(tmp_path):
    p = _photo(tmp_path)
    cols = photo_colours(p)
    assert any(int(c["hex"][1:3], 16) < 60 for c in cols)
    assert cols == photo_colours(p)


def test_a_non_white_uniform_background_is_ignored(tmp_path):
    img = Image.new("RGB", (100, 100), (120, 130, 140))
    ImageDraw.Draw(img).rectangle((30, 30, 70, 70), fill=(10, 200, 10))
    img.save(tmp_path / "g.png")
    assert photo_colours(tmp_path / "g.png")[0]["hex"] == "#0ac80a"


def test_an_unreadable_image_gives_no_colours(tmp_path):
    (tmp_path / "x.png").write_bytes(b"nope")
    assert photo_colours(tmp_path / "x.png") == []
