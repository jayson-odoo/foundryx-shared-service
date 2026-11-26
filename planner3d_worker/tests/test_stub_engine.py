import numpy as np
import trimesh
from PIL import Image

from planner3d_worker.engines import stub

DIMS = {"lengthMm": 1200, "widthMm": 600, "heightMm": 750}


def _photo(tmp_path):
    p = tmp_path / "a.png"
    Image.fromarray(np.full((8, 8, 3), 120, dtype=np.uint8)).save(p)
    return p


def _gen(tmp_path, out, n=3):
    return stub.generate([_photo(tmp_path)], DIMS, out, n=n)


def test_ac_s3_22_candidate_names(tmp_path):
    for n in (2, 3):
        out = tmp_path / f"o{n}"
        out.mkdir()
        paths = _gen(tmp_path, out, n)
        assert [p.name for p in paths] == [f"candidate-{i}.glb" for i in range(1, n + 1)]
        assert all(p.exists() for p in paths)


def test_ac_s3_22_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    pa, pb = _gen(tmp_path, a), _gen(tmp_path, b)
    assert [p.read_bytes() for p in pa] == [p.read_bytes() for p in pb]


def test_ac_s3_24_bbox_y_up_metres_base_centre(tmp_path):
    out = tmp_path / "o"
    out.mkdir()
    for p in _gen(tmp_path, out):
        mesh = trimesh.load(p, force="mesh")
        lo, hi = mesh.bounds
        ext = hi - lo
        assert abs(ext[0] - 1.2) <= 0.001
        assert abs(ext[1] - 0.75) <= 0.001
        assert abs(ext[2] - 0.6) <= 0.001
        assert abs(lo[1]) <= 1e-6
        assert abs((lo[0] + hi[0]) / 2) <= 1e-6
        assert abs((lo[2] + hi[2]) / 2) <= 1e-6
