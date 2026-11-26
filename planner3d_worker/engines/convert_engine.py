"""Convert engine: one GLB in, the six export files out."""

from __future__ import annotations

from pathlib import Path

from planner3d_worker.convert import convert_glb


class ConvertEngine:
    kinds = ["convert"]

    def run(self, kind: str, inputs: dict, params: dict, out_dir) -> list[tuple[str, str]]:
        if kind != "convert":
            raise ValueError(f"convert engine cannot run {kind}")
        result = convert_glb(Path(inputs["model.glb"]), Path(out_dir))
        return [(name, "model" if name == "model.glb" else "export") for name in result]
