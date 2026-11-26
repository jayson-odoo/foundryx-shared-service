"""Follow-up red tests: claim and input validation, base url scheme, short error text."""
import json
import logging
import uuid

import httpx
import pytest

from planner3d_worker.client import Worker
from planner3d_worker.tests.fake_engines import FakeEngine, PathMessageEngine
from planner3d_worker.tests.test_client import INPUTS, NAME, TOKEN, FakeSS, _worker


class OddClaimSS(FakeSS):
    """Claim answers with a caller-chosen job id and input names."""

    def __init__(self, job_id=None, names=None):
        super().__init__("model")
        self.job_id = job_id or str(uuid.uuid4())
        self.names = names

    def handler(self, request):
        if request.url.path == "/planner3d/worker/claim":
            self.calls.append(request)
            inputs = INPUTS["model"]
            if self.names is not None:
                inputs = [{**inputs[0], "name": n} for n in self.names]
            return httpx.Response(200, json={
                "jobId": self.job_id, "kind": "model", "params": {}, "inputs": inputs,
            })
        return super().handler(request)

    def downloads(self):
        return [r for r in self.calls if "/inputs/" in r.url.path]


@pytest.mark.parametrize("bad_id", ["/tmp/x", "../x", "not-a-uuid", "a/b"])
def test_claim_with_a_job_id_that_is_not_a_uuid_is_ignored(tmp_path, caplog, bad_id):
    work = tmp_path / "work"
    work.mkdir()
    outside = tmp_path / "x"
    ss = OddClaimSS(job_id=bad_id)
    caplog.set_level(logging.WARNING)
    assert _worker(ss, work).run_once() is None
    assert ss.downloads() == []
    assert ss.finish() == []
    assert any(r.levelno >= logging.WARNING for r in caplog.records)
    assert not outside.exists()
    assert list(tmp_path.iterdir()) == [work]


def test_claim_with_a_uuid_job_id_proceeds_control(tmp_path):
    ss = OddClaimSS()
    assert _worker(ss, tmp_path).run_once() == ss.job_id
    assert ss.finish()[0]["status"] == "succeeded"


@pytest.mark.parametrize("bad_name", ["../evil.png", "a/b.png", "x..y/../z", "sp ace.png", "/abs.png", "bad\x00.png"])
def test_input_names_outside_the_safe_pattern_fail_the_job_as_bad_input(tmp_path, bad_name):
    work = tmp_path / "work"
    work.mkdir()
    ss = OddClaimSS(names=[bad_name])
    _worker(ss, work).run_once()
    fin = ss.finish()
    assert len(fin) == 1 and fin[0]["status"] == "failed"
    assert fin[0]["error"]["code"] == "bad_input"
    assert ss.downloads() == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["work"]


def test_double_dot_inside_an_otherwise_safe_name_is_refused(tmp_path):
    ss = OddClaimSS(names=["a..b.png"])
    _worker(ss, tmp_path).run_once()
    assert ss.finish()[0]["error"]["code"] == "bad_input"


def _make(url):
    return Worker(base_url=url, token=TOKEN, name=NAME, engine=FakeEngine(),
                  http=httpx.Client(), work_dir=None, health=lambda: (True, ""))


def test_plain_http_to_a_remote_host_is_refused():
    with pytest.raises(ValueError):
        _make("http://example.com")


@pytest.mark.parametrize("url", [
    "http://localhost", "http://localhost:8002", "http://127.0.0.1:8002", "http://testserver",
    "https://example.com", "https://chat.example.org/",
])
def test_https_and_local_http_base_urls_are_allowed(url):
    _make(url)


def test_engine_error_text_is_not_sent_in_the_finish_body(tmp_path):
    ss = FakeSS("model")
    _worker(ss, tmp_path, engine=PathMessageEngine()).run_once()
    fin = ss.finish()
    assert fin[0]["error"]["code"] == "worker_failed"
    body = json.dumps(fin[0])
    assert "/Users/someone" not in body and "model.bin" not in body
    assert 0 < len(fin[0]["error"]["message"]) <= 200
