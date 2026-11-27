"""Prompt builders for the claude-procedural engine (plan D3, D7)."""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Optional

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


def _file_block(path: Path) -> dict:
    data = Path(path).read_bytes()
    return _image_block(data, _sniff(data, Path(path)))


def first_turn(photos: list[Path], drawing: Optional[Path], dims_mm: dict, category: Optional[dict], profile: Profile) -> list[dict]:
    blocks = [_file_block(p) for p in photos]
    if drawing is not None:
        blocks.append(_file_block(drawing))
    lines = [
        f"Images: {len(photos)} product photo(s)" + (", then the technical drawing (hidden sides)." if drawing is not None else "."),
        f"Dimensions in mm: length {dims_mm['length']} (X), width {dims_mm['width']} (Z), height {dims_mm['height']} (Y).",
    ]
    if category and (category.get("name") or category.get("code")):
        lines.append(f"Category: {category.get('name') or category.get('code')}.")
    if profile.approach == "sdf":
        lines.append("Approach: sdf (signed distance field with smooth unions, meshed with manifold3d level set). One smooth ceramic piece.")
    else:
        lines.append("Approach: primitives (CSG of primitives via manifold3d).")
    lines.append("The script reads params.json with the dimensions above. Write the script now.")
    blocks.append({"type": "text", "text": "\n".join(lines)})
    return blocks


def refine_turn(renders: dict[str, bytes], measured_mm: dict, spec_mm: dict, error: Optional[str]) -> list[dict]:
    blocks = [_image_block(png, "image/png") for png in renders.values()]
    lines = [
        "Renders of your model: " + ", ".join(renders) + " (flat shaded, light grey).",
        "Measured bounding box mm: " + ", ".join(f"{k} {measured_mm[k]}" for k in ("length", "width", "height") if k in measured_mm) + ".",
        "Specified mm: " + ", ".join(f"{k} {spec_mm[k]}" for k in ("length", "width", "height") if k in spec_mm) + ".",
    ]
    if error:
        lines.append("The last run failed with this error:\n" + error)
    lines.append(
        "Compare the renders with the photo and the drawing, fix the biggest visual differences "
        "and any bbox mismatch, and return the full corrected script in one ```python block."
    )
    blocks.append({"type": "text", "text": "\n".join(lines)})
    return blocks


_FENCE = re.compile(r"```python[ \t]*\r?\n(.*?)```", re.DOTALL)


def extract_script(text: str) -> str:
    blocks = _FENCE.findall(text or "")
    if not blocks:
        raise ValueError("the reply has no ```python block")
    return blocks[-1]
