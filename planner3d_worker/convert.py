"""Convert a GLB into the six export formats (glb, gltf, obj+mtl, fbx, stl)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import trimesh

FBX_FORMAT_ID = "fbx"  # binary FBX; "fbxa" is the ASCII variant
ASSIMP_TIMEOUT_S = 120


class ConvertError(Exception):
    pass


def convert_glb(glb_path: Path, out_dir: Path) -> dict[str, Path]:
    glb_path, out_dir = Path(glb_path), Path(out_dir)
    assimp = shutil.which("assimp")
    if assimp is None:
        raise ConvertError("fbx_unavailable")

    result: dict[str, Path] = {}

    glb_out = out_dir / "model.glb"
    shutil.copyfile(glb_path, glb_out)
    result["model.glb"] = glb_out

    scene = trimesh.load(glb_path, force="scene")

    gltf_out = out_dir / "model.gltf"
    files = scene.export(file_type="gltf")
    gltf_out.write_bytes(files["model.gltf"] if "model.gltf" in files else next(iter(files.values())))
    # embed external buffers as data URIs so the .gltf is a single self-contained file
    _embed_gltf(gltf_out, files)
    result["model.gltf"] = gltf_out

    obj_out = out_dir / "model.obj"
    obj_text = scene.export(file_type="obj", include_texture=False, mtl_name="model.mtl")
    if isinstance(obj_text, tuple):  # older trimesh
        obj_text = obj_text[0]
    if isinstance(obj_text, dict):
        obj_out.write_bytes(obj_text["model.obj"] if "model.obj" in obj_text else next(iter(obj_text.values())))
        mtl = obj_text.get("model.mtl", b"newmtl material_0\nKd 0.8 0.8 0.8\n")
    else:
        obj_out.write_text(obj_text if isinstance(obj_text, str) else obj_text.decode())
        mtl = b"newmtl material_0\nKd 0.8 0.8 0.8\n"
    mtl_out = out_dir / "model.mtl"
    mtl_out.write_bytes(mtl if isinstance(mtl, bytes) else mtl.encode())
    result["model.obj"] = obj_out
    result["model.mtl"] = mtl_out

    stl_out = out_dir / "model.stl"
    mesh = trimesh.load(glb_path, force="mesh")
    stl_out.write_bytes(mesh.export(file_type="stl"))
    result["model.stl"] = stl_out

    fbx_out = out_dir / "model.fbx"
    try:
        proc = subprocess.run(
            [assimp, "export", str(glb_path), str(fbx_out), f"-f{FBX_FORMAT_ID}"],
            capture_output=True,
            text=True,
            timeout=ASSIMP_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise ConvertError("fbx_timeout") from exc
    if proc.returncode != 0 or not fbx_out.exists() or fbx_out.stat().st_size == 0:
        raise ConvertError(f"fbx_failed: {(proc.stderr or proc.stdout).strip()[:300]}")
    result["model.fbx"] = fbx_out
    return result


def _embed_gltf(gltf_out: Path, files: dict) -> None:
    import base64
    import json

    doc = json.loads(gltf_out.read_text())
    for buf in doc.get("buffers", []):
        uri = buf.get("uri")
        if uri and not uri.startswith("data:") and uri in files:
            data = base64.b64encode(files[uri]).decode()
            buf["uri"] = f"data:application/octet-stream;base64,{data}"
    gltf_out.write_text(json.dumps(doc))
