"""A Docker daemon that never existed, and a place for a bot to write.

Every S2 test drives these instead of a real container: the runner's job is to
shape a spec, read a stream of events and turn an exit into a status, and all
three are testable without ever starting anything.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional


class FakeContainer:
    """Replays a scripted stdout, then exits with a scripted code."""

    def __init__(self, lines: List[str], exit_code: int = 0, name: str = "bot"):
        self._lines = lines
        self._exit_code = exit_code
        self.name = name
        self.stopped_with: Optional[int] = None
        self.waited = False

    def logs(self, stream: bool = False, follow: bool = False):
        for line in self._lines:
            yield (line + "\n").encode("utf-8")

    def wait(self) -> dict:
        self.waited = True
        return {"StatusCode": self._exit_code}

    def stop(self, timeout: int = 10) -> None:
        self.stopped_with = timeout


class FakeContainers:
    def __init__(self, container: FakeContainer, fail_with: Optional[Exception] = None):
        self._container = container
        self._fail_with = fail_with
        self.runs: List[Dict] = []

    def run(self, **kwargs):
        self.runs.append(kwargs)
        if self._fail_with is not None:
            raise self._fail_with
        return self._container


class FakeDocker:
    """What ``docker.from_env()`` would have handed back."""

    def __init__(
        self,
        container: Optional[FakeContainer] = None,
        *,
        info_error: Optional[Exception] = None,
        run_error: Optional[Exception] = None,
    ):
        self.containers = FakeContainers(container or FakeContainer([]), run_error)
        self._info_error = info_error

    def info(self) -> dict:
        if self._info_error is not None:
            raise self._info_error
        return {"ServerVersion": "fake"}


def event_line(kind: str, **data) -> str:
    """The exact stdout shape the bot emits (``bot/events.py``)."""
    import json

    return f"[event] {kind} {json.dumps(data)}"


def bot_stdout(
    *,
    lobby: bool = False,
    joined: bool = True,
    reason: str = "room_empty",
    segments: int = 2,
    started_ts: float = 1_000.0,
    finished_ts: float = 2_800.0,
) -> List[str]:
    """A whole run's stdout, in the order the bot really writes it."""
    lines = []
    if lobby:
        lines.append(event_line("in_lobby"))
    if joined:
        lines.append(event_line("joined", lobby=lobby))
        lines.append(event_line("recording_started", ts=started_ts))
        lines.append(event_line("participants", humans=2, tiles=["A", "B"]))
    lines.append(event_line("finished", reason=reason, segments=segments, ts=finished_ts))
    # The bot's LAST stdout line is the bare reason (`print(reason)`).
    lines.append(reason)
    return lines


class FakeArtifacts:
    """An in-memory ``Artifacts`` — what the container left behind."""

    kind = "fake"

    def __init__(self, blobs: Optional[Dict[str, bytes]] = None, prefix: str = "t/m"):
        self.blobs = dict(blobs or {})
        self.prefix = prefix
        self.deleted: List[str] = []

    def names(self) -> List[str]:
        return sorted(self.blobs)

    def read(self, name: str) -> bytes:
        return self.blobs[name]

    def delete(self, name: str) -> None:
        self.blobs.pop(name, None)
        self.deleted.append(name)

    def key_of(self, name: str) -> str:
        return f"{self.prefix}/{name}"


class RecordingStorage:
    """A ``StorageService`` that just remembers what it was handed."""

    def __init__(self):
        self.saved: Dict[str, bytes] = {}

    def save(self, key_hint: str, content: bytes, mime_type: str) -> str:
        key = f"{key_hint}.ogg"
        self.saved[key] = content
        return key

    def put(self, key_hint: str, content: bytes, mime_type: str) -> str:  # pragma: no cover
        return self.save(key_hint, content, mime_type)

    def put_raw(self, raw: str, content: bytes, mime_type: str) -> None:  # pragma: no cover
        self.saved[raw] = content

    def resolve(self, key: str):  # pragma: no cover
        return ("path", key)

    def fetch(self, key: str):  # pragma: no cover
        return self.saved[key], "audio/ogg"

    def delete(self, key: str) -> None:  # pragma: no cover
        self.saved.pop(key, None)


def local_artifacts(tmp_path: Path, names: Dict[str, bytes]):
    from modules.meetings.services.recordings import LocalArtifacts

    for name, blob in names.items():
        (tmp_path / name).write_bytes(blob)
    return LocalArtifacts(tmp_path)
