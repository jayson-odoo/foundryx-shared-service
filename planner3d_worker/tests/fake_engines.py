"""Module-level engines (picklable for a spawned child)."""
import time
from pathlib import Path


class FakeEngine:
    kinds = ["model", "render", "convert"]

    def __init__(self, n=3, raise_in_run=False):
        self.n = n
        self.raise_in_run = raise_in_run

    def run(self, kind, inputs, params, out_dir):
        if self.raise_in_run:
            raise RuntimeError("boom")
        out = Path(out_dir)
        for p in inputs.values():
            assert Path(p).exists()
        if kind == "model":
            res = []
            for i in range(1, self.n + 1):
                (out / f"candidate-{i}.glb").write_bytes(b"glTF" + bytes([i]))
                (out / f"candidate-{i}.json").write_bytes(b"{}")
                res += [(f"candidate-{i}.glb", "candidate"), (f"candidate-{i}.json", "report")]
            return res
        if kind == "render":
            (out / "render.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            (out / "diff.json").write_bytes(b"{}")
            return [("render.png", "render"), ("diff.json", "diff_report")]
        names = ["model.glb", "model.gltf", "model.obj", "model.mtl", "model.fbx", "model.stl"]
        for n in names:
            (out / n).write_bytes(b"x")
        return [(n, "model" if n == "model.glb" else "export") for n in names]


class HogEngine(FakeEngine):
    def run(self, kind, inputs, params, out_dir):
        blocks = []
        for _ in range(30):
            b = bytearray(10 * 1024 * 1024)
            for i in range(0, len(b), 4096):
                b[i] = 1
            blocks.append(b)
            time.sleep(0.02)
        time.sleep(5)
        return []


class SleepEngine(FakeEngine):
    def run(self, kind, inputs, params, out_dir):
        time.sleep(30)
        return []
