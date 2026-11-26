"""Server-side product-pixel check for render jobs (plan D3).

Same semantics as ``planner3d_worker/render_only.product_diff`` with the mask
rule ``red > 0``, but Pillow only (the backend has no numpy). The render must
be the scene's size: SS never resizes it.
"""

from __future__ import annotations

import io

from PIL import Image, ImageChops

MASK_RULE = "red > 0"


def product_diff(original_png: bytes, final_png: bytes, mask_png: bytes) -> dict:
    # Image.open reads the header only: sizes are compared before any decode.
    original = Image.open(io.BytesIO(original_png))
    final = Image.open(io.BytesIO(final_png))
    mask = Image.open(io.BytesIO(mask_png))
    if original.size != final.size:
        raise ValueError(f"images differ in size: {original.size} and {final.size}")
    if mask.size != original.size:
        raise ValueError(f"mask {mask.size} does not match image {original.size}")
    original, final, mask = original.convert("RGB"), final.convert("RGB"), mask.convert("RGB")

    product = mask.getchannel("R").point(lambda v: 255 if v > 0 else 0)
    diff = ImageChops.difference(original, final)
    r, g, b = diff.split()
    biggest = ImageChops.lighter(ImageChops.lighter(r, g), b)
    inside = ImageChops.darker(biggest, product)
    changed = inside.point(lambda v: 255 if v > 0 else 0)
    return {
        "product_pixels": product.histogram()[255],
        "changed_pixels": changed.histogram()[255],
        "max_abs_diff": inside.getextrema()[1],
    }
