"""Software z-buffer rasteriser for the render-compare loop (plan
planner3d-claude-procedural-engine, D7).

numpy + Pillow only, orthographic, flat shaded on white, with the material colour of each part
(glTF baseColorFactor / metallicFactor, or vertex and face colours), light grey when a part has none. Headless and
deterministic: the same mesh gives the same PNG bytes. glTF frame in: Y up, front
faces +Z, length along X.
"""

from __future__ import annotations

import io
import json
import math
import struct
from typing import Optional

import numpy as np
import trimesh
from PIL import Image

BACKGROUND = 255
# (yaw about Y in degrees, elevation in degrees): front looks down -Z, side down -X.
VIEWS = {"front": (0.0, 8.0), "side": (90.0, 8.0), "three_quarter": (35.0, 22.0)}
LIGHT = np.array([0.35, 0.55, 0.75])
LIGHT = LIGHT / np.linalg.norm(LIGHT)
DEFAULT_RGB = (0.78, 0.78, 0.78)
VIEW = np.array([0.0, 0.0, 1.0])
HALF = (LIGHT + VIEW) / np.linalg.norm(LIGHT + VIEW)
OUTLINE_RGB = np.array([70.0, 70.0, 70.0])


def _rotation(yaw_deg: float, elev_deg: float) -> np.ndarray:
    """World -> camera: camera x right, y up, z toward the viewer."""
    yaw, elev = math.radians(yaw_deg), math.radians(elev_deg)
    ry = np.array([[math.cos(yaw), 0, -math.sin(yaw)], [0, 1, 0], [math.sin(yaw), 0, math.cos(yaw)]])
    rx = np.array([[1, 0, 0], [0, math.cos(elev), -math.sin(elev)], [0, math.sin(elev), math.cos(elev)]])
    return rx @ ry


def _png(rgb: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(buf, "PNG", optimize=False)
    return buf.getvalue()


def _blank(size: int) -> bytes:
    return _png(np.full((size, size, 3), BACKGROUND, dtype=np.uint8))


def _material_of(geom) -> tuple[tuple[float, float, float], float]:
    """(rgb 0..1, metallic 0..1) from a geometry's material; the default grey when it has none."""
    rgb, metallic = DEFAULT_RGB, 0.0
    material = getattr(getattr(geom, "visual", None), "material", None)
    if material is not None:
        factor = getattr(material, "baseColorFactor", None)
        if factor is None:
            factor = getattr(material, "main_color", None)
        if factor is not None:
            f = np.asarray(factor, dtype=float).ravel()[:3]
            if len(f) == 3:
                rgb = tuple(float(x) / 255.0 for x in f)
        m = getattr(material, "metallicFactor", None)
        if m is not None:
            metallic = float(m)
    return rgb, metallic


def _collect(mesh, materials: Optional[dict]):
    """World vertices, faces and per-face colour and metallic of a Trimesh or a Scene."""
    if isinstance(mesh, trimesh.Scene):
        items = []
        for node in mesh.graph.nodes_geometry:
            transform, name = mesh.graph[node]
            items.append((name, mesh.geometry[name], transform))
    else:
        items = [(None, mesh, np.eye(4))]
    verts, faces, rgbs, metals = [], [], [], []
    offset = 0
    for name, geom, transform in items:
        v = np.asarray(getattr(geom, "vertices", []), dtype=float)
        f = np.asarray(getattr(geom, "faces", []), dtype=np.int64)
        if len(v) == 0 or len(f) == 0:
            continue
        v = np.einsum("ij,nj->ni", transform[:3, :3], v) + transform[:3, 3]
        rgb, metallic = (materials or {}).get(name) or _material_of(geom)
        face_rgb = np.tile(np.asarray(rgb, dtype=float), (len(f), 1))
        visual = getattr(geom, "visual", None)
        # vertex or face colours, when the file carries them, are the part's colour
        if visual is not None and getattr(visual, "kind", None) in ("vertex", "face") and visual.defined:
            face_rgb = np.asarray(visual.face_colors, dtype=float)[:, :3] / 255.0
        verts.append(v)
        faces.append(f + offset)
        rgbs.append(face_rgb)
        metals.append(np.full(len(f), metallic))
        offset += len(v)
    if not verts:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64), np.zeros((0, 3)), np.zeros(0)
    return np.concatenate(verts), np.concatenate(faces), np.concatenate(rgbs), np.concatenate(metals)


def _shade(cam_n: np.ndarray, rgb: np.ndarray, metallic: np.ndarray) -> np.ndarray:
    """Per-face colour 0..255. Dielectric: base x a studio rig (fill + key + rim). Metal: base x a sky/floor
    gradient on the normal plus one specular highlight; the two are mixed by the metallic factor."""
    lambert = np.abs(np.einsum("nj,j->n", cam_n, LIGHT))
    # studio rig: hemisphere fill 0.66, key light 0.34 (saturating so a face turned to it is fully lit), rim 0.06
    key = 0.34 * np.clip(1.3 * lambert, 0.0, 1.0)
    rim = 0.06 * (1.0 - np.abs(cam_n[:, 2]))
    dielectric = rgb * np.clip(0.66 + key + rim, 0.0, 1.0)[:, None]
    sky = 0.5 + 0.5 * cam_n[:, 1]
    env = 0.25 + 0.75 * sky
    spec = np.clip(np.abs(np.einsum("nj,j->n", cam_n, HALF)), 0.0, 1.0) ** 40
    metal = np.clip(rgb * (0.85 * env)[:, None] + (0.9 * spec)[:, None], 0.0, 1.0)
    m = metallic[:, None]
    return np.clip((1.0 - m) * dielectric + m * metal, 0.0, 1.0) * 255.0


def _render(vertices, faces, face_rgb, face_metal, yaw: float, elev: float, size: int) -> bytes:
    rot = _rotation(yaw, elev)
    pts = np.einsum("ij,nj->ni", rot, vertices - vertices.mean(axis=0))
    lo, hi = pts[:, :2].min(axis=0), pts[:, :2].max(axis=0)
    span = float(max(hi - lo)) or 1.0
    scale = size * 0.86 / span
    centre = (lo + hi) / 2.0
    sx = (pts[:, 0] - centre[0]) * scale + size / 2.0
    sy = size / 2.0 - (pts[:, 1] - centre[1]) * scale
    sz = pts[:, 2]

    tri = faces
    p0, p1, p2 = vertices[tri[:, 0]], vertices[tri[:, 1]], vertices[tri[:, 2]]
    normals = np.cross(p1 - p0, p2 - p0)
    lengths = np.linalg.norm(normals, axis=1)
    keep = lengths > 1e-12
    normals = np.where(keep[:, None], normals / np.where(keep, lengths, 1.0)[:, None], 0.0)
    cam_n = np.einsum("ij,nj->ni", rot, normals)
    colour = _shade(cam_n, face_rgb, face_metal).astype(np.uint8)

    image = np.full((size, size, 3), BACKGROUND, dtype=np.uint8)
    depth = np.full((size, size), -np.inf)
    for t in range(len(tri)):
        if not keep[t]:
            continue
        a, b, c = tri[t]
        x0, y0, x1, y1, x2, y2 = sx[a], sy[a], sx[b], sy[b], sx[c], sy[c]
        minx = max(int(math.floor(min(x0, x1, x2))), 0)
        maxx = min(int(math.ceil(max(x0, x1, x2))), size - 1)
        miny = max(int(math.floor(min(y0, y1, y2))), 0)
        maxy = min(int(math.ceil(max(y0, y1, y2))), size - 1)
        if minx > maxx or miny > maxy:
            continue
        den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(den) < 1e-12:
            continue
        gx, gy = np.meshgrid(np.arange(minx, maxx + 1) + 0.5, np.arange(miny, maxy + 1) + 0.5)
        w0 = ((y1 - y2) * (gx - x2) + (x2 - x1) * (gy - y2)) / den
        w1 = ((y2 - y0) * (gx - x2) + (x0 - x2) * (gy - y2)) / den
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not inside.any():
            continue
        z = w0 * sz[a] + w1 * sz[b] + w2 * sz[c]
        win_d = depth[miny : maxy + 1, minx : maxx + 1]
        win_i = image[miny : maxy + 1, minx : maxx + 1]
        closer = inside & (z > win_d)
        win_d[closer] = z[closer]
        win_i[closer] = colour[t]
    return _png(_outline(image, depth > -np.inf))


def _outline(image: np.ndarray, covered: np.ndarray) -> np.ndarray:
    """A soft 1 px dark edge on the silhouette so white parts read on the white background."""
    padded = np.pad(covered, 1, constant_values=False)
    interior = padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:]
    edge = covered & ~interior
    out = image.astype(float)
    out[edge] = 0.4 * out[edge] + 0.6 * OUTLINE_RGB
    return out.astype(np.uint8)


def glb_materials(data: bytes) -> dict:
    """Geometry name -> ((r, g, b) 0..1, metallic) from the glTF JSON chunk only (baseColorFactor and
    metallicFactor); no image is read or decoded. Names follow the loader's: the mesh name, with a
    ``_<n>`` suffix for further primitives, or ``geometry_<n>`` for an unnamed mesh."""
    try:
        if data[:4] != b"glTF" or len(data) < 20:
            return {}
        length, kind = struct.unpack("<I4s", data[12:20])
        if kind != b"JSON" or 20 + length > len(data):
            return {}
        doc = json.loads(data[20 : 20 + length].decode("utf-8"))
    except (ValueError, struct.error, UnicodeDecodeError):
        return {}
    mats = doc.get("materials") or []
    out: dict = {}
    for mi, mesh in enumerate(doc.get("meshes") or []):
        base = mesh.get("name") or f"geometry_{mi}"
        for pi, prim in enumerate(mesh.get("primitives") or []):
            idx = prim.get("material")
            if not isinstance(idx, int) or not 0 <= idx < len(mats):
                continue
            pbr = mats[idx].get("pbrMetallicRoughness") or {}
            factor = pbr.get("baseColorFactor") or [1.0, 1.0, 1.0, 1.0]
            value = (tuple(float(x) for x in factor[:3]), float(pbr.get("metallicFactor", 1.0)))
            out.setdefault(base, value)
            out[f"{base}_{pi}"] = value
    return out


def render_views(mesh, size: int = 512, materials: Optional[dict] = None) -> dict[str, bytes]:
    """Front, side and three-quarter PNGs of a Trimesh or Scene (``size`` px square).

    ``materials`` optionally maps a geometry name to ``(rgb 0..1, metallic)`` and wins over the
    geometry's own material (used when the model was loaded without materials)."""
    vertices, faces, rgb, metal = _collect(mesh, materials)
    if len(vertices) == 0 or len(faces) == 0:
        return {name: _blank(size) for name in VIEWS}
    return {name: _render(vertices, faces, rgb, metal, yaw, elev, size) for name, (yaw, elev) in VIEWS.items()}
