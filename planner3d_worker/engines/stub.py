"""Deterministic stub engine: box GLBs with the exact requested dimensions.

Y up, metres, origin at the base centre. No timestamps in the output, so the same
input always yields byte-identical files.
"""

from __future__ import annotations

from pathlib import Path

import trimesh


def generate(photos: list[Path], dims_mm: dict, out_dir: Path, n: int = 3) -> list[Path]:
    length = float(dims_mm["lengthMm"]) / 1000.0
    width = float(dims_mm["widthMm"]) / 1000.0
    height = float(dims_mm["heightMm"]) / 1000.0
    paths: list[Path] = []
    for i in range(1, n + 1):
        mesh = trimesh.creation.box(extents=(length, height, width))
        mesh.apply_translation((0.0, height / 2.0, 0.0))
        path = Path(out_dir) / f"candidate-{i}.glb"
        path.write_bytes(mesh.export(file_type="glb"))
        paths.append(path)
    return paths
