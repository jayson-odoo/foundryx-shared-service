"""Software z-buffer rasteriser for the render-compare loop (plan
planner3d-claude-procedural-engine, D7).

numpy + Pillow only, orthographic, flat shaded, light grey on white. Headless and
deterministic: the same mesh gives the same PNG bytes. glTF frame in: Y up, front
faces +Z, length along X.
"""

from __future__ import annotations

import io
import math

import numpy as np
import trimesh
from PIL import Image

BACKGROUND = 255
# (yaw about Y in degrees, elevation in degrees): front looks down -Z, side down -X.
VIEWS = {"front": (0.0, 8.0), "side": (90.0, 8.0), "three_quarter": (35.0, 22.0)}
LIGHT = np.array([0.35, 0.55, 0.75])
LIGHT = LIGHT / np.linalg.norm(LIGHT)


def _rotation(yaw_deg: float, elev_deg: float) -> np.ndarray:
    """World -> camera: camera x right, y up, z toward the viewer."""
    yaw, elev = math.radians(yaw_deg), math.radians(elev_deg)
    ry = np.array([[math.cos(yaw), 0, -math.sin(yaw)], [0, 1, 0], [math.sin(yaw), 0, math.cos(yaw)]])
    rx = np.array([[1, 0, 0], [0, math.cos(elev), -math.sin(elev)], [0, math.sin(elev), math.cos(elev)]])
    return rx @ ry


def _png(gray: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(gray, "L").convert("RGB").save(buf, "PNG", optimize=False)
    return buf.getvalue()


def _blank(size: int) -> bytes:
    return _png(np.full((size, size), BACKGROUND, dtype=np.uint8))


def _render(vertices: np.ndarray, faces: np.ndarray, yaw: float, elev: float, size: int) -> bytes:
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
    facing = np.abs(cam_n[:, 2])  # two sided: open meshes still read
    lit = np.abs(np.einsum("nj,j->n", cam_n, LIGHT))
    shade = (0.30 + 0.45 * lit + 0.15 * facing).clip(0.0, 1.0)
    colour = (60 + shade * 170).astype(np.uint8)

    image = np.full((size, size), BACKGROUND, dtype=np.uint8)
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
    return _png(image)


def render_views(mesh: trimesh.Trimesh, size: int = 512) -> dict[str, bytes]:
    """Front, side and three-quarter PNGs of ``mesh`` (``size`` px square)."""
    vertices = np.asarray(getattr(mesh, "vertices", np.zeros((0, 3))), dtype=float)
    faces = np.asarray(getattr(mesh, "faces", np.zeros((0, 3), dtype=int)), dtype=np.int64)
    if len(vertices) == 0 or len(faces) == 0:
        return {name: _blank(size) for name in VIEWS}
    return {name: _render(vertices, faces, yaw, elev, size) for name, (yaw, elev) in VIEWS.items()}
