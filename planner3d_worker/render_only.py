"""Render-only compositing: the AI redraws the room, the products stay as they were.

An image model asked to "make this room look real" will also redraw the products
in it, and a redrawn product is no longer the product in the catalogue. So the
generated picture is only ever used OUTSIDE the product mask: every product pixel
is copied back from the original viewport capture, byte for byte, and
`product_diff` proves it.

The command line counts a mask pixel as product when its red channel is above 0,
writes PNG only, and reports from the saved file read back from disk.

numpy and Pillow only.

    python render_only.py composite --original a.png --generated b.png \
        --mask m.png --out final.png --diff-out diff.png --report report.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

# Amplification of the difference picture. A change of a few levels is
# invisible at 1x, and those are exactly the changes worth seeing.
DIFF_GAIN = 8
# Drawn round the product in the difference picture. Magenta, because a
# difference picture is mostly black and grey.
OUTLINE_COLOUR = (255, 0, 255)
# How the command line reads the mask picture. Written into the report, so the
# numbers say which pixels they are about.
MASK_RULE = "red > 0"


def _check_shapes(first: np.ndarray, second: np.ndarray, mask: np.ndarray) -> None:
    for name, image in (("first image", first), ("second image", second)):
        if image.ndim != 3 or image.shape[2] != 3:
            raise ValueError(f"{name} must have shape (H, W, 3), got {image.shape}")
    if first.shape != second.shape:
        raise ValueError(f"images differ in size: {first.shape} and {second.shape}")
    if mask.shape != first.shape[:2]:
        raise ValueError(f"mask {mask.shape} does not match image {first.shape[:2]}")


def _distance_outside(mask: np.ndarray, reach: int) -> np.ndarray:
    """Distance in pixels from each pixel to the nearest mask pixel.

    Only out to `reach`: anything further is infinity, which is all the feather
    needs to know. The mask is slid over itself once per offset inside that
    radius, which is a handful of shifts for a feather of a few pixels and needs
    no scipy.
    """
    height, width = mask.shape
    distance = np.full(mask.shape, np.inf)
    distance[mask] = 0.0
    padded = np.pad(mask, reach, mode="constant", constant_values=False)
    for dy in range(-reach, reach + 1):
        for dx in range(-reach, reach + 1):
            offset = float(np.hypot(dy, dx))
            if offset == 0.0 or offset > reach:
                continue
            # True where the pixel at (y + dy, x + dx) is product.
            shifted = padded[reach + dy : reach + dy + height, reach + dx : reach + dx + width]
            np.minimum(distance, np.where(shifted, offset, np.inf), out=distance)
    return distance


def composite(
    original: np.ndarray,
    generated: np.ndarray,
    product_mask: np.ndarray,
    feather_px: int = 2,
) -> np.ndarray:
    """`generated` everywhere except the products, which come from `original`.

    The feather goes OUTWARD only. Alpha is 1 on every mask pixel and falls to 0
    over `feather_px` pixels outside it, so the seam is softened with background
    pixels and a product pixel is never blended.
    """
    original = np.asarray(original)
    generated = np.asarray(generated)
    mask = np.asarray(product_mask).astype(bool)
    _check_shapes(original, generated, mask)
    if feather_px < 0:
        raise ValueError(f"feather_px must be 0 or more, got {feather_px}")

    feather = int(feather_px)
    alpha = np.zeros(mask.shape, dtype=np.float64)
    if feather > 0:
        distance = _distance_outside(mask, feather)
        alpha = np.clip(1.0 - distance / (feather + 1), 0.0, 1.0)
    alpha = alpha[..., None]

    blended = np.rint(alpha * original + (1.0 - alpha) * generated).astype(np.uint8)
    # The two ends are copied rather than trusted to the arithmetic: "byte for
    # byte" is the whole claim, so it does not rest on float rounding.
    blended = np.where(alpha == 0.0, generated, blended)
    blended = np.where(mask[..., None], original, blended)
    return blended.astype(np.uint8)


def product_diff(original: np.ndarray, final: np.ndarray, product_mask: np.ndarray) -> dict:
    """How many product pixels differ between `original` and `final`, and by how much."""
    original = np.asarray(original)
    final = np.asarray(final)
    mask = np.asarray(product_mask).astype(bool)
    _check_shapes(original, final, mask)

    difference = np.abs(original.astype(np.int16) - final.astype(np.int16))[mask]
    return {
        "product_pixels": int(mask.sum()),
        "changed_pixels": int(difference.any(axis=1).sum()),
        "max_abs_diff": int(difference.max()) if difference.size else 0,
    }


def _outline(mask: np.ndarray) -> np.ndarray:
    """The ring of pixels just OUTSIDE the mask, so it never covers a product pixel."""
    return np.isfinite(_distance_outside(mask, 1)) & ~mask


def _diff_picture(original: np.ndarray, final: np.ndarray, mask: np.ndarray) -> np.ndarray:
    difference = np.abs(original.astype(np.int16) - final.astype(np.int16))
    picture = np.clip(difference * DIFF_GAIN, 0, 255).astype(np.uint8)
    picture[_outline(mask)] = OUTLINE_COLOUR
    return picture


def _load_rgb(path: Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def _load_mask(path: Path) -> np.ndarray:
    """Product wherever the mask's red channel is above 0.

    Not "at least half": the scene draws products with smoothed edges, so the
    rim of a product is a pixel the product only partly covers, and its mask
    value is somewhere between black and white. It still shows the product, so
    it is still a pixel the image model may not keep.
    """
    return np.asarray(_load_rgb(path))[..., 0] > 0


def verify_saved(original_path: Path, final_path: Path, mask_path: Path) -> dict:
    """`product_diff`, measured from the files on disk.

    The claim is about the picture somebody is handed, so it is checked on that
    picture, read back, rather than on the array that was about to be saved.
    """
    return product_diff(
        np.asarray(_load_rgb(original_path)),
        np.asarray(_load_rgb(final_path)),
        _load_mask(mask_path),
    )


def run_composite(args: argparse.Namespace) -> dict:
    # A lossy file cannot keep product pixels unchanged, so it is refused before
    # anything is written rather than reported on afterwards.
    if args.out.suffix.lower() != ".png":
        raise SystemExit(f"--out must be a .png file (lossless), got {args.out.name}")

    original_image = _load_rgb(args.original)
    generated_image = _load_rgb(args.generated)
    # Image models hand back their own size; the viewport's is the one that counts.
    if generated_image.size != original_image.size:
        generated_image = generated_image.resize(original_image.size, Image.LANCZOS)

    original = np.asarray(original_image)
    generated = np.asarray(generated_image)
    mask = _load_mask(args.mask)

    Image.fromarray(composite(original, generated, mask, feather_px=args.feather)).save(args.out)
    # Every number below describes the file just written, read back from disk.
    final = np.asarray(_load_rgb(args.out))

    outside = ~mask
    changed_outside = (original != final).any(axis=2) & outside
    report = {
        **verify_saved(args.original, args.out, args.mask),
        "mask_rule": MASK_RULE,
        "image_size": [original_image.width, original_image.height],
        "feather_px": args.feather,
        "changed_outside_pct": (
            round(100.0 * float(changed_outside.sum()) / float(outside.sum()), 2)
            if outside.any()
            else 0.0
        ),
    }

    if args.diff_out:
        Image.fromarray(_diff_picture(original, final, mask)).save(args.diff_out)
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    comp = commands.add_parser("composite", help="paste the original product pixels onto a generated image")
    comp.add_argument("--original", type=Path, required=True, help="the viewport capture")
    comp.add_argument("--generated", type=Path, required=True, help="the image model's picture")
    comp.add_argument("--mask", type=Path, required=True, help="products on black; any red above 0 is product")
    comp.add_argument("--out", type=Path, required=True, help="where to write the final image (.png only)")
    comp.add_argument("--diff-out", type=Path, help="where to write the difference picture")
    comp.add_argument("--report", type=Path, help="where to write the numbers, as JSON")
    comp.add_argument("--feather", type=int, default=2, help="pixels of blend outside the product")
    comp.set_defaults(run=run_composite)

    args = parser.parse_args(argv)
    print(json.dumps(args.run(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
