"""One meeting, one container (S2 plan §3, AC-S2-5..10, AC-S2-13).

The handler starts a bot container from the S1 image, follows its stdout, maps
the ``[event] <kind> <json>`` lines onto the meeting's status while the call is
running, and turns the exit into the final status. It BLOCKS for the length of
the meeting on purpose: the Celery worker's ``--concurrency`` is then the only
cap on how many bots run at once (AC-S2-9), which is what the memory of the host
can actually be reasoned about.

Everything that identifies a tenant - the notetaker credentials, the browser
profile volume, the storage the audio lands in - is resolved from THAT tenant's
own rows and put on THAT container (AC-S2-13). Two tenants meeting in the same
minute share nothing but the image.
"""
from __future__ import annotations

import json
import logging
import re
import signal
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.config import settings
from app.models.background_job import JOB_DONE, JOB_FAILED, BackgroundJob
from app.models.connection import Connection
from app.secrets import decrypt_secret

from ..models import (
    STATUS_FAILED,
    STATUS_IN_LOBBY,
    STATUS_NOT_ADMITTED,
    STATUS_PROCESSING,
    STATUS_RECORDING,
    Meeting,
)
from .recordings import (
    SCREENSHOT_NAME,
    Artifacts,
    LocalArtifacts,
    S3Artifacts,
    register_recording,
)

logger = logging.getLogger("foundryx.meetings")

# The pilot image, built locally from ``modules/meetings/bot``. Overridable with
# MEETINGS_BOT_IMAGE so a deploy can pin a published tag.
DEFAULT_BOT_IMAGE = "foundryx-shared-service:bot-spike"
DEFAULT_DISPLAY_NAME = "Notetaker"

# The bot's own exit words (see ``bot/__main__.py``).
FINISHED_REASONS = ("room_empty", "removed", "ended", "max_duration", "stopped")
NOT_ADMITTED_REASONS = ("not_admitted", "denied")

# A live event that moves the meeting on while the call is still running.
LIVE_STATUS = {
    "in_lobby": STATUS_IN_LOBBY,
    "joined": STATUS_RECORDING,
    "recording_started": STATUS_RECORDING,
}

_EVENT_RE = re.compile(r"^\[event\]\s+(\S+)(?:\s+(\{.*\}))?\s*$")

# How long the bot gets to leave the call and flush its tail on shutdown. The
# container handles SIGTERM by leaving, so this is a graceful path, not a kill.
STOP_TIMEOUT_SECONDS = 45


class BotRunError(Exception):
    """The run could not be STARTED - missing credentials, missing image, no
    Docker. Distinct from a bot that ran and failed, which is a meeting status."""


@dataclass
class ContainerSpec:
    """Exactly what gets handed to Docker. A dataclass rather than a call so a
    test can assert on one tenant's spec without a Docker daemon anywhere near
    it (AC-S2-13)."""

    image: str
    name: str
    command: List[str]
    environment: Dict[str, str] = field(default_factory=dict)
    volumes: Dict[str, Dict[str, str]] = field(default_factory=dict)
    shm_size: str = "1g"

    def as_kwargs(self) -> Dict[str, Any]:
        return {
            "image": self.image,
            "name": self.name,
            "command": self.command,
            "environment": self.environment,
            "volumes": self.volumes,
            "shm_size": self.shm_size,
            "detach": True,
            # Never auto-remove: the logs and the exit code are the only record
            # of what happened, and they die with the container.
            "auto_remove": False,
        }


def docker_client():
    """The Docker client. A module-level function so a test can swap it."""
    import docker  # noqa: PLC0415 — optional at import time, required at run time

    return docker.from_env()


def bot_image() -> str:
    return getattr(settings, "meetings_bot_image", "") or DEFAULT_BOT_IMAGE


# ── per-tenant inputs ─────────────────────────────────────────────────────────


def bot_credentials(db: Session, tenant_id: str) -> Tuple[str, str, Optional[str]]:
    """The tenant's notetaker email + password + display-name override.

    Raises ``BotRunError`` rather than running a bot that cannot sign in - a
    container that fails to log in burns a meeting and reports a confusing
    reason."""
    from ..providers import MEET_BOT_PROVIDER

    connection = (
        db.query(Connection)
        .filter(
            Connection.tenant_id == tenant_id,
            Connection.provider == MEET_BOT_PROVIDER,
            Connection.is_active.is_(True),
        )
        .first()
    )
    if connection is None:
        raise BotRunError("This tenant has no notetaker account connected.")
    config = connection.config_json or {}
    try:
        credentials = decrypt_secret(connection.credentials_json)
    except InvalidToken as exc:
        raise BotRunError(
            "The notetaker account's password can no longer be decrypted. "
            "Re-enter it on the connection and save."
        ) from exc
    email = str(config.get("email") or "").strip()
    password = str(credentials.get("password") or "")
    if not email or not password:
        raise BotRunError("The notetaker account is missing an email or password.")
    return email, password, (str(config.get("displayNameOverride") or "").strip() or None)


def storage_connection(db: Session, tenant_id: str) -> Optional[Connection]:
    from app.repositories.connection_repository import ConnectionRepository

    return ConnectionRepository(db).resolve_for_type(tenant_id, "storage")


def build_output(
    db: Session, meeting: Meeting
) -> Tuple[Dict[str, str], Dict[str, Dict[str, str]], Artifacts]:
    """Where this meeting's container writes, as (env, volumes, artifacts).

    With a tenant storage connection the container uploads straight to that
    tenant's own bucket under ``<tenant>/<meeting>/`` (S2 plan §3). Without one -
    the pilot, which runs on local-disk storage - it writes to a bind-mounted
    directory under ``media_root`` instead, because ``BOT_OUT=s3://…`` has
    nothing to fill in and a bot that cannot write anywhere records nothing.
    Either way the path carries the tenant id, so two tenants never share one.
    """
    prefix = f"{meeting.tenant_id}/{meeting.id}"
    connection = storage_connection(db, meeting.tenant_id)
    if connection is not None:
        from app.integrations.s3_provider import S3CompatibleAdapter, derive_endpoint

        config = connection.config_json or {}
        credentials = decrypt_secret(connection.credentials_json) if connection.credentials_json else {}
        bucket = str(config.get("bucket") or "")
        adapter = S3CompatibleAdapter.from_connection(
            connection.provider, config, credentials
        )
        env = {
            "BOT_OUT": f"s3://{bucket}/{prefix}/",
            # boto3 inside the container reads the standard names.
            "AWS_ACCESS_KEY_ID": str(credentials.get("accessKeyId") or ""),
            "AWS_SECRET_ACCESS_KEY": str(credentials.get("secretAccessKey") or ""),
            "BOT_S3_REGION": str(config.get("region") or "auto"),
        }
        endpoint = derive_endpoint(connection.provider, config)
        if endpoint:
            env["BOT_S3_ENDPOINT"] = endpoint
        return env, {}, S3Artifacts(adapter, bucket, prefix)

    host_dir = (Path(settings.media_root).resolve() / "meetings" / prefix)
    host_dir.mkdir(parents=True, exist_ok=True)
    return (
        {"BOT_OUT": "/out"},
        {str(host_dir): {"bind": "/out", "mode": "rw"}},
        LocalArtifacts(host_dir),
    )


def build_spec(db: Session, meeting: Meeting) -> Tuple[ContainerSpec, Artifacts]:
    """The container for ONE meeting of ONE tenant."""
    from .settings import MeetingsSettingsService

    email, password, name_override = bot_credentials(db, meeting.tenant_id)
    tenant_settings = MeetingsSettingsService(db).get(meeting.tenant_id)
    out_env, volumes, artifacts = build_output(db, meeting)

    environment = {
        "BOT_EMAIL": email,
        "BOT_PASSWORD": password,
        "BOT_DISPLAY_NAME": (
            tenant_settings.bot_display_name or name_override or DEFAULT_DISPLAY_NAME
        ),
        "BOT_FOR_USER": _for_user(db, meeting),
        "BOT_HEADLESS": "1",
        **out_env,
    }
    if tenant_settings.consent_message:
        environment["BOT_CONSENT_TEXT"] = tenant_settings.consent_message

    # One profile volume per TENANT: the notetaker's signed-in Chromium profile
    # is that tenant's credential in cookie form, and sharing it across tenants
    # would sign one tenant's bot in as another's.
    volumes = {
        **volumes,
        f"meetings-profile-{meeting.tenant_id}": {"bind": "/profile", "mode": "rw"},
    }
    return (
        ContainerSpec(
            image=bot_image(),
            name=f"meetings-bot-{meeting.id}",
            command=["--meet-url", meeting.conference_url],
            environment=environment,
            volumes=volumes,
        ),
        artifacts,
    )


def _for_user(db: Session, meeting: Meeting) -> str:
    """Whose notetaker this is, for the display name and the consent message.

    The first opted-in participant, by email so the ordering is stable; a
    meeting with none never reaches here (dispatch skips it)."""
    from ..models import MeetingParticipant

    row = (
        db.query(MeetingParticipant)
        .filter(
            MeetingParticipant.meeting_id == meeting.id,
            MeetingParticipant.is_opted_in.is_(True),
        )
        .order_by(MeetingParticipant.email.asc())
        .first()
    )
    if row is None:
        return ""
    return row.display_name or row.email


# ── the run ───────────────────────────────────────────────────────────────────


def parse_event(line: str) -> Optional[Tuple[str, dict]]:
    """One ``[event] <kind> <json>`` stdout line, or None for anything else."""
    match = _EVENT_RE.match(line.strip())
    if match is None:
        return None
    kind, payload = match.group(1), match.group(2)
    try:
        data = json.loads(payload) if payload else {}
    except ValueError:
        data = {}
    return kind, data if isinstance(data, dict) else {}


@contextmanager
def graceful_stop_on_sigterm(container):
    """Stop the container the polite way when the worker is asked to shut down.

    Celery's warm shutdown lets a running task finish, which for a meeting could
    be hours - so SIGTERM has to reach the container. ``docker stop`` sends the
    container its own SIGTERM, which the bot handles by LEAVING the call and
    flushing its tail (AC-S2-10), so segments recorded so far survive. The
    previous handler still runs afterwards: Celery's own shutdown must not be
    swallowed by ours."""
    try:
        previous = signal.getsignal(signal.SIGTERM)
    except (ValueError, AttributeError):  # pragma: no cover — not the main thread
        yield
        return

    def handler(signum, frame):
        try:
            container.stop(timeout=STOP_TIMEOUT_SECONDS)
        except Exception:  # noqa: BLE001 — shutdown must continue regardless
            logger.exception("meetings bot container could not be stopped gracefully")
        if callable(previous):
            previous(signum, frame)

    try:
        signal.signal(signal.SIGTERM, handler)
    except ValueError:  # pragma: no cover — signal only works in the main thread
        yield
        return
    try:
        yield
    finally:
        try:
            signal.signal(signal.SIGTERM, previous)
        except (ValueError, TypeError):  # pragma: no cover
            pass


def _set_status(db: Session, meeting: Meeting, status: str) -> None:
    meeting.status = status
    db.commit()


def follow(db: Session, meeting: Meeting, container) -> Tuple[Optional[str], Optional[float], Optional[float]]:
    """Tail the container's stdout, moving the meeting on as events arrive.

    Returns ``(reason, recording_started_ts, finished_ts)`` - the reason off the
    bot's own ``finished`` event when it emitted one, and the two timestamps that
    make the recorded duration (the bot stamps every event, so the worker never
    has to guess at it or re-read the audio)."""
    reason: Optional[str] = None
    started_ts: Optional[float] = None
    finished_ts: Optional[float] = None
    last_plain: Optional[str] = None

    for raw in container.logs(stream=True, follow=True):
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        for part in line.splitlines():
            part = part.strip()
            if not part:
                continue
            parsed = parse_event(part)
            if parsed is None:
                # The bot's LAST stdout line is the bare exit reason.
                last_plain = part
                continue
            kind, data = parsed
            if kind in LIVE_STATUS and meeting.status != LIVE_STATUS[kind]:
                _set_status(db, meeting, LIVE_STATUS[kind])
            if kind == "recording_started":
                started_ts = data.get("ts") or _now_ts()
            if kind == "finished":
                reason = str(data.get("reason") or "") or None
                finished_ts = data.get("ts") or _now_ts()
    return reason or last_plain, started_ts, finished_ts


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def run_bot(db: Session, job: BackgroundJob) -> None:
    """Handler for ``meetings.bot_run`` — one meeting, start to finish."""
    from app.jobs.service import JobService

    service = JobService(db)
    payload = job.payload_json or {}
    meeting = (
        db.query(Meeting)
        .filter(
            Meeting.tenant_id == job.tenant_id,
            Meeting.id == str(payload.get("meeting_id") or ""),
        )
        .first()
    )
    if meeting is None:
        service.finish(job, status=JOB_FAILED, error="The meeting no longer exists.")
        return

    try:
        spec, artifacts = build_spec(db, meeting)
    except BotRunError as exc:
        _fail(db, service, job, meeting, str(exc), artifacts=None)
        return

    if payload.get("late"):
        service.log(job, "the meeting had already started when the bot was dispatched")

    try:
        client = docker_client()
        container = client.containers.run(**spec.as_kwargs())
    except Exception as exc:  # noqa: BLE001 — no container means no run
        _fail(db, service, job, meeting, f"The bot container could not start: {exc}", None)
        return

    service.log(job, f"started {spec.name} from {spec.image}")
    try:
        with graceful_stop_on_sigterm(container):
            reason, started_ts, finished_ts = follow(db, meeting, container)
            exit_code = int((container.wait() or {}).get("StatusCode", 1))
    except Exception as exc:  # noqa: BLE001 — the run itself blew up
        _fail(db, service, job, meeting, f"The bot run failed: {exc}", artifacts)
        return

    reason = reason or "error:unknown"
    if exit_code != 0:
        _fail(db, service, job, meeting, reason, artifacts)
        return
    if reason in NOT_ADMITTED_REASONS:
        # No files, nothing to transcribe - the bot never got into the room.
        meeting.status = STATUS_NOT_ADMITTED
        meeting.status_reason = reason
        db.commit()
        service.finish(job, status=JOB_DONE, result={"reason": reason})
        _mark_bot_signed_in(db, meeting.tenant_id)
        return

    duration = _duration_seconds(started_ts, finished_ts)
    try:
        file_id = register_recording(db, meeting, artifacts)
    except Exception as exc:  # noqa: BLE001 — the bot did its job; we did not
        # The audio exists and is still where the bot left it; what failed is
        # ours. Say so on the meeting rather than leaving it stuck in `joining`
        # forever, which is what an uncaught raise here would do.
        logger.exception("meetings recording registration failed for %s", meeting.id)
        db.rollback()
        _fail(db, service, job, meeting, f"The recording could not be stored: {exc}", artifacts)
        return
    meeting.status = STATUS_PROCESSING
    meeting.status_reason = None
    meeting.duration_s = duration
    db.commit()
    _mark_bot_signed_in(db, meeting.tenant_id)
    service.finish(
        job,
        status=JOB_DONE,
        result={"reason": reason, "fileId": file_id, "durationS": duration},
    )
    _enqueue_transcribe(db, meeting)


def _duration_seconds(started_ts: Optional[float], finished_ts: Optional[float]) -> Optional[int]:
    if not started_ts or not finished_ts or finished_ts < started_ts:
        return None
    return int(finished_ts - started_ts)


def _fail(
    db: Session,
    service,
    job: BackgroundJob,
    meeting: Meeting,
    reason: str,
    artifacts: Optional[Artifacts],
) -> None:
    """A run that ended badly: the meeting says so, and the screenshot the bot
    left behind is kept so somebody can see what the page actually showed.

    No retry, ever. A meeting happens once; re-joining it later would join an
    empty room and report a successful capture of nothing."""
    screenshot = None
    if artifacts is not None:
        try:
            if SCREENSHOT_NAME in artifacts.names():
                screenshot = artifacts.key_of(SCREENSHOT_NAME)
        except Exception:  # noqa: BLE001 — a missing screenshot is not the failure
            logger.warning("meetings screenshot lookup failed for %s", meeting.id)
    meeting.status = STATUS_FAILED
    meeting.status_reason = reason
    meeting.screenshot_key = screenshot
    db.commit()
    service.finish(job, status=JOB_FAILED, error=reason, result={"screenshotKey": screenshot})


def _mark_bot_signed_in(db: Session, tenant_id: str) -> None:
    """A run that got as far as Meet proves the notetaker account really signs
    in - the one thing S0 refused to claim without evidence (AC-S0-5). This is
    that evidence, so the connection stops saying UNVERIFIED (AC-S2-12)."""
    from app.models.connection import CONNECTION_STATUS_ACTIVE

    from ..providers import MEET_BOT_PROVIDER

    connection = (
        db.query(Connection)
        .filter(
            Connection.tenant_id == tenant_id,
            Connection.provider == MEET_BOT_PROVIDER,
            Connection.is_active.is_(True),
        )
        .first()
    )
    if connection is None:
        return
    connection.status = CONNECTION_STATUS_ACTIVE
    connection.last_tested_at = datetime.now(timezone.utc)
    connection.last_error = None
    db.commit()


def _enqueue_transcribe(db: Session, meeting: Meeting) -> None:
    from app.jobs.service import JobService

    from ..jobs import TRANSCRIBE

    JobService(db).create_and_enqueue(
        type=TRANSCRIBE,
        tenant_id=meeting.tenant_id,
        payload={"meeting_id": meeting.id, "tenant_id": meeting.tenant_id},
    )
