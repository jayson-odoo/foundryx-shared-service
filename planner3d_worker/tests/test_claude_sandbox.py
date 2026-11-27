"""claude-procedural red tests: sandbox for model-written code (D6).

``run_script(src, work_dir, limits, check=True)``: the AST pre-check is defence in
depth only; the real isolation tests pass ``check=False`` so the OS sandbox itself is
what is under test (``check`` is a contract addition made by the tester).
"""
import json
import textwrap
from pathlib import Path

import pytest

from planner3d_worker.claude import sandbox
from planner3d_worker.claude.sandbox import Limits, SandboxUnavailable, ScriptRejected, check_script, run_script

needs_sandbox = pytest.mark.skipif(not sandbox.available(), reason="macOS sandbox-exec not available")

CLEAN = textwrap.dedent(
    """
    import json
    import math
    import numpy as np
    import trimesh
    mesh = trimesh.creation.box(extents=(1.0, 0.5, 0.4))
    mesh.export("model.glb")
    """
)


@pytest.mark.parametrize(
    "src",
    [
        "import subprocess\n",
        "import os\n",
        "from os import path\n",
        "import socket\n",
        "import ctypes\n",
        "import importlib\n",
        "import sys\n",
        "import requests\n",
        "__import__('os')\n",
        "eval('1+1')\n",
        "exec('x=1')\n",
        "compile('x', 'f', 'exec')\n",
        "open('/etc/passwd').read()\n",
        "globals()['x'] = 1\n",
        "getattr(object, '__subclasses__')\n",
        "x = ().__class__.__bases__\n",
        "x = (1).__class__\n",
    ],
)
def test_check_script_rejects(src):
    with pytest.raises(ScriptRejected):
        check_script(src)


def test_check_script_accepts_a_clean_trimesh_script():
    check_script(CLEAN)
    check_script("from scipy import ndimage\nfrom scipy.spatial import ConvexHull\n")


@pytest.mark.parametrize("mod", ["numpy", "math", "trimesh", "manifold3d", "scipy", "json", "itertools", "functools", "collections"])
def test_check_script_allows_each_listed_import(mod):
    check_script(f"import {mod}\n")


def test_script_rejected_is_an_exception_with_a_message():
    with pytest.raises(ScriptRejected) as e:
        check_script("import subprocess\n")
    assert str(e.value)


def test_limits_defaults():
    lim = Limits()
    assert (lim.cpu_s, lim.wall_s, lim.mem_mb, lim.file_mb) == (240, 300, 3072, 200)


def test_run_script_refuses_without_a_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "available", lambda: False)
    with pytest.raises(SandboxUnavailable):
        run_script(CLEAN, tmp_path, Limits())
    assert not (tmp_path / "gen.py").exists()


def test_run_script_rejected_source_never_runs(tmp_path):
    with pytest.raises(ScriptRejected):
        run_script("import subprocess\n", tmp_path, Limits())
    assert not (tmp_path / "model.glb").exists()


def _probe(tmp_path, body, limits=None):
    work = tmp_path / "work"
    work.mkdir()
    src = "import json\nimport numpy as np\n" + textwrap.dedent(body)
    res = run_script(src, work, limits or Limits(cpu_s=20, wall_s=30, mem_mb=2048, file_mb=10), check=False)
    out = work / "result.txt"
    return res, (out.read_text() if out.exists() else None)


@needs_sandbox
def test_happy_path_writes_model_glb(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    res = run_script(CLEAN, work, Limits(cpu_s=60, wall_s=120, mem_mb=2048, file_mb=50))
    assert res.ok, res.stderr_tail
    assert res.glb == work / "model.glb" and res.glb.read_bytes()[:4] == b"glTF"
    assert res.reason is None and res.seconds >= 0
    assert (work / "gen.py").exists() and (work / "params.json").exists()


@needs_sandbox
def test_no_model_glb_is_reason_no_output(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    res = run_script("x = 1\n", work, Limits(cpu_s=20, wall_s=30, mem_mb=2048, file_mb=10))
    assert not res.ok and res.reason == "no_output" and res.glb is None


@needs_sandbox
def test_script_exception_is_reason_exit_with_stderr(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    res = run_script("raise ValueError('boom-marker')\n", work, Limits(cpu_s=20, wall_s=30, mem_mb=2048, file_mb=10))
    assert not res.ok and res.reason == "exit" and "boom-marker" in res.stderr_tail


@needs_sandbox
def test_socket_connect_fails(tmp_path):
    res, out = _probe(
        tmp_path,
        """
        import socket
        try:
            s = socket.create_connection(("1.1.1.1", 80), timeout=3)
            open("result.txt", "w").write("LEAKED")
        except Exception:
            open("result.txt", "w").write("BLOCKED")
        """,
    )
    assert out == "BLOCKED", (out, res.stderr_tail)


@needs_sandbox
def test_write_outside_work_dir_fails(tmp_path_factory, tmp_path):
    outside = tmp_path_factory.mktemp("outside") / "escaped.txt"
    res, out = _probe(
        tmp_path,
        f"""
        try:
            open({str(outside)!r}, "w").write("x")
            open("result.txt", "w").write("LEAKED")
        except Exception:
            open("result.txt", "w").write("BLOCKED")
        """,
    )
    assert out == "BLOCKED", (out, res.stderr_tail)
    assert not outside.exists()


@needs_sandbox
def test_reading_a_file_outside_work_dir_fails(tmp_path_factory, tmp_path):
    canary = tmp_path_factory.mktemp("home-like") / "secret.txt"
    canary.write_text("TOP-SECRET-CANARY")
    res, out = _probe(
        tmp_path,
        f"""
        try:
            data = open({str(canary)!r}).read()
            open("result.txt", "w").write("LEAKED:" + data)
        except Exception:
            open("result.txt", "w").write("BLOCKED")
        """,
    )
    assert out == "BLOCKED", (out, res.stderr_tail)


@needs_sandbox
def test_environment_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-canary-env")
    res, out = _probe(
        tmp_path,
        """
        import os
        open("result.txt", "w").write(json.dumps(dict(os.environ)))
        """,
    )
    assert out is not None, res.stderr_tail
    assert json.loads(out) == {}


@needs_sandbox
def test_cpu_spin_is_killed(tmp_path):
    res, _ = _probe(tmp_path, "while True:\n    pass\n", Limits(cpu_s=1, wall_s=8, mem_mb=1024, file_mb=10))
    assert not res.ok and res.reason in ("cpu", "timeout")
    assert res.seconds < 20


@needs_sandbox
def test_sleep_past_wall_clock_is_timeout(tmp_path):
    res, _ = _probe(tmp_path, "import time\ntime.sleep(60)\n", Limits(cpu_s=20, wall_s=2, mem_mb=1024, file_mb=10))
    assert not res.ok and res.reason == "timeout" and res.seconds < 20


@needs_sandbox
def test_memory_hog_is_killed(tmp_path):
    res, _ = _probe(
        tmp_path,
        """
        import time
        blocks = []
        while True:
            b = bytearray(50 * 1024 * 1024)
            for i in range(0, len(b), 4096):
                b[i] = 1
            blocks.append(b)
            time.sleep(0.01)
        """,
        Limits(cpu_s=30, wall_s=30, mem_mb=300, file_mb=10),
    )
    assert not res.ok and res.reason == "memory"


@needs_sandbox
def test_fork_bomb_is_contained(tmp_path):
    res, out = _probe(
        tmp_path,
        """
        import os
        forked = 0
        try:
            for _ in range(50):
                pid = os.fork()
                if pid == 0:
                    while True:
                        pass
                forked += 1
        except OSError:
            pass
        open("result.txt", "w").write(str(forked))
        """,
        Limits(cpu_s=10, wall_s=15, mem_mb=1024, file_mb=10),
    )
    assert out == "0", (out, res.stderr_tail)
    import psutil

    import os

    work = os.path.realpath(tmp_path / "work")
    left = []
    for p in psutil.process_iter():
        try:
            if os.path.realpath(p.cwd()) == work:
                left.append(p.pid)
        except (psutil.Error, OSError):
            continue
    assert left == []


def _glb_probe(tmp_path, body, limits=None, outside=None):
    work = tmp_path / "work"
    work.mkdir()
    return run_script("import os\nimport json\n" + textwrap.dedent(body), work, limits or Limits(cpu_s=20, wall_s=30, mem_mb=2048, file_mb=10), check=False)


def test_run_result_has_glb_bytes_for_a_regular_output(tmp_path):
    if not sandbox.available():
        pytest.skip("macOS sandbox-exec not available")
    work = tmp_path / "work"
    work.mkdir()
    res = run_script(CLEAN, work, Limits(cpu_s=60, wall_s=120, mem_mb=2048, file_mb=50))
    assert res.ok and res.glb_bytes and res.glb_bytes[:4] == b"glTF"


@needs_sandbox
def test_symlinked_output_is_bad_output_and_never_read(tmp_path_factory, tmp_path):
    secret = tmp_path_factory.mktemp("elsewhere") / "secret.bin"
    secret.write_bytes(b"OUTSIDE-CANARY-BYTES")
    res = _glb_probe(tmp_path, f"os.symlink({str(secret)!r}, 'model.glb')\n")
    assert not res.ok and res.reason == "bad_output"
    assert res.glb is None and res.glb_bytes is None
    assert "OUTSIDE-CANARY" not in repr(res)


@needs_sandbox
def test_hard_linked_output_is_bad_output(tmp_path):
    res = _glb_probe(tmp_path, "open('a.bin','wb').write(b'x'*10)\nos.link('a.bin', 'model.glb')\n")
    assert not res.ok and res.reason == "bad_output"


@needs_sandbox
def test_over_cap_output_is_bad_output(tmp_path):
    res = _glb_probe(tmp_path, "open('model.glb','wb').write(b'x'*(2*1024*1024))\n", Limits(cpu_s=20, wall_s=30, mem_mb=2048, file_mb=10, output_mb=1))
    assert not res.ok and res.reason == "bad_output"


@needs_sandbox
def test_work_dir_total_size_is_capped(tmp_path):
    res = _glb_probe(
        tmp_path,
        """
        import time
        for i in range(200):
            open(f"f{i}.bin", "wb").write(b"x" * (512 * 1024))
            time.sleep(0.02)
        time.sleep(20)
        """,
        Limits(cpu_s=20, wall_s=30, mem_mb=2048, file_mb=10, dir_mb=5),
    )
    assert not res.ok and res.reason == "disk"
