"""External Code-runner contract + escape suite (AC-SAR-63..67, 70).

These tests exercise the REAL subprocess jail (``code_runner.sandbox``), the
same code the deployed runner container executes. They need no HTTP server.
"""
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request

import pytest

from code_runner import RUNNER_VERSION
from code_runner.policy import CAPABILITIES, validate_source
from code_runner.sandbox import Limits, execute

FAST = Limits(wall_seconds=4.0, cpu_seconds=2)


def _run(source, inputs=None, limits=FAST):
    return execute(source, inputs or {}, limits)


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The reviewer's escape: a generator exposes its frame, the frame chain walks
# out of the exec'd module into the harness, whose real builtins still carried
# ``__import__``. Every hop is now closed twice (static policy + runtime).
FRAME_WALK_ESCAPE = (
    "holder = {}\n"
    "def grab(_):\n"
    "    holder['f'] = g.gi_frame.f_back\n"
    "    return 1\n"
    "g = (grab(x) for x in [0]); next(g)\n"
    "imp = holder['f'].f_back.f_builtins['__import__']\n"
    "os = imp('os')\n"
    "result = {'cwd': os.getcwd()}\n"
)


def _run_unpoliced(source, inputs=None, limits=FAST):
    """Run the REAL harness child with the static policy stubbed out, so the
    runtime denial layer is exercised on its own (defense in depth)."""
    bootstrap = (
        "import sys\n"
        f"sys.path.insert(0, {_ROOT!r})\n"
        "import code_runner.policy as policy\n"
        "policy.validate_source = lambda source: []\n"
        "from code_runner.harness import main\n"
        "sys.exit(main())\n"
    )
    job = json.dumps({"source": source, "input": inputs or {}, "consoleLimit": 4096, "outputLimit": 65536})
    proc = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", bootstrap],
        input=job.encode("utf-8"),
        capture_output=True,
        timeout=limits.wall_seconds,
        env={},
        cwd="/",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    return json.loads(proc.stdout.decode("utf-8", "replace").strip().splitlines()[-1])


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
        FRAME_WALK_ESCAPE,
        "g = (x for x in [0])\nresult = {'f': g.gi_code}",
        "def f():\n    return 1\nresult = {'g': f.f_globals}",
        "def f():\n    return 1\nresult = {'k': f['__code__']}",
        "result = {'m': int.mro()}",
        "result = {'s': '{0.__class__}'.format(input)}",
        "result = {'s': '{0.__class__}'.format_map({'0': input})}",
    ],
)
def test_policy_rejects_imports_reflection_io_and_missing_result(source):
    assert validate_source(source)
    out = _run(source)
    assert not out.ok and out.termination == "policy"


def test_frame_walk_escape_is_closed_at_runtime_without_the_policy():
    # Regression for the review blocker (AC-SAR-64): even with the static
    # policy gone, the walked-to builtins carry no ``__import__``.
    out = _run_unpoliced(FRAME_WALK_ESCAPE)
    assert not out["ok"] and out["termination"] == "error"
    assert "cwd" not in json.dumps(out.get("result"))
    assert "not available" in out["error"]


# The runtime _harden() layer is DEFENSE IN DEPTH, not the boundary: it closes
# the CASUAL bypass routes (neutered builtins, a frame walk to
# f_builtins['__import__'], the sys.meta_path re-import). It does NOT make an
# in-process interpreter safe against arbitrary bytecode - the static policy is
# the gate (see test_static_policy_is_the_gate_for_reflection_escapes below).
@pytest.mark.parametrize(
    "source",
    [
        "import os\nresult = {'env': dict(os.environ)}",
        "result = {'x': __import__('os').getcwd()}",
        "result = {'x': open('/etc/passwd').read()}",
        "exec('import os')\nresult = {}",
        "result = {'x': eval('1')}",
        "result = {'x': compile('1', 'x', 'eval')}",
        "holder = {}\n"
        "def grab(_):\n"
        "    holder['f'] = g.gi_frame.f_back\n"
        "    return 1\n"
        "g = (grab(x) for x in [0]); next(g)\n"
        "mods = holder['f'].f_back.f_globals\n"
        "result = {'leak': sorted(k for k in mods if k in ('sys', 'os', 'io', 'json', 'types', 'subprocess', 'socket'))}",
    ],
)
def test_hardening_closes_the_casual_bypass_routes(source):
    out = _run_unpoliced(source)
    if out["ok"]:
        # The only permitted "success": the walked-to globals carry no module.
        assert out["result"] == {"leak": []}
    else:
        assert out["termination"] == "error"
        assert any(m in out["error"] for m in ("not available", "not defined", "not found"))


# The subclass-walk to BuiltinImporter (object.__subclasses__() ->
# BuiltinImporter.load_module('posix')) is the route _harden CANNOT close in
# process. This test pins the honest security model: the STATIC POLICY blocks
# it (that is the gate), and - deliberately - the runtime layer alone does not,
# so no one may re-add a "runtime layer holds even if the policy slipped" claim.
_SUBCLASS_WALK_ESCAPE = (
    "subs = ().__class__.__base__.__subclasses__()\n"
    "posix = None\n"
    "for c in subs:\n"
    "    if c.__name__ == 'BuiltinImporter':\n"
    "        posix = c.load_module('posix')\n"
    "        break\n"
    "result = {'cwd': posix.getcwd()}\n"
)


def test_static_policy_is_the_gate_for_reflection_escapes():
    # Production path: the static policy rejects the dunder walk outright.
    issues = validate_source(_SUBCLASS_WALK_ESCAPE)
    assert any("__subclasses__" in i for i in issues)
    out = _run(_SUBCLASS_WALK_ESCAPE)
    assert not out.ok and out.termination == "policy"


def test_runtime_layer_alone_does_not_stop_the_subclass_walk():
    # With the policy stubbed, _harden's meta_path clearing is not enough: the
    # importer CLASS is still reachable via __subclasses__. This asserts the
    # DOCUMENTED limitation - the static policy is what makes production safe,
    # not the runtime layer. If a future change makes _harden actually block
    # this, tighten the assertion; do NOT claim the runtime layer is a boundary.
    out = _run_unpoliced(_SUBCLASS_WALK_ESCAPE)
    assert out["ok"] and out["result"] == {"cwd": "/"}


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
    # A real reach probe: with the policy stubbed, the child still has no
    # environment, no os/socket module and no importer to fetch one.
    out = _run_unpoliced(
        "holder = {}\n"
        "def grab(_):\n"
        "    holder['f'] = g.gi_frame.f_back\n"
        "    return 1\n"
        "g = (grab(x) for x in [0]); next(g)\n"
        "b = holder['f'].f_back.f_builtins\n"
        "names = ['__import__', 'open', 'exec', 'eval', 'compile']\n"
        "probe = {}\n"
        "for n in names:\n"
        "    try:\n"
        "        b[n]('os')\n"
        "        probe[n] = 'reached'\n"
        "    except Exception as exc:\n"
        "        probe[n] = str(exc)\n"
        "result = {'probe': probe}\n"
    )
    assert out["ok"], out
    assert all("not available" in v for v in out["result"]["probe"].values()), out["result"]
    # Sanity: the allowed surface still works end to end through the policy.
    out2 = _run("result = {'x': input}", {"k": "v"})
    assert out2.ok and out2.result == {"x": {"k": "v"}}


def test_capabilities_list_is_stable():
    assert len(CAPABILITIES) == 5 and any("No imports" in row for row in CAPABILITIES)
    assert json.dumps(list(CAPABILITIES))


def test_healthcheck_reads_listen_state_without_dialing(tmp_path):
    # The container probe must not connect() (seccomp denies it): it reads
    # /proc/net/tcp for a LISTEN (0A) row on the runner port.
    from code_runner.healthcheck import _listening

    table = tmp_path / "tcp"
    table.write_text(
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        "   0: 00000000:1F4B 00000000:0000 0A 00000000:00000000 00:00000000 00000000 10001        0 1 0 0 0\n"
        "   1: 0100007F:1F4C 00000000:0000 01 00000000:00000000 00:00000000 00000000 10001        0 1 0 0 0\n"
    )
    assert _listening(8011, tables=(str(table),))
    assert not _listening(8012, tables=(str(table),))  # established, not listening
    assert not _listening(8011, tables=(str(tmp_path / "missing"),))


def _serve(env):
    from http.server import ThreadingHTTPServer

    from code_runner.server import RunnerConfig, make_handler

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(RunnerConfig(env)))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def test_health_requires_the_bearer_when_a_token_is_configured():
    from app.workflow_engine.code_runner import HttpCodeRunnerClient

    httpd, base = _serve({"CODE_RUNNER_TOKEN": "secret"})
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"{base}/health", timeout=3)
        assert exc.value.code == 401
        # The backend probe sends its token: a mismatch is "unhealthy" (surfaces
        # at publish as the runner warning), a match is healthy.
        assert HttpCodeRunnerClient(base, "wrong").health() is False
        assert HttpCodeRunnerClient(base, "").health() is False
        assert HttpCodeRunnerClient(base, "secret").health() is True
    finally:
        httpd.shutdown()
        httpd.server_close()
    # Local dev (anonymous, no token) keeps the bare probe working.
    httpd, base = _serve({"CODE_RUNNER_ALLOW_ANONYMOUS": "1"})
    try:
        with urllib.request.urlopen(f"{base}/health", timeout=3) as res:
            assert res.status == 200
    finally:
        httpd.shutdown()
        httpd.server_close()
