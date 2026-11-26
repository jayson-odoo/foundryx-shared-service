import json
import logging
from pathlib import Path

import httpx
import pytest

from planner3d_worker.client import Worker
from planner3d_worker.tests.fake_engines import FakeEngine, HogEngine, SleepEngine

TOKEN = "s3cr3t-token-value-xyz"
NAME = "mac-mini-1"
JOB = "6f1c2a3e-4b5d-4e7f-8a9b-0c1d2e3f4a5b"

INPUTS = {
    "model": [{"role": "photo", "name": "photo-1.png", "mime": "image/png", "size": 4, "sha256": "x"}],
    "render": [
        {"role": n, "name": f"{n}.png", "mime": "image/png", "size": 4, "sha256": "x"}
        for n in ("scene", "mask", "depth")
    ],
    "convert": [{"role": "model", "name": "model.glb", "mime": "model/gltf-binary", "size": 4, "sha256": "x"}],
}


class FakeSS:
    def __init__(self, kind="model", claim=True, heartbeat_status=200):
        self.kind, self.claim, self.heartbeat_status = kind, claim, heartbeat_status
        self.calls = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if path == "/planner3d/worker/claim":
            if not self.claim:
                return httpx.Response(204)
            return httpx.Response(200, json={
                "jobId": JOB, "kind": self.kind,
                "params": {"dimensionsMm": {"length": 1200, "width": 600, "height": 750}},
                "inputs": INPUTS[self.kind],
            })
        if "/inputs/" in path:
            return httpx.Response(200, content=b"\x89PNG data")
        if path.endswith("/heartbeat"):
            if self.heartbeat_status == 409:
                return httpx.Response(409, json={"code": "cancelled"})
            return httpx.Response(200, json={})
        if "/outputs/" in path:
            return httpx.Response(201, json={"name": path.rsplit("/", 1)[1], "size": 1, "sha256": "x"})
        if path.endswith("/finish"):
            return httpx.Response(200, json={"id": JOB})
        return httpx.Response(404)

    def outputs(self):
        return {r.url.path.rsplit("/", 1)[1]: r.url.params.get("role")
                for r in self.calls if r.method == "PUT" and "/outputs/" in r.url.path}

    def finish(self):
        fin = [r for r in self.calls if r.url.path.endswith("/finish")]
        return [json.loads(r.content) for r in fin]


def _worker(ss, tmp_path, engine=None, health=None, **kw):
    http = httpx.Client(transport=httpx.MockTransport(ss.handler), base_url="http://ss.test")
    return Worker(
        base_url="http://ss.test", token=TOKEN, name=NAME, engine=engine or FakeEngine(),
        http=http, work_dir=tmp_path, health=health or (lambda: (True, "")), **kw,
    )


def test_ac_s3_20_happy_model_job(tmp_path):
    ss = FakeSS("model")
    assert _worker(ss, tmp_path).run_once() == JOB
    claim = json.loads(ss.calls[0].content)
    assert claim == {"kinds": ["model", "render", "convert"]}
    outs = ss.outputs()
    cands = [n for n in outs if n.endswith(".glb")]
    assert sorted(cands) == ["candidate-1.glb", "candidate-2.glb", "candidate-3.glb"]
    assert all(outs[n] == "candidate" for n in cands)
    fin = ss.finish()
    assert len(fin) == 1 and fin[0]["status"] == "succeeded"
    assert fin[0]["gpuSeconds"] >= 0 and fin[0]["peakRssMb"] > 0


def test_ac_s3_20_idle_204_returns_none(tmp_path):
    ss = FakeSS(claim=False)
    assert _worker(ss, tmp_path).run_once() is None
    assert len(ss.calls) == 1 and not ss.finish()


def test_ac_s3_20_health_refuses_makes_no_http_call(tmp_path):
    ss = FakeSS()
    w = _worker(ss, tmp_path, health=lambda: (False, "swap too high"))
    assert w.run_once() is None
    assert ss.calls == []


def test_ac_s3_21_engine_exception_finishes_worker_failed(tmp_path):
    ss = FakeSS("model")
    _worker(ss, tmp_path, engine=FakeEngine(raise_in_run=True)).run_once()
    fin = ss.finish()
    assert len(fin) == 1 and fin[0]["status"] == "failed"
    assert fin[0]["error"]["code"] == "worker_failed"
    assert fin[0]["error"]["message"]


def test_ac_s3_21_memory_cap_finishes_memory_cap(tmp_path):
    ss = FakeSS("model")
    _worker(ss, tmp_path, engine=HogEngine(), rss_cap_mb=100, timeout_s=60).run_once()
    fin = ss.finish()
    assert fin[0]["status"] == "failed" and fin[0]["error"]["code"] == "memory_cap"


def test_ac_s3_21_timeout_finishes_timeout(tmp_path):
    ss = FakeSS("model")
    _worker(ss, tmp_path, engine=SleepEngine(), timeout_s=1).run_once()
    fin = ss.finish()
    assert fin[0]["status"] == "failed" and fin[0]["error"]["code"] == "timeout"


def test_ac_s3_25_convert_job_uploads_six_files(tmp_path):
    ss = FakeSS("convert")
    _worker(ss, tmp_path).run_once()
    outs = ss.outputs()
    assert set(outs) == {"model.glb", "model.gltf", "model.obj", "model.mtl", "model.fbx", "model.stl"}
    assert outs["model.glb"] == "model"
    assert all(v == "export" for k, v in outs.items() if k != "model.glb")
    assert ss.finish()[0]["status"] == "succeeded"


def test_ac_s3_26_render_job_uploads_render_and_diff(tmp_path):
    ss = FakeSS("render")
    _worker(ss, tmp_path).run_once()
    outs = ss.outputs()
    assert outs == {"render.png": "render", "diff.json": "diff_report"}
    assert ss.finish()[0]["status"] == "succeeded"


def test_ac_s3_20_every_call_carries_auth_headers(tmp_path):
    ss = FakeSS("model")
    _worker(ss, tmp_path).run_once()
    assert len(ss.calls) > 4
    for r in ss.calls:
        assert r.headers["authorization"] == f"Bearer {TOKEN}"
        assert r.headers["x-planner3d-worker"] == NAME


def test_ac_s3_20_token_never_logged(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    for kind in ("model", "convert"):
        _worker(FakeSS(kind), tmp_path).run_once()
    _worker(FakeSS("model"), tmp_path, engine=FakeEngine(raise_in_run=True)).run_once()
    text = "\n".join(r.getMessage() + str(r.args) + str(r.exc_text) for r in caplog.records)
    assert TOKEN not in text


def test_ac_s3_20_heartbeat_cancelled_stops_without_finish(tmp_path):
    ss = FakeSS("model", heartbeat_status=409)
    _worker(ss, tmp_path).run_once()
    assert any(r.url.path.endswith("/heartbeat") for r in ss.calls)
    assert ss.finish() == []
