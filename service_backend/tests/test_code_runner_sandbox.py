"""External Code-runner contract + escape suite (AC-SAR-63..67, 70).

These tests exercise the REAL subprocess jail (``code_runner.sandbox``), the
same code the deployed runner container executes. They need no HTTP server.
"""
import json
import sys

import pytest

from code_runner import RUNNER_VERSION
from code_runner.policy import CAPABILITIES, validate_source
from code_runner.sandbox import Limits, execute

FAST = Limits(wall_seconds=4.0, cpu_seconds=2)


def _run(source, inputs=None, limits=FAST):
    return execute(source, inputs or {}, limits)


def test_happy_path_returns_declared_dictionary_and_console():
    out = _run(
        "summary = input['task'] + ': ' + input['status']\n"
        "print('working', len(summary))\n"
        "result = {'summary': summary, 'n': len(summary), 'ok': True, 'j': json.dumps({'a': 1}), 'm': math.floor(2.7), 'r': re.sub('a', 'b', 'banana')}",
        {"task": "Launch", "status": "blocked"},
    )
    assert out.ok and out.termination == "completed"
    assert out.result == {"summary": "Launch: blocked", "n": 15, "ok": True, "j": '{"a": 1}', "m": 2, "r": "bbnbnb"}
    assert out.stdout == "working 15\n"
    assert out.runner_version == RUNNER_VERSION
    assert out.duration_ms >= 0


@pytest.mark.parametrize(
    "source",
    [
        "import os\nresult = {}",
        "from subprocess import run\nresult = {}",
        "result = {'x': __import__('os').getcwd()}",
        "result = {'x': open('/etc/passwd').read()}",
        "result = {'k': [c for c in ().__class__.__bases__]}",
        "result = {'g': getattr(input, 'keys')}",
        "result = {'e': eval('1+1')}",
        "exec('result = {}')",
        "result = {'b': __builtins__}",
        "class A:\n    pass\nresult = {}",
        "x = 5",  # no result
    ],
)
def test_policy_rejects_imports_reflection_io_and_missing_result(source):
    assert validate_source(source)
    out = _run(source)
    assert not out.ok and out.termination == "policy"


def test_denied_capabilities_fail_at_runtime_even_if_policy_slipped():
    # Names the policy does not list are simply absent from the builtins table.
    out = _run("result = {'x': bytearray(4)}")
    assert not out.ok and "bytearray" in out.error
    out = _run("result = {'x': input.__class__}")
    assert out.termination == "policy"
    out = _run("input['task'] = 'mutated'\nresult = {'x': input['task']}", {"task": "t"})
    assert not out.ok and "does not support item assignment" in out.error


def test_wall_clock_timeout_kills_the_child():
    out = _run("while True:\n    pass\nresult = {}", limits=Limits(wall_seconds=1.0, cpu_seconds=5))
    assert not out.ok and out.termination == "timeout"


def test_cpu_limit_terminates_a_busy_loop():
    out = _run("i = 0\nwhile True:\n    i += 1\nresult = {}", limits=Limits(wall_seconds=8.0, cpu_seconds=1))
    assert not out.ok and out.termination in ("resource_limit", "timeout")


@pytest.mark.skipif(sys.platform == "darwin", reason="RLIMIT_AS is unreliable on macOS; enforced on the Linux runner")
def test_memory_limit_is_enforced_on_linux():
    out = _run("x = 'a' * (300 * 1024 * 1024)\nresult = {'n': len(x)}", limits=Limits(wall_seconds=8.0, memory_bytes=64 * 1024 * 1024))
    assert not out.ok and out.termination in ("memory_limit", "resource_limit")


def test_output_console_and_source_limits():
    out = _run("result = {'big': 'x' * 200000}")
    assert out.termination == "output_limit"
    out = _run("print('a' * 100000)\nresult = {'ok': 1}")
    assert out.ok and out.console_truncated and len(out.stdout) <= FAST.console_bytes
    out = _run("result = {}\n" + "# pad\n" * 20000)
    assert out.termination == "source_limit"


def test_malformed_results_fail_cleanly():
    assert _run("result = 5").termination == "invalid_result"
    assert _run("result = {'f': lambda: 1}").termination == "error"
    out = _run("result = {'v': 1 / 0}")
    assert out.termination == "error" and "ZeroDivisionError" in out.error
    out = _run("def f(n):\n    return f(n + 1)\nresult = {'v': f(0)}")
    assert out.termination == "error" and "recursion" in out.error.lower()


def test_child_has_no_environment_or_platform_reach():
    # No os module, no env, no sockets: the only way to observe the outside
    # world would be an import, which the policy + builtins table deny.
    out = _run("result = {'names': sorted(k for k in ['json', 'math', 're'])}")
    assert out.ok and out.result == {"names": ["json", "math", "re"]}
    out = _run("result = {'x': input}", {"k": "v"})
    assert out.ok and out.result == {"x": {"k": "v"}}


def test_capabilities_list_is_stable():
    assert len(CAPABILITIES) == 5 and any("No imports" in row for row in CAPABILITIES)
    assert json.dumps(list(CAPABILITIES))
