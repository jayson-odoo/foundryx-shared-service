"""``MlxLocalProvider`` subprocess driver (S3 plan §3.1, R1).

Every test fakes ``subprocess.run`` - none of these exec a real python or a
real mlx-whisper. The flock test is the one exception: it drives the REAL
``fcntl.flock`` against a tmp-path lock file across two threads, because
serialization is exactly the thing under test (AC-S3-12).
"""
import json
import subprocess
import threading
import time
from pathlib import Path

import pytest

from modules.meetings.stt import mlx_local


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture(autouse=True)
def isolated_lock(tmp_path, monkeypatch):
    """Every test gets its OWN lock file - never the shared tempdir path,
    which would otherwise serialize unrelated tests against each other."""
    monkeypatch.setattr(mlx_local, "LOCK_PATH", tmp_path / "stt.lock")


def test_a_successful_run_parses_the_json_contract(monkeypatch):
    payload = {
        "language": "en",
        "segments": [
            {"start_ms": 0, "end_ms": 1200, "text": "hello there"},
            {"start_ms": 1200, "end_ms": 2400, "text": "how are you"},
        ],
    }
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeCompleted(stdout=json.dumps(payload))
    )

    result = mlx_local.MlxLocalProvider().transcribe(Path("/tmp/recording.ogg"))

    assert result.language == "en"
    assert [("start_ms", s.start_ms, "end_ms", s.end_ms, "text", s.text) for s in result.segments] == [
        ("start_ms", 0, "end_ms", 1200, "text", "hello there"),
        ("start_ms", 1200, "end_ms", 2400, "text", "how are you"),
    ]


def test_per_segment_language_passes_through(monkeypatch):
    """S3 code-switch fix: the chunked runner tags each segment with the
    detected language of the chunk it came from - a code-switched meeting
    carries a real value per segment, not a file-wide guess."""
    payload = {
        "language": "zh",
        "segments": [
            {"start_ms": 0, "end_ms": 1200, "text": "hello there", "language": "en"},
            {"start_ms": 1200, "end_ms": 2400, "text": "你好嗎", "language": "zh"},
        ],
    }
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeCompleted(stdout=json.dumps(payload))
    )

    result = mlx_local.MlxLocalProvider().transcribe(Path("/tmp/recording.ogg"))

    assert [s.language for s in result.segments] == ["en", "zh"]


def test_a_segment_missing_the_language_key_parses_with_language_none(monkeypatch):
    """Tolerates an older runner payload that never sent per-segment
    language."""
    payload = {
        "language": "en",
        "segments": [{"start_ms": 0, "end_ms": 1200, "text": "hello there"}],
    }
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeCompleted(stdout=json.dumps(payload))
    )

    result = mlx_local.MlxLocalProvider().transcribe(Path("/tmp/recording.ogg"))

    assert result.segments[0].language is None


def test_the_runner_argv_carries_chunk_s_and_languages(monkeypatch):
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeCompleted(stdout=json.dumps({"language": None, "segments": []}))

    monkeypatch.setattr(subprocess, "run", _fake_run)

    mlx_local.MlxLocalProvider().transcribe(Path("/tmp/recording.ogg"))

    from app.config import settings

    assert captured["cmd"][-2] == str(settings.meetings_stt_chunk_s)
    assert captured["cmd"][-1] == settings.meetings_stt_languages


def test_a_non_zero_exit_raises_with_the_stderr_tail(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(returncode=1, stderr="RuntimeError: no Metal device"),
    )

    with pytest.raises(mlx_local.SttTranscriptionError, match="no Metal device"):
        mlx_local.MlxLocalProvider().transcribe(Path("/tmp/recording.ogg"))


def test_a_timeout_raises_and_still_releases_the_lock(monkeypatch):
    def _timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="mlx_runner.py", timeout=1800)

    monkeypatch.setattr(subprocess, "run", _timeout)

    with pytest.raises(mlx_local.SttTranscriptionError, match="timed out"):
        mlx_local.MlxLocalProvider().transcribe(Path("/tmp/recording.ogg"))

    # The lock must be released even on failure - a second call proves it by
    # not hanging.
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeCompleted(stdout=json.dumps({"language": None, "segments": []}))
    )
    mlx_local.MlxLocalProvider().transcribe(Path("/tmp/recording.ogg"))


def test_unparseable_stdout_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(stdout="not json"))

    with pytest.raises(mlx_local.SttTranscriptionError, match="no parseable JSON"):
        mlx_local.MlxLocalProvider().transcribe(Path("/tmp/recording.ogg"))


def test_two_concurrent_calls_serialize_on_the_flock(monkeypatch):
    """AC-S3-12: the second call WAITS for the first's flock rather than
    running alongside it. ``subprocess`` is a shared module object, so
    patching it once (via ``monkeypatch``) covers both threads."""
    order = []
    log_lock = threading.Lock()

    def _slow_run(*a, **k):
        with log_lock:
            order.append("start")
        time.sleep(0.2)
        with log_lock:
            order.append("end")
        return _FakeCompleted(stdout=json.dumps({"language": None, "segments": []}))

    monkeypatch.setattr(subprocess, "run", _slow_run)

    provider = mlx_local.MlxLocalProvider()
    threads = [
        threading.Thread(target=lambda: provider.transcribe(Path("/tmp/recording.ogg")))
        for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Serialized: a "start" is never followed by a second "start" before the
    # first "end" - the two runs never overlapped.
    assert order == ["start", "end", "start", "end"]
