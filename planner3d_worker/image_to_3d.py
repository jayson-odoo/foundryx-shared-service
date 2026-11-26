"""Image to 3D post-processing and TripoSR glue, ported from the proof's
``image_to_3d.py`` (PLANNER-3D-PROOF P1).

The pose and scale functions (``upright_and_forward``, ``scale_to_catalogue``)
are the proof's, unchanged, and need only numpy + trimesh. Everything that
needs torch, rembg or TripoSR is imported INSIDE the function that uses it, so
this module imports on a machine with no model stack.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
from PIL import Image


def _install_shims(triposr_src: Path) -> None:
    """Let TripoSR import in a sandbox with no Hugging Face and no compiler.

    * `torchmcubes` is a C++/CUDA extension. scikit-image does the same
      marching cubes on CPU from a wheel, so a small stand-in module is enough.
    * The image tokenizer asks Hugging Face for the DINO ViT-B/16 `config.json`
      only to learn the architecture. Those are the `ViTConfig` defaults, and
      the weights themselves are inside TripoSR's own checkpoint.
    """
    import torch
    from skimage import measure

    shim = types.ModuleType("torchmcubes")

    def marching_cubes(level: "torch.Tensor", threshold: float):
        verts, faces, _normals, _values = measure.marching_cubes(level.cpu().numpy(), threshold)
        # TripoSR swaps the axes back ([2, 1, 0]) because torchmcubes answers in
        # z, y, x. scikit-image answers in x, y, z, so hand it over pre-swapped.
        verts = np.ascontiguousarray(verts[:, [2, 1, 0]])
        return (
            torch.from_numpy(verts.astype(np.float32)),
            torch.from_numpy(faces.astype(np.int64)),
        )

    shim.marching_cubes = marching_cubes
    sys.modules["torchmcubes"] = shim

    sys.path.insert(0, str(triposr_src))
    import tsr.models.tokenizers.image as image_tokenizer
    from transformers import ViTConfig

    config_path = Path(triposr_src) / "_dino_vitb16_config.json"
    if not config_path.exists():
        ViTConfig(
            hidden_size=768,
            num_hidden_layers=12,
            num_attention_heads=12,
            intermediate_size=3072,
            image_size=224,
            patch_size=16,
            qkv_bias=True,
        ).to_json_file(config_path)
    image_tokenizer.hf_hub_download = lambda **_: str(config_path)


def cut_out(photo: Path, foreground_ratio: float) -> tuple[Image.Image, np.ndarray]:
    """Product on mid-grey, the framing TripoSR was trained on, plus its mask."""
    import rembg
    from tsr.utils import remove_background, resize_foreground

    session = rembg.new_session()
    rgba = remove_background(Image.open(photo).convert("RGB"), session)
    rgba = resize_foreground(rgba, foreground_ratio)
    array = np.asarray(rgba).astype(np.float32) / 255.0
    alpha = array[:, :, 3:4]
    rgb = array[:, :, :3] * alpha + (1 - alpha) * 0.5
    return Image.fromarray((rgb * 255).astype(np.uint8)), alpha[:, :, 0]


def load_model(weights: str, triposr_src: Path, device: str):
    """TripoSR on ``device``. ``weights`` is a local folder (config.yaml +
    model.ckpt) or a Hugging Face repo id (needs HF_TOKEN in the environment)."""
    _install_shims(Path(triposr_src))
    from tsr.system import TSR

    model = TSR.from_pretrained(str(weights), config_name="config.yaml", weight_name="model.ckpt")
    model.renderer.set_chunk_size(8192)
    model.to(device)
    return model


def reconstruct(model, image: Image.Image, mc_resolution: int, device: str):
    """The raw mesh straight out of the model (TripoSR frame, vertex colours)."""
    import torch

    with torch.no_grad():
        scene_codes = model([image], device=device)
    with torch.no_grad():
        return model.extract_mesh(scene_codes, True, resolution=mc_resolution)[0]


def clean_mesh(mesh, target_faces: int = 20000, smooth_iterations: int = 12):
    """Keep the biggest piece, decimate, fix winding, smooth the stair-steps."""
    import trimesh

    pieces = mesh.split(only_watertight=False)
    if len(pieces) > 1:
        mesh = max(pieces, key=lambda piece: len(piece.faces))
    if len(mesh.faces) > target_faces:
        colors = np.asarray(mesh.visual.vertex_colors)
        simplified = mesh.simplify_quadric_decimation(face_count=target_faces)
        from scipy.spatial import cKDTree

        _, nearest = cKDTree(mesh.vertices).query(simplified.vertices)
        simplified.visual.vertex_colors = colors[nearest]
        mesh = simplified
    # Marching cubes winds every triangle the same way: the mesh is either right
    # or inside-out. Signed volume tells which; one flip fixes it.
    if mesh.volume < 0:
        mesh.invert()
    trimesh.smoothing.filter_taubin(mesh, iterations=smooth_iterations)
    return mesh


def report(mesh, pose: dict, proportions: dict, dims_mm: dict, extra: dict | None = None) -> dict:
    """The JSON that travels beside a candidate GLB."""
    low, high = mesh.bounds
    return {
        "faces": int(len(mesh.faces)),
        "vertices": int(len(mesh.vertices)),
        "pose": pose,
        "size_m_w_h_d": [round(float(v), 4) for v in (high - low)],
        "catalogue_mm_w_h_d": [dims_mm["width"], dims_mm["height"], dims_mm["depth"]],
        **proportions,
        **(extra or {}),
    }


def upright_and_forward(mesh, width_mm: float, depth_mm: float, height_mm: float,
                        tilt_override_deg: float | None, yaw_override_deg: float | None):
    """Turn the raw mesh into the pose the room uses: Y up, front toward +Z.

    TripoSR rebuilds the object as the camera saw it: the photo's viewpoint is
    +X and up is +Z, so a product shot taken from above and to one side comes
    out tilted and turned by the photographer's angle. Two facts undo it:

    * Sanitaryware is boxy. Its tightest bounding box sits square to the
      product, so the box's axes are the product's own up, width and depth.
      The axis nearest the photo's up is up (nobody shoots a WC from below).
    * The catalogue knows the footprint. Of the two level axes, depth is the
      one that makes width : depth match the catalogue; when the footprint is
      near square (a round basin) the side that faced the camera is the front.

    When the model is too malformed for its box to mean anything, a person
    gives the tilt and turn instead (`--tilt-deg`, `--yaw-deg`), and the report
    says so.
    """
    import trimesh

    # TripoSR (x front, y left, z up) -> room (x right, y up, z front).
    to_room = np.array([[0, 1, 0, 0], [0, 0, 1, 0], [1, 0, 0, 0], [0, 0, 0, 1]], dtype=float)
    mesh.apply_transform(to_room)

    if tilt_override_deg is not None or yaw_override_deg is not None:
        tilt, yaw = tilt_override_deg or 0.0, yaw_override_deg or 0.0
        # Tilt about the camera's level axis (room X), then turn about up (Y).
        mesh.apply_transform(trimesh.transformations.rotation_matrix(np.radians(tilt), [1, 0, 0]))
        mesh.apply_transform(trimesh.transformations.rotation_matrix(np.radians(yaw), [0, 1, 0]))
        return mesh, {"method": "manual", "tilt_deg": tilt, "yaw_deg": yaw}

    if height_mm < 0.5 * min(width_mm, depth_mm):
        # A flat product (a countertop basin, a shower tray) has no boxy sides
        # for a bounding box to lock onto, but it has a simpler tell: it is at
        # its lowest when it is level. Undo the camera's downward look by
        # trying each tilt and keeping the one with the least height.
        points = np.asarray(mesh.convex_hull.vertices)

        def height_at(tilt_deg: float) -> float:
            tilt = np.radians(tilt_deg)
            return float(np.ptp(points[:, 1] * np.cos(tilt) - points[:, 2] * np.sin(tilt)))

        tilt_deg = float(min(np.arange(-70.0, 71.0, 1.0), key=height_at))
        mesh.apply_transform(trimesh.transformations.rotation_matrix(np.radians(tilt_deg), [1, 0, 0]))
        return mesh, {"method": "automatic (lowest when level)", "tilt_deg": tilt_deg, "yaw_deg": 0.0}

    to_box, extents = trimesh.bounds.oriented_bounds(mesh)
    axes = to_box[:3, :3]  # rows: the tight box's axes, in the room frame
    up_index = int(np.argmax(np.abs(axes[:, 1])))
    up = axes[up_index] * np.sign(axes[up_index, 1])
    tilt_deg = float(np.degrees(np.arccos(np.clip(up[1], -1, 1))))

    level = [index for index in range(3) if index != up_index]
    camera = np.array([0.0, 0.0, 1.0])
    target = np.log(width_mm / depth_mm)
    near_square = abs(target) < np.log(1.15)
    best = None
    for width_index, depth_index in (level, level[::-1]):
        front = axes[depth_index] * (1 if axes[depth_index] @ camera >= 0 else -1)
        ratio_error = abs(np.log(extents[width_index] / extents[depth_index]) - target)
        facing = float(front @ camera)
        score = -facing if near_square else ratio_error - 0.05 * facing
        if best is None or score < best[0]:
            best = (score, front)
    front = best[1]
    right = np.cross(up, front)  # keeps the model right-handed: never a mirror image
    rotation = np.eye(4)
    rotation[:3, :3] = np.stack([right, up, front])
    mesh.apply_transform(rotation)
    yaw_deg = float(np.degrees(np.arctan2(front[0], front[2])))
    return mesh, {"method": "automatic (tight bounding box)", "tilt_deg": round(tilt_deg, 1), "yaw_deg": round(yaw_deg, 1)}


def scale_to_catalogue(mesh, width_mm: float, depth_mm: float, height_mm: float):
    """Stretch the model's bounding box onto the catalogue's exact size, in metres.

    Per axis, not one uniform factor: the room is planned on the real footprint,
    so the model must fill exactly that box. How far the three factors differ is
    the model's proportion error, and it is reported rather than hidden.
    """
    low, high = mesh.bounds
    native = high - low
    target = np.array([width_mm, height_mm, depth_mm]) / 1000.0
    factors = target / native
    mesh.apply_translation(-(low + high) / 2)
    mesh.apply_scale(factors)
    # Feet on the floor, centred on the footprint: the origin the scene places by.
    mesh.apply_translation([0, target[1] / 2, 0])
    uniform = float(np.exp(np.mean(np.log(factors))))
    stretch = factors / uniform
    return mesh, {
        "native_bbox_ratio_w_h_d": [round(float(v / native[1]), 3) for v in native],
        "catalogue_ratio_w_h_d": [round(float(v / target[1]), 3) for v in target],
        "per_axis_stretch_w_h_d": [round(float(v), 3) for v in stretch],
        "max_stretch_pct": round(float(np.max(np.abs(stretch - 1)) * 100), 1),
    }
