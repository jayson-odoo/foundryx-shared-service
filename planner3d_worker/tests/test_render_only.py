import numpy as np
import pytest

from planner3d_worker.render_only import composite, product_diff

H, W = 40, 60


def _images(seed=0):
    rng = np.random.default_rng(seed)
    original = rng.integers(0, 256, size=(H, W, 3), dtype=np.uint8)
    generated = rng.integers(0, 256, size=(H, W, 3), dtype=np.uint8)
    return original, generated


def _rect_mask():
    m = np.zeros((H, W), dtype=bool)
    m[12:28, 20:40] = True
    return m


def _irregular_mask():
    m = np.zeros((H, W), dtype=bool)
    m[5:15, 5:12] = True
    m[10:30, 8:14] = True
    m[25, 40] = True
    m[26:34, 44:55] = True
    m[30, 30:36] = True
    return m


MASKS = [_rect_mask, _irregular_mask]


def _chebyshev_distance(mask):
    """Brute-force Chebyshev distance to the nearest mask pixel."""
    ys, xs = np.nonzero(mask)
    dist = np.full(mask.shape, np.inf)
    for y in range(mask.shape[0]):
        for x in range(mask.shape[1]):
            dist[y, x] = np.max([np.abs(ys - y), np.abs(xs - x)], axis=0).min()
    return dist


@pytest.mark.parametrize("make_mask", MASKS)
@pytest.mark.parametrize("feather", [0, 2, 4])
def test_b1_product_pixels_are_original(make_mask, feather):
    original, generated = _images(1)
    mask = make_mask()
    out = composite(original, generated, mask, feather_px=feather)
    assert out.dtype == np.uint8
    assert out.shape == (H, W, 3)
    assert np.array_equal(out[mask], original[mask])


def test_b1_ignores_generated_content_on_the_product():
    original, generated = _images(2)
    mask = _rect_mask()
    other = generated.copy()
    other[mask] = 255 - other[mask]
    a = composite(original, generated, mask)
    b = composite(original, other, mask)
    assert np.array_equal(a[mask], b[mask])
    assert np.array_equal(a[mask], original[mask])


@pytest.mark.parametrize("make_mask", MASKS)
@pytest.mark.parametrize("feather", [1, 2, 4])
def test_b2_far_pixels_are_generated(make_mask, feather):
    original, generated = _images(3)
    mask = make_mask()
    out = composite(original, generated, mask, feather_px=feather)
    far = _chebyshev_distance(mask) > feather + 1
    assert far.any()
    assert np.array_equal(out[far], generated[far])


def test_b2_default_feather_is_two():
    original, generated = _images(4)
    mask = _rect_mask()
    out = composite(original, generated, mask)
    far = _chebyshev_distance(mask) > 3
    assert np.array_equal(out[far], generated[far])


@pytest.mark.parametrize("make_mask", MASKS)
def test_b3_band_is_a_blend(make_mask):
    original, generated = _images(5)
    mask = make_mask()
    feather = 3
    out = composite(original, generated, mask, feather_px=feather)
    dist = _chebyshev_distance(mask)
    band = (~mask) & (dist <= feather + 1)
    assert band.any()
    lo = np.minimum(original, generated)[band].astype(int)
    hi = np.maximum(original, generated)[band].astype(int)
    got = out[band].astype(int)
    # allow one level for rounding of the blend
    assert (got >= lo - 1).all()
    assert (got <= hi + 1).all()


def test_b4_zero_feather_is_a_hard_edge():
    original, generated = _images(6)
    mask = _irregular_mask()
    out = composite(original, generated, mask, feather_px=0)
    assert np.array_equal(out[mask], original[mask])
    assert np.array_equal(out[~mask], generated[~mask])


def test_b5_mismatched_shapes_raise():
    original, generated = _images(7)
    mask = _rect_mask()
    with pytest.raises(ValueError):
        composite(original[:, :-1], generated, mask)
    with pytest.raises(ValueError):
        composite(original, generated[:-1], mask)
    with pytest.raises(ValueError):
        composite(original, generated, mask[:-1])
    with pytest.raises(ValueError):
        composite(original, generated, mask[:, :-1])


@pytest.mark.parametrize("make_mask", MASKS)
def test_b6_composite_output_leaves_product_untouched(make_mask):
    original, generated = _images(8)
    mask = make_mask()
    out = composite(original, generated, mask)
    diff = product_diff(original, out, mask)
    assert diff["product_pixels"] == int(mask.sum())
    assert diff["changed_pixels"] == 0
    assert diff["max_abs_diff"] == 0


def test_b6_empty_mask_gives_zeroes():
    original, generated = _images(9)
    mask = np.zeros((H, W), dtype=bool)
    diff = product_diff(original, generated, mask)
    assert diff == {"product_pixels": 0, "changed_pixels": 0, "max_abs_diff": 0}


def test_b7_one_altered_channel_is_detected():
    original, generated = _images(10)
    mask = _rect_mask()
    out = composite(original, generated, mask)
    y, x = 15, 25
    assert mask[y, x]
    value = int(out[y, x, 1])
    out[y, x, 1] = value + 1 if value < 255 else value - 1
    diff = product_diff(original, out, mask)
    assert diff["changed_pixels"] == 1
    assert diff["max_abs_diff"] == 1


def test_b7_change_outside_the_mask_is_ignored():
    original, generated = _images(11)
    mask = _rect_mask()
    out = composite(original, generated, mask)
    out[0, 0] = 255 - out[0, 0]
    diff = product_diff(original, out, mask)
    assert diff["changed_pixels"] == 0
    assert diff["max_abs_diff"] == 0


# ---- B8 to B11: rim pixels, disk-measured report, lossless output, pixel counting ----

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

from planner3d_worker import render_only

RENDER_ONLY = Path(render_only.__file__).resolve()


def _rim_mask_red():
    red = np.zeros((H, W), dtype=np.uint8)
    red[12:28, 20:40] = 255
    block = red == 255
    grown = np.zeros_like(block)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            grown |= np.roll(np.roll(block, dy, axis=0), dx, axis=1)
    red[grown & ~block] = 60
    return red


def _write_case(tmp_path):
    original, generated = _images(seed=3)
    red = _rim_mask_red()
    Image.fromarray(original).save(tmp_path / "original.png")
    Image.fromarray(generated).save(tmp_path / "generated.png")
    mask_rgb = np.stack([red, np.zeros_like(red), np.zeros_like(red)], axis=2)
    Image.fromarray(mask_rgb).save(tmp_path / "mask.png")
    return original, red


def _run_cli(tmp_path, out_name="final.png", report=True):
    cmd = [
        sys.executable, str(RENDER_ONLY), "composite",
        "--original", str(tmp_path / "original.png"),
        "--generated", str(tmp_path / "generated.png"),
        "--mask", str(tmp_path / "mask.png"),
        "--out", str(tmp_path / out_name),
    ]
    if report:
        cmd += ["--report", str(tmp_path / "report.json")]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_b8_rim_pixels_are_original(tmp_path):
    original, red = _write_case(tmp_path)
    result = _run_cli(tmp_path)
    assert result.returncode == 0, result.stderr
    final = np.asarray(Image.open(tmp_path / "final.png").convert("RGB"))
    product = red > 0
    assert product.sum() > (red == 255).sum()
    assert np.array_equal(final[product], original[product])


def test_b9_report_matches_disk(tmp_path):
    _, red = _write_case(tmp_path)
    result = _run_cli(tmp_path)
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["product_pixels"] == int((red > 0).sum())
    assert report["changed_pixels"] == 0
    assert report["max_abs_diff"] == 0


def test_b9_verify_saved_reads_paths(tmp_path):
    original, red = _write_case(tmp_path)
    final = original.copy()
    ys, xs = np.nonzero(red > 0)
    final[ys[0], xs[0], 0] = (int(final[ys[0], xs[0], 0]) + 5) % 256
    Image.fromarray(final).save(tmp_path / "final.png")
    result = render_only.verify_saved(
        tmp_path / "original.png", tmp_path / "final.png", tmp_path / "mask.png"
    )
    assert result["changed_pixels"] == 1
    assert result["product_pixels"] == int((red > 0).sum())


def test_b10_lossy_output_refused(tmp_path):
    _write_case(tmp_path)
    result = _run_cli(tmp_path, out_name="final.jpg")
    assert result.returncode != 0
    assert not (tmp_path / "final.jpg").exists()


def test_b11_product_diff_counts_pixels_not_channels():
    original, _ = _images(seed=5)
    mask = _rect_mask()
    final = original.copy()
    final[15, 25, 0] = (int(final[15, 25, 0]) + 3) % 256
    final[15, 25, 1] = (int(final[15, 25, 1]) + 7) % 256
    expected = max(
        abs(int(final[15, 25, c]) - int(original[15, 25, c])) for c in (0, 1)
    )
    result = product_diff(original, final, mask)
    assert result["changed_pixels"] == 1
    assert result["max_abs_diff"] == expected
