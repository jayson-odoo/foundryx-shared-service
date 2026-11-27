"""Prompt builders for the claude-procedural engine (plan D3, D7)."""

from __future__ import annotations

import base64
import io
import re
import textwrap
import warnings
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

from planner3d_worker.claude.routing import Profile

SYSTEM_PROMPT = """\
You are a procedural CAD modeller. From product photos, an optional technical drawing and exact dimensions you write ONE self-contained Python script that builds the product as a 3D model.

Rules for the script:
- Use only numpy, math, trimesh and manifold3d (and scipy, json, itertools, functools, collections if needed). No other imports, no file or network access except the two files below.
- Read the dimensions with json.load(open("params.json")). It holds {"dimensionsMm": {"length", "width", "height"}} in millimetres.
- Build the product in glTF frame: Y up, units metres, origin at the centre of the base, length along X, width along Z, the front of the product faces +Z.
- The bounding box of the final model must equal the given dimensions exactly: build at any scale, then scale each axis at the end so the extents are length/1000 (X), height/1000 (Y), width/1000 (Z), and translate so the base sits at Y = 0 centred on X and Z.
- Clean, watertight-ish surfaces. Smooth where the product is curved (enough segments, no faceted lumps or stray fragments). Parts that are one piece in reality must be one welded piece; keep genuinely separate parts (seat, lid, taps, handles) as separate named parts.
- Approach "primitives": a CSG of primitives (boxes, cylinders, spheres, extrusions) combined with manifold3d booleans.
- Approach "sdf": a numpy signed distance field with smooth unions (smooth minimum) sampled on a grid and meshed with manifold3d (Manifold.level_set) for one-piece ceramics; then convert to a trimesh mesh.
- Total triangle budget 60,000 (hard limit 300,000): mesh SDF bodies at a resolution fine enough for smooth curves, then smooth (trimesh.smoothing.filter_taubin) and decimate to the budget (mesh.simplify_quadric_decimation(face_count=N)).
- trimesh.creation.cylinder, annulus and capsule run along Z: rotate them so their axes match the Y-up frame before use, and check the orientation in the renders.
- Sculpted parts (levers, spouts, handles) are lofted or swept profiles, or hulls of several cross-sections, never a single box.
- Materials: ceramic white roughness 0.3, chrome metallic 1.0 roughness 0.1, following the photo.
- Colours go in glTF PBR materials only: give each part trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(baseColorFactor=[r, g, b, 255], metallicFactor=..., roughnessFactor=...)), never vertex colours or face colours. Always name each part (Scene geometry names) and give every part its own material.
- baseColorFactor values are LINEAR, not sRGB: convert every colour you read from the photo (sRGB) to linear before writing it (c/255, then ((c + 0.055) / 1.055) ** 2.4 for c above 0.04045, else c / 12.92). A "Photo finish colours" line in the request lists measured colours with their linear values.
- Finish table (linear baseColorFactor, metallic, roughness); start from it and adjust to the photo colour facts, keeping the table values unless the photo clearly differs: chrome (0.55, 0.556, 0.554) m1 r0.08; brushed nickel / stainless (0.66, 0.61, 0.53) m1 r0.35; brushed gold (1.0, 0.766, 0.336) m1 r0.35; polished gold (1.0, 0.766, 0.336) m1 r0.1; rose gold (0.95, 0.64, 0.54) m1 r0.25; gunmetal (0.22, 0.22, 0.23) m1 r0.3; matte black (0.02, 0.02, 0.02) m0 r0.6; ceramic white (0.85, 0.85, 0.83) m0 r0.15. Choose the finish of each part from the photo.
- Model every functional feature visible in the photo or drawing: drain / waste outlet hole (with its chrome pop-up cap when shown), tap holes, overflow slots, flush buttons, handles, aerators. Before writing the script, list the visible features in a comment at the top of the script, then build each.
- Write the result to model.glb in the current directory with simple PBR materials that match the photo (for example white ceramic: baseColor near white, roughness 0.15, metallic 0; chrome: metallic 1, roughness 0.1). Use trimesh.visual.material.PBRMaterial and export a trimesh.Scene so named parts survive.
- Look at the drawing for sides the photo does not show (back, top, hidden faces) and follow it for proportions.
- The script must run to completion in under four minutes on a laptop CPU and must not print secrets or read anything outside the cwd.

Reply with a short note and then ONLY the script in a single ```python fenced block.
"""

MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def _sniff(data: bytes, path: Path) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return MEDIA_TYPES.get(path.suffix.lower(), "image/png")


def _image_block(data: bytes, media_type: str) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(data).decode("ascii")}}


TRIANGLE_BUDGET = 60_000
MAX_SIDE = 1568
MAX_BYTES = 3_500_000


MAX_PIXELS = 100_000_000


class ImageTooLarge(ValueError):
    """An input image has more pixels than the engine will decode."""


def _shrink(data: bytes, media_type: str) -> tuple[bytes, str]:
    """Long side at most MAX_SIDE px, EXIF orientation applied, under MAX_BYTES. A small image passes through."""
    old_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            try:
                img = Image.open(io.BytesIO(data))
                if img.size[0] * img.size[1] > MAX_PIXELS:
                    raise ImageTooLarge(f"the image is {img.size[0]}x{img.size[1]} pixels; at most {MAX_PIXELS} are accepted")
                if img.format == "JPEG":
                    img.draft("RGB", (MAX_SIDE * 2, MAX_SIDE * 2))  # decode at a reduced size
                img.load()
            except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
                raise ImageTooLarge("the image has too many pixels") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = old_limit
    if max(img.size) <= MAX_SIDE and len(data) <= MAX_BYTES:
        return data, media_type
    img = ImageOps.exif_transpose(img)
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    candidates: list[tuple[bytes, str]] = []
    if media_type == "image/png":
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        candidates.append((buf.getvalue(), "image/png"))
    flat = img.convert("RGB") if img.mode not in ("RGB", "L") else img
    for quality in (90, 80, 70, 60):
        buf = io.BytesIO()
        flat.save(buf, "JPEG", quality=quality)
        candidates.append((buf.getvalue(), "image/jpeg"))
        if len(buf.getvalue()) <= MAX_BYTES:
            break
    fitting = [c for c in candidates if len(c[0]) <= MAX_BYTES]
    return min(fitting or candidates, key=lambda c: len(c[0]))


def _file_block(path: Path) -> dict:
    data = Path(path).read_bytes()
    data, media_type = _shrink(data, _sniff(data, Path(path)))
    return _image_block(data, media_type)


def finish_line(finish_colours: list[dict]) -> str:
    listed = ", ".join(f"{c['hex']} (linear {c['linear'][0]}, {c['linear'][1]}, {c['linear'][2]})" for c in finish_colours)
    return f"Photo finish colours (sRGB hex, linear rgb): {listed}."


def first_turn(
    photos: list[Path],
    drawing: Optional[Path],
    dims_mm: dict,
    category: Optional[dict],
    profile: Profile,
    finish_colours: Optional[list[dict]] = None,
) -> list[dict]:
    blocks = [_file_block(p) for p in photos]
    if drawing is not None:
        blocks.append(_file_block(drawing))
    lines = [
        f"Images: {len(photos)} product photo(s)" + (", then the technical drawing (hidden sides)." if drawing is not None else "."),
        f"Dimensions in mm: length {dims_mm['length']} (X), width {dims_mm['width']} (Z), height {dims_mm['height']} (Y).",
    ]
    if category and (category.get("name") or category.get("code")):
        lines.append(f"Category: {category.get('name') or category.get('code')}.")
    if finish_colours:
        lines.append(finish_line(finish_colours))
    if profile.approach == "sdf":
        lines.append("Approach: sdf (signed distance field with smooth unions, meshed with manifold3d level set). One smooth ceramic piece.")
    else:
        lines.append("Approach: primitives (CSG of primitives via manifold3d).")
    lines.append("The script reads params.json with the dimensions above. Write the script now.")
    blocks.append({"type": "text", "text": "\n".join(lines)})
    return blocks


def refine_turn(
    renders: dict[str, bytes],
    measured_mm: dict,
    spec_mm: dict,
    error: Optional[str],
    faces: Optional[int] = None,
    parts: Optional[list[dict]] = None,
    over_budget: bool = False,
) -> list[dict]:
    blocks = [_image_block(png, "image/png") for png in renders.values()]
    lines = [
        "Renders of your model: " + ", ".join(renders) + " (flat shaded, light grey).",
        "Measured bounding box mm: " + ", ".join(f"{k} {measured_mm[k]}" for k in ("length", "width", "height") if k in measured_mm) + ".",
        "Specified mm: " + ", ".join(f"{k} {spec_mm[k]}" for k in ("length", "width", "height") if k in spec_mm) + ".",
    ]
    if faces is not None:
        lines.append(f"Triangle count: {faces} (budget {TRIANGLE_BUDGET}).")
        if over_budget:
            lines.append(f"The model is over the {TRIANGLE_BUDGET} triangle budget: smooth and decimate it to the budget.")
    if parts:
        lines.append("Parts (name, extents mm length x width x height, centre mm x, y, z):")
        for part in parts:
            e, c = part["extentsMm"], part["centreMm"]
            lines.append(f"- {part['name']}: {e[0]} x {e[1]} x {e[2]}, centre {c[0]}, {c[1]}, {c[2]}")
    if error:
        lines.append("The last run failed with this error:\n" + error)
    lines.append("Check each feature you listed at the top of your script is present and visible in the renders; add any that are missing.")
    lines.append("Fix orientation errors first (a part standing the wrong way, an axis on Z instead of Y).")
    lines.append(
        "Compare the renders with the photo and the drawing, fix the biggest visual differences "
        "and any bbox mismatch, and return the full corrected script in one ```python block."
    )
    blocks.append({"type": "text", "text": "\n".join(lines)})
    return blocks


_FENCE = re.compile(r"^[ \t]*```[ \t]*(?:python3?|py)[ \t]*\n(.*?)^[ \t]*```", re.DOTALL | re.MULTILINE | re.IGNORECASE)


def extract_script(text: str) -> str:
    """The script block of a reply: the last python block that writes model.glb, else the longest."""
    blocks = [textwrap.dedent(b) for b in _FENCE.findall((text or "").replace("\r\n", "\n"))]
    if not blocks:
        raise ValueError("the reply has no ```python block")
    writers = [b for b in blocks if "model.glb" in b]
    return writers[-1] if writers else max(blocks, key=len)
