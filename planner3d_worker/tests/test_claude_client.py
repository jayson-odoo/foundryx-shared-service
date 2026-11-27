"""claude-procedural red tests: the worker loop maps EngineFailure codes to job error codes."""
import json

import pytest

from planner3d_worker.engines.claude_procedural import EngineFailure
from planner3d_worker.tests.fake_engines import FakeEngine
from planner3d_worker.tests.test_client import FakeSS, _worker


class CodeEngine(FakeEngine):
    """Module-level so the capped child process can unpickle it."""

    code = "spend_cap"

    def run(self, kind, inputs, params, out_dir):
        raise EngineFailure(self.code, "US$700 cap reached")


class SandboxEngine(CodeEngine):
    code = "sandbox_unavailable"


@pytest.mark.parametrize("engine,code", [(CodeEngine(), "spend_cap"), (SandboxEngine(), "sandbox_unavailable")])
def test_engine_failure_code_becomes_the_job_error_code(tmp_path, engine, code):
    ss = FakeSS("model")
    _worker(ss, tmp_path, engine=engine).run_once()
    fin = ss.finish()
    assert len(fin) == 1 and fin[0]["status"] == "failed"
    assert fin[0]["error"]["code"] == code
    assert 0 < len(fin[0]["error"]["message"]) <= 200
    assert "US$700" not in json.dumps(fin[0])


def test_generic_errors_include_the_new_codes():
    from planner3d_worker.client import GENERIC_ERRORS

    for code in ("spend_cap", "generation_failed", "no_api_key", "sandbox_unavailable"):
        assert code in GENERIC_ERRORS
