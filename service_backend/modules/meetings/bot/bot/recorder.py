"""ffmpeg pulls the null sink's monitor and writes 60 s opus segments; each closed segment is
uploaded at once so a crash loses at most one segment (AC-S1-5)."""
from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

from .storage import Storage


class Recorder:
    def __init__(self, work_dir: Path, storage: Storage, segment_seconds: int = 60) -> None:
        self.work_dir = work_dir
        self.storage = storage
        self.segment_seconds = segment_seconds
        self._proc: subprocess.Popen[bytes] | None = None
        self._uploaded: set[str] = set()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._upload_loop, daemon=True)

    def start(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        sink = os.environ.get("PULSE_SINK", "meet")
        cmd = [
            "ffmpeg", "-nostdin", "-loglevel", "error",
            "-f", "pulse", "-i", f"{sink}.monitor",
            "-ac", "1", "-ar", "48000", "-c:a", "libopus", "-b:a", "48k",
            "-f", "segment", "-segment_time", str(self.segment_seconds), "-reset_timestamps", "1",
            str(self.work_dir / "audio_%04d.ogg"),
        ]
        self._proc = subprocess.Popen(cmd)
        self._thread.start()

    def _closed_segments(self, include_last: bool) -> list[Path]:
        files = sorted(self.work_dir.glob("audio_*.ogg"))
        if not include_last and files:
            files = files[:-1]  # the newest one is still being written
        return [f for f in files if f.name not in self._uploaded]

    def _upload(self, files: list[Path]) -> None:
        for f in files:
            self.storage.put(f)
            self._uploaded.add(f.name)

    def _upload_loop(self) -> None:
        while not self._stop.wait(5):
            self._upload(self._closed_segments(include_last=False))

    def stop(self) -> int:
        self._stop.set()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        time.sleep(0.5)
        self._upload(self._closed_segments(include_last=True))
        return len(self._uploaded)
