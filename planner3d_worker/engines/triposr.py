"""TripoSR engine (model jobs). Needs the model stack from
``requirements-model.txt``; every heavy import happens inside ``run``, which
executes in the capped child process.

Frames: the catalogue's ``length`` runs along the room X axis and ``width``
along Z, the same as the stub engine, so ``image_to_3d``'s width = length and
depth = width.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from planner3d_worker import image_to_3d

# (foreground_ratio, marching-cubes resolution): three different takes.
VARIANTS = [(0.85, 256), (0.75, 256), (0.90, 320)]
DEFAULT_WEIGHTS = "stabilityai/TripoSR"


def pick_device() -> str:
    import torch

    return "mps" if torch.backends.mps.is_available() else "cpu"


class TripoSREngine:
    kinds = ["model"]

    def __init__(self, n: int = 3, triposr_src: str | None = None, weights: str | None = None):
        self.n = min(max(n, 1), len(VARIANTS))
        self.triposr_src = triposr_src or os.environ.get(
            "PLANNER3D_TRIPOSR_SRC", str(Path.home() / "planner3d" / "triposr_src")
        )
        self.weights = weights or os.environ.get("PLANNER3D_TRIPOSR_WEIGHTS", DEFAULT_WEIGHTS)

    def run(self, kind: str, inputs: dict, params: dict, out_dir) -> list[tuple[str, str]]:
        if kind != "model":
            raise ValueError(f"TripoSR cannot run {kind}")
        if not os.environ.get("HF_TOKEN"):
            from planner3d_worker import keychain

            # Only this child process ever holds it; it is never printed or stored.
            os.environ["HF_TOKEN"] = keychain.hugging_face_token()
        dims = params["dimensionsMm"]
        length, width, height = float(dims["length"]), float(dims["width"]), float(dims["height"])
        photo = Path(inputs[sorted(inputs)[0]])
        device = pick_device()
        model = image_to_3d.load_model(self.weights, Path(self.triposr_src), device)

        out = Path(out_dir)
        produced: list[tuple[str, str]] = []
        for i, (ratio, mc) in enumerate(VARIANTS[: self.n], start=1):
            image, _ = image_to_3d.cut_out(photo, ratio)
            mesh = image_to_3d.reconstruct(model, image, mc, device)
            mesh = image_to_3d.clean_mesh(mesh)
            mesh, pose = image_to_3d.upright_and_forward(mesh, length, width, height, None, None)
            mesh, proportions = image_to_3d.scale_to_catalogue(mesh, length, width, height)
            glb = out / f"candidate-{i}.glb"
            mesh.export(glb)
            rep = image_to_3d.report(
                mesh,
                pose,
                proportions,
                {"width": length, "height": height, "depth": width},
                {"foreground_ratio": ratio, "mc_resolution": mc, "device": device},
            )
            (out / f"candidate-{i}.json").write_text(json.dumps(rep, indent=2) + "\n")
            produced += [(glb.name, "candidate"), (f"candidate-{i}.json", "report")]
        return produced
