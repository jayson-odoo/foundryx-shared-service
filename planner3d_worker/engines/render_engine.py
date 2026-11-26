"""Render engine. Generation is a STUB for now (the scene, blurred); a real
image model replaces ``_generate`` later. The product pixels are pasted back by
``render_only.composite``, so the result keeps them byte for byte either way."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from planner3d_worker import render_only

BLUR_RADIUS = 6


def _generate(scene: Image.Image) -> Image.Image:
    return scene.filter(ImageFilter.GaussianBlur(BLUR_RADIUS))


class RenderEngine:
    kinds = ["render"]

    def run(self, kind: str, inputs: dict, params: dict, out_dir) -> list[tuple[str, str]]:
        if kind != "render":
            raise ValueError(f"render engine cannot run {kind}")
        out = Path(out_dir)
        scene_path, mask_path = Path(inputs["scene.png"]), Path(inputs["mask.png"])
        scene = Image.open(scene_path).convert("RGB")
        generated = _generate(scene)
        mask = render_only._load_mask(mask_path)
        final = render_only.composite(np.asarray(scene), np.asarray(generated), mask)
        render_path = out / "render.png"
        Image.fromarray(final).save(render_path)
        report = render_only.verify_saved(scene_path, render_path, mask_path)
        report["mask_rule"] = render_only.MASK_RULE
        (out / "diff.json").write_text(json.dumps(report, indent=2) + "\n")
        return [("render.png", "render"), ("diff.json", "diff_report")]
