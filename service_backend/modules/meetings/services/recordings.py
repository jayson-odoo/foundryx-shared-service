"""What the bot left behind, turned into one core ``files`` row (S2 plan §4).

The container writes 60 s opus segments plus ``events.jsonl``, ``last.png`` and
the odd probe artefact to whatever ``BOT_OUT`` names. Two targets exist because
two deployments do: a tenant with an S3/R2 storage connection gets
``s3://bucket/<tenant>/<meeting>/``, and a tenant without one (the pilot) gets a
bind-mounted directory under ``media_root``. ``Artifacts`` is the two-line seam
between them, so nothing above here branches on which.

The segments are concatenated into ONE recording (a meeting is one thing to
listen to, and S3 transcribes one file) and registered as a core ``files`` row in
the tenant's "Meetings" folder - spine M19: reuse core, do not add a table.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Protocol

from sqlalchemy.orm import Session

from app.models.document import File, FileVersion, Folder
from app.services.storage import storage_for_tenant

from ..models import Meeting

logger = logging.getLogger("foundryx.meetings")

SEGMENT_RE = re.compile(r"^audio_\d+\.ogg$")
SCREENSHOT_NAME = "last.png"
RECORDING_MIME = "audio/ogg"
MEETINGS_FOLDER = "Meetings"


class Artifacts(Protocol):
    """Everything one meeting's container wrote, wherever it wrote it."""

    def names(self) -> List[str]:
        """Every artefact name under this meeting's prefix."""
        ...

    def read(self, name: str) -> bytes: ...

    def delete(self, name: str) -> None: ...

    def key_of(self, name: str) -> str:
        """A stable, storable reference to one artefact (e.g. the screenshot)."""
        ...


class LocalArtifacts:
    """A bind-mounted directory on the worker host (the pilot's target)."""

    kind = "local"

    def __init__(self, root: Path):
        self.root = Path(root)

    def names(self) -> List[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_file())

    def read(self, name: str) -> bytes:
        return (self.root / name).read_bytes()

    def delete(self, name: str) -> None:
        try:
            (self.root / name).unlink()
        except FileNotFoundError:
            pass

    def key_of(self, name: str) -> str:
        return str(self.root / name)


class S3Artifacts:
    """An S3/R2 prefix the container uploaded to through the tenant's bucket."""

    kind = "s3"

    def __init__(self, adapter, bucket: str, prefix: str):
        self.adapter = adapter
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def names(self) -> List[str]:
        response = self.adapter.client.list_objects_v2(
            Bucket=self.bucket, Prefix=f"{self.prefix}/"
        )
        return sorted(
            obj["Key"].rsplit("/", 1)[-1] for obj in response.get("Contents", [])
        )

    def read(self, name: str) -> bytes:
        return self.adapter.fetch(self.key_of(name))[0]

    def delete(self, name: str) -> None:
        self.adapter.delete(self.key_of(name))

    def key_of(self, name: str) -> str:
        return f"{self.prefix}/{name}"


def segment_names(artifacts: Artifacts) -> List[str]:
    """The audio segments, in the order the recorder wrote them.

    ``audio_0000.ogg`` … is zero-padded by the recorder, so a plain sort is the
    chronological one - no numeric parsing needed and none that can go wrong."""
    return sorted(n for n in artifacts.names() if SEGMENT_RE.match(n))


def ffmpeg_exe() -> str:
    """A usable ffmpeg. Prefers the system one (the Docker image ships it) and
    falls back to the static binary ``imageio-ffmpeg`` bundles, so a native local
    worker with no brew/apt ffmpeg still concatenates."""
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg  # optional; installed via requirements

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - resolved lazily; the caller reports it
        return "ffmpeg"


def concat_segments(segments: List[bytes]) -> bytes:
    """Join opus/ogg segments into one file. Stream copy, never a re-encode:
    every segment came out of the same encoder at the same settings, so there is
    nothing to convert and re-encoding would only lose quality and time."""
    if not segments:
        return b""
    if len(segments) == 1:
        return segments[0]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        paths = []
        for index, blob in enumerate(segments):
            path = root / f"seg_{index:04d}.ogg"
            path.write_bytes(blob)
            paths.append(path)
        listing = root / "segments.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in paths))
        out = root / "recording.ogg"
        subprocess.run(
            [
                ffmpeg_exe(), "-nostdin", "-loglevel", "error", "-y",
                "-f", "concat", "-safe", "0", "-i", str(listing),
                "-c", "copy", str(out),
            ],
            check=True,
            capture_output=True,
        )
        return out.read_bytes()


def meetings_folder(db: Session, tenant_id: str) -> Folder:
    """The tenant's "Meetings" folder, created on first use.

    A root-level folder, and looked up by name because that is what the tenant
    sees in the Drive - a stored id would be a hardcoded lookup of something the
    tenant can rename (PRINCIPLES: never do that), and a rename would silently
    start a second folder rather than break."""
    folder = (
        db.query(Folder)
        .filter(
            Folder.tenant_id == tenant_id,
            Folder.parent_id.is_(None),
            Folder.name == MEETINGS_FOLDER,
            Folder.is_deleted.is_(False),
        )
        .first()
    )
    if folder is None:
        folder = Folder(tenant_id=tenant_id, parent_id=None, name=MEETINGS_FOLDER)
        db.add(folder)
        db.flush()
    return folder


def recording_name(meeting: Meeting) -> str:
    """A filename a person can find in the Drive: the meeting and when it ran."""
    stamp = meeting.starts_at.strftime("%Y-%m-%d %H%M") if meeting.starts_at else "unknown"
    title = (meeting.title or "Meeting").strip() or "Meeting"
    safe = re.sub(r'[\\/:*?"<>|]+', " ", title).strip()
    return f"{safe} {stamp}.ogg"


def register_recording(
    db: Session, meeting: Meeting, artifacts: Artifacts
) -> Optional[str]:
    """Concatenate the segments, store the result, register one core ``files``
    row and point the meeting at it. Returns the file id, or None when the bot
    recorded nothing at all.

    The segments are deleted only AFTER the joined file is safely stored: losing
    the source to a failed upload would lose the meeting."""
    names = segment_names(artifacts)
    if not names:
        return None

    blobs = [artifacts.read(name) for name in names]
    content = concat_segments(blobs)
    if not content:
        return None

    folder = meetings_folder(db, meeting.tenant_id)
    file = File(
        tenant_id=meeting.tenant_id,
        folder_id=folder.id,
        name=recording_name(meeting),
        # No human uploaded this; ``created_by`` stays NULL rather than being
        # attributed to whoever happened to be in the meeting.
        created_by=None,
    )
    db.add(file)
    db.flush()
    version = FileVersion(
        file_id=file.id,
        ordinal=1,
        storage_key="",  # set after the store (the key needs the version id)
        size_bytes=len(content),
        mime=RECORDING_MIME,
    )
    db.add(version)
    db.flush()
    version.storage_key = storage_for_tenant(db, meeting.tenant_id).save(
        f"meetings/{meeting.id}/{version.id}", content, RECORDING_MIME
    )
    file.current_version_id = version.id
    meeting.recording_file_id = file.id
    db.flush()

    for name in names:
        try:
            artifacts.delete(name)
        except Exception:  # noqa: BLE001 - the recording is safe; a leftover is not a failure
            logger.warning("meetings segment %s could not be removed", name)
    return file.id
