import shutil

import pytest
import trimesh

from planner3d_worker.convert import ConvertError, convert_glb

NAMES = {"model.glb", "model.gltf", "model.obj", "model.mtl", "model.fbx", "model.stl"}
needs_assimp = pytest.mark.skipif(shutil.which("assimp") is None, reason="assimp CLI not installed")


def _glb(tmp_path):
    p = tmp_path / "in.glb"
    trimesh.creation.box(extents=(1.0, 0.5, 0.25)).export(p)
    return p


@needs_assimp
def test_ac_s3_25_writes_six_files(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    res = convert_glb(_glb(tmp_path), out)
    assert set(res) == NAMES
    assert all(p.exists() and p.stat().st_size > 0 for p in res.values())


@needs_assimp
@pytest.mark.parametrize("name", ["model.gltf", "model.obj", "model.stl"])
def test_ac_s3_25_reopen_keeps_triangles(tmp_path, name):
    out = tmp_path / "out"
    out.mkdir()
    res = convert_glb(_glb(tmp_path), out)
    src = trimesh.load(tmp_path / "in.glb", force="mesh")
    again = trimesh.load(res[name], force="mesh")
    assert len(again.faces) == len(src.faces)


@needs_assimp
def test_ac_s3_25_fbx_magic(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    res = convert_glb(_glb(tmp_path), out)
    head = res["model.fbx"].read_bytes()[:64]
    assert head.startswith(b"Kaydara FBX Binary") or b"FBX" in head


def test_ac_s3_25_missing_assimp_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda *a, **k: None)
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ConvertError, match="fbx_unavailable"):
        convert_glb(_glb(tmp_path), out)
