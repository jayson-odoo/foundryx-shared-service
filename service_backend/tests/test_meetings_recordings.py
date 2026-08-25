"""Segments in, one recording out - AC-S2-6 in detail.

The concatenation is exercised against REAL opus bytes made by the same ffmpeg
the worker uses: fabricated bytes would satisfy every assertion here and still
leave the only thing that matters - a playable joined file - untested.
"""
import subprocess
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.meetings.models import Meeting
from tests.meetings_bot_fakes import FakeArtifacts, RecordingStorage
from tests.meetings_helpers import utc

NOW = utc(2026, 9, 1, 2, 0)


def _opus(seconds: float) -> bytes:
    from modules.meetings.services.recordings import ffmpeg_exe

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "seg.ogg"
        subprocess.run(
            [
                ffmpeg_exe(), "-nostdin", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                "-t", str(seconds), "-c:a", "libopus", "-b:a", "48k", str(out),
            ],
            check=True,
            capture_output=True,
        )
        return out.read_bytes()


def _duration(blob: bytes) -> float:
    """What ffmpeg says the joined file actually plays for."""
    from modules.meetings.services.recordings import ffmpeg_exe

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.ogg"
        src.write_bytes(blob)
        out = Path(tmp) / "out.wav"
        subprocess.run(
            [ffmpeg_exe(), "-nostdin", "-loglevel", "error", "-y", "-i", str(src), str(out)],
            check=True,
            capture_output=True,
        )
        # 48 kHz mono 16-bit PCM, minus the 44-byte wav header.
        return (out.stat().st_size - 44) / (48_000 * 2)


@pytest.fixture
def db(meetings_session_factory):
    session = meetings_session_factory()
    yield session
    session.close()


@pytest.fixture
def storage(monkeypatch):
    from modules.meetings.services import recordings as recordings_module

    recorder = RecordingStorage()
    monkeypatch.setattr(
        recordings_module, "storage_for_tenant", lambda db, tenant_id: recorder
    )
    return recorder


_SEQUENCE = {"n": 0}


def _meeting(db, *, title="Weekly product sync", url=None):
    from modules.meetings.services.calendar_sync import dedupe_key

    # A fresh link per meeting: `uq_meetings_dedupe` is <url>|<start>, and every
    # meeting here shares one start.
    _SEQUENCE["n"] += 1
    url = url or f"https://meet.google.com/abc-defg-h{_SEQUENCE['n']:02d}"
    row = Meeting(
        tenant_id=DEFAULT_TENANT_ID,
        dedupe_key=dedupe_key(url, NOW),
        title=title,
        conference_url=url,
        platform="meet",
        starts_at=NOW,
        ends_at=NOW + timedelta(hours=1),
        status="processing",
    )
    db.add(row)
    db.flush()
    return row


def test_the_segments_are_joined_in_the_order_the_recorder_wrote_them():
    from modules.meetings.services.recordings import segment_names

    artifacts = FakeArtifacts(
        {
            "audio_0010.ogg": b"",
            "audio_0002.ogg": b"",
            "audio_0000.ogg": b"",
            "events.jsonl": b"",
            "last.png": b"",
            "dom_probe.json": b"",
        }
    )
    # Zero-padded by the recorder, so a plain sort IS chronological - and only
    # the audio is a segment.
    assert segment_names(artifacts) == [
        "audio_0000.ogg",
        "audio_0002.ogg",
        "audio_0010.ogg",
    ]


def test_two_real_segments_concatenate_into_one_playable_file():
    from modules.meetings.services.recordings import concat_segments

    joined = concat_segments([_opus(0.5), _opus(0.5)])

    assert joined.startswith(b"OggS")
    assert _duration(joined) == pytest.approx(1.0, abs=0.15)


def test_a_single_segment_needs_no_ffmpeg_at_all():
    from modules.meetings.services.recordings import concat_segments

    one = _opus(0.4)
    assert concat_segments([one]) == one
    assert concat_segments([]) == b""


def test_registering_writes_one_file_row_in_the_meetings_folder(db, storage):
    from app.models.document import File, FileVersion, Folder
    from modules.meetings.services.recordings import register_recording

    meeting = _meeting(db)
    artifacts = FakeArtifacts({"audio_0000.ogg": _opus(0.4), "audio_0001.ogg": _opus(0.4)})

    file_id = register_recording(db, meeting, artifacts)
    db.commit()

    file = db.query(File).filter(File.id == file_id).one()
    assert file.tenant_id == DEFAULT_TENANT_ID
    # Nobody uploaded this, so it is attributed to nobody.
    assert file.created_by is None
    folder = db.query(Folder).filter(Folder.id == file.folder_id).one()
    assert folder.name == "Meetings" and folder.parent_id is None

    version = db.query(FileVersion).filter(FileVersion.file_id == file.id).one()
    assert version.mime == "audio/ogg"
    assert version.size_bytes == len(storage.saved[version.storage_key])
    assert file.current_version_id == version.id
    assert meeting.recording_file_id == file.id


def test_the_meetings_folder_is_made_once_and_then_reused(db, storage):
    from app.models.document import Folder
    from modules.meetings.services.recordings import register_recording

    for index in range(3):
        meeting = _meeting(db, title=f"Meeting {index}")
        register_recording(db, meeting, FakeArtifacts({"audio_0000.ogg": _opus(0.3)}))
    db.commit()

    assert (
        db.query(Folder)
        .filter(Folder.tenant_id == DEFAULT_TENANT_ID, Folder.name == "Meetings")
        .count()
        == 1
    )


def test_nothing_is_registered_when_the_bot_recorded_nothing(db, storage):
    from app.models.document import File
    from modules.meetings.services.recordings import register_recording

    meeting = _meeting(db)
    assert register_recording(db, meeting, FakeArtifacts({"events.jsonl": b"{}"})) is None
    assert db.query(File).count() == 0
    assert meeting.recording_file_id is None


def test_the_segments_are_deleted_but_the_other_artefacts_are_kept(db, storage):
    """`events.jsonl` and the captions are S3's inputs; deleting them here would
    throw away the transcript before it was ever made."""
    from modules.meetings.services.recordings import register_recording

    meeting = _meeting(db)
    artifacts = FakeArtifacts(
        {
            "audio_0000.ogg": _opus(0.3),
            "events.jsonl": b"{}",
            "last.png": b"\x89PNG",
        }
    )
    register_recording(db, meeting, artifacts)
    db.commit()

    assert artifacts.deleted == ["audio_0000.ogg"]
    assert sorted(artifacts.blobs) == ["events.jsonl", "last.png"]


def test_the_filename_says_which_meeting_and_when(db, storage):
    from modules.meetings.services.recordings import recording_name

    assert (
        recording_name(_meeting(db, title="Weekly product sync"))
        == "Weekly product sync 2026-09-01 0200.ogg"
    )
    # A title with path characters must not become a path.
    assert "/" not in recording_name(_meeting(db, title="Ops / Finance sync"))
    untitled = _meeting(db, title=None)
    assert recording_name(untitled).startswith("Meeting ")


def test_a_local_artifacts_directory_reads_lists_and_deletes(tmp_path):
    from modules.meetings.services.recordings import LocalArtifacts

    (tmp_path / "audio_0000.ogg").write_bytes(b"one")
    (tmp_path / "last.png").write_bytes(b"png")
    artifacts = LocalArtifacts(tmp_path)

    assert artifacts.names() == ["audio_0000.ogg", "last.png"]
    assert artifacts.read("audio_0000.ogg") == b"one"
    assert artifacts.key_of("last.png").endswith("last.png")

    artifacts.delete("audio_0000.ogg")
    assert artifacts.names() == ["last.png"]
    # Deleting what is already gone is a no-op, not a crash.
    artifacts.delete("audio_0000.ogg")


def test_an_empty_output_directory_is_not_an_error(tmp_path):
    from modules.meetings.services.recordings import LocalArtifacts

    assert LocalArtifacts(tmp_path / "never-created").names() == []
