"""Deterministic stub engine: box GLBs with the exact requested dimensions.

Y up, metres, origin at the base centre. No timestamps in the output, so the same
input always yields byte-identical files.
"""

from __future__ import annotations

import json
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


class StubEngine:
    """Model jobs on the CPU, no model: deterministic boxes of the right size."""

    kinds = ["model"]

    def run(self, kind: str, inputs: dict, params: dict, out_dir) -> list[tuple[str, str]]:
        if kind != "model":
            raise ValueError(f"stub engine cannot run {kind}")
        dims = params["dimensionsMm"]
        paths = generate(
            [Path(p) for p in inputs.values()],
            {"lengthMm": dims["length"], "widthMm": dims["width"], "heightMm": dims["height"]},
            Path(out_dir),
        )
        produced: list[tuple[str, str]] = []
        for path in paths:
            report = path.with_suffix(".json")
            report.write_text(json.dumps({"engine": "stub", "dimensionsMm": dims}) + "\n")
            produced += [(path.name, "candidate"), (report.name, "report")]
        return produced
