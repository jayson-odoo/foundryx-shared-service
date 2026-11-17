"""Meta ``leadgen`` webhook -> stored, mapped, delivered lead (plan 64 AC-64-26/27/35/37).

``handle_leadgen_change`` is registered with core's Meta webhook registry and
runs inside omnichannel's ingress worker BEFORE its channel lookup, so a Page
with no Messenger channel (or a tenant without omnichannel) still gets its
leads. It only enqueues: the Page is taken from the entry id (never from ids
inside the change value, which is raw Meta data), only ids cross the queue.

``process_leadgen`` (the task) resolves ALL live sources on the Page (shared
Pages, D13), fetches the lead ONCE with the first token that works, and stores
+ maps + queues delivery once per source that does not hold it yet. Idempotent
on (source, leadgen id): a replayed webhook creates nothing.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.repositories.module_repository import ModuleRepository
from app.secrets import decrypt_secret, encrypt_secret

from .. import mapping
from ..meta_leads import MetaLeadClient, MetaLeadError
from ..models import PLATFORM_FACEBOOK, SOURCE_LIVE, SOURCE_ROUTING_STATES, SOURCE_WAITING_FOR_TEST, LcLead, LcSource
from . import delivery_service, field_service, source_service

logger = logging.getLogger(__name__)

MODULE_NAME = "lead_capture"
_ID_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}$")


def _clean_id(value: Any) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        value = str(value)
    return value if isinstance(value, str) and _ID_RE.match(value) else ""


def _live_sources(db: Session, page_id: str) -> List[LcSource]:
    """Sources that receive leads: ``LIVE`` and ``WAITING_FOR_TEST`` (AC-64-16)."""
    return (
        db.query(LcSource)
        .filter(
            LcSource.platform == PLATFORM_FACEBOOK,
            LcSource.account_ref == page_id,
            LcSource.status.in_(SOURCE_ROUTING_STATES),
        )
        .order_by(LcSource.created_at.asc(), LcSource.id.asc())
        .all()
    )


def _active(db: Session, tenant_id: str) -> bool:
    tenant = db.get(Tenant, tenant_id)
    return bool(tenant and tenant.signin_allowed) and ModuleRepository(db).is_active(tenant_id, MODULE_NAME)


def handle_leadgen_change(db: Session, obj: str, entry_id: str, value: Any) -> None:
    """Registry handler: validate the ids, skip Pages nobody holds, enqueue."""
    page_id = _clean_id(entry_id)
    if obj != "page" or not page_id or not isinstance(value, dict):
        return
    leadgen_id = _clean_id(value.get("leadgen_id"))
    if not leadgen_id:
        return
    if not _live_sources(db, page_id):
        logger.info("leadgen for a Page with no live source dropped")
        return
    form_id = _clean_id(value.get("form_id"))
    created = value.get("created_time")
    created_time = created if isinstance(created, int) and not isinstance(created, bool) else None
    _enqueue_after_commit(db, (page_id, leadgen_id, form_id, created_time))


_PENDING_KEY = "lead_capture_pending_leadgen"


def _enqueue_after_commit(db: Session, args: tuple) -> None:
    """Queue the task once the ingress COMMITS (the registry commits right after
    a successful handler; a rolled-back handler queues nothing). Never inside
    the handler's savepoint: an eager run (dev / test copy) would otherwise
    work on the same connection mid-transaction."""
    pending = db.info.setdefault(_PENDING_KEY, [])
    pending.append(args)
    if len(pending) == 1:
        event.listen(db, "after_commit", _fire_pending, once=True)
        event.listen(db, "after_rollback", _drop_pending, once=True)


def _drop_pending(session: Session) -> None:
    session.info.pop(_PENDING_KEY, None)
    if event.contains(session, "after_commit", _fire_pending):
        event.remove(session, "after_commit", _fire_pending)


def _fire_pending(session: Session) -> None:
    pending = session.info.pop(_PENDING_KEY, [])
    if event.contains(session, "after_rollback", _drop_pending):
        event.remove(session, "after_rollback", _drop_pending)
    from app.workflow_engine.worker import lead_capture_process_leadgen

    for args in pending:
        try:
            lead_capture_process_leadgen.delay(*args)
        except Exception:  # noqa: BLE001 - Meta retries the webhook; backfill recovers
            logger.exception("leadgen enqueue failed")


def _source_token(source: LcSource) -> Optional[Dict[str, Any]]:
    try:
        creds = decrypt_secret(source.credentials_encrypted or "")
    except Exception:  # noqa: BLE001 - undecryptable token: try the next source
        logger.warning("lead source %s credentials could not be decrypted", source.id)
        return None
    return creds if creds.get("pageToken") else None


def process_leadgen(
    db: Session,
    page_id: str,
    leadgen_id: str,
    form_id: str = "",
    created_time: Optional[int] = None,
    *,
    client: Optional[MetaLeadClient] = None,
) -> List[str]:
    """Store + deliver one Meta lead for every live source on the Page that
    takes its form. Returns the new lead ids (empty on a replay)."""
    sources = [s for s in _live_sources(db, page_id) if _active(db, s.tenant_id)]
    takers = [s for s in sources if source_service.accepts_form(s, form_id)]
    if not takers:
        return []
    if not _missing(db, takers, leadgen_id):
        return []

    meta = client or MetaLeadClient()
    configured = meta.configured
    raw: Optional[Dict[str, Any]] = None
    token_used: Optional[Dict[str, Any]] = None
    last_error: Optional[MetaLeadError] = None
    dead: set = set()
    for source in list(sources):  # first healthy token on the Page (AC-64-37)
        creds = _source_token(source)
        if creds is None or (configured and creds.get("dev")):
            continue  # a dev credential never answers once a real Meta app is set
        try:
            raw = meta.get_lead(creds["pageToken"], leadgen_id, form_id, dev=bool(creds.get("dev")))
            token_used = creds
            break
        except MetaLeadError as exc:
            last_error = exc
            logger.warning("lead read failed with one source token (code %s)", exc.code)
            if exc.token_invalid:
                source_service.mark_needs_reconnect(db, source.id)  # AC-64-29
                dead.add(source.id)
    if raw is None or token_used is None:
        raise last_error or MetaLeadError("No usable Page token for this Page.")

    lead_form = _clean_id(raw.get("form_id")) or form_id
    todo = [s for s in _live_sources(db, page_id) if s.id not in dead and _active(db, s.tenant_id)]
    todo = [s for s in todo if source_service.accepts_form(s, lead_form)]
    return store_lead(
        db, page_id, raw, todo, meta=meta, token=token_used, form_id_hint=form_id, created_time=created_time
    )


def _missing(db: Session, sources: List[LcSource], leadgen_id: str) -> List[LcSource]:
    held = {
        sid for (sid,) in db.query(LcLead.source_id)
        .filter(LcLead.platform == PLATFORM_FACEBOOK, LcLead.platform_lead_id == leadgen_id,
                LcLead.source_id.in_([s.id for s in sources]))
        .all()
    }
    return [s for s in sources if s.id not in held]


def store_lead(
    db: Session,
    page_id: str,
    raw: Dict[str, Any],
    sources: List[LcSource],
    *,
    meta: MetaLeadClient,
    token: Dict[str, Any],
    form_id_hint: str = "",
    created_time: Optional[int] = None,
) -> List[str]:
    """THE store path for a lead read from Meta, shared by the webhook and the
    backfill (AC-64-28): one ``lc_lead`` per source in ``sources`` that does
    not hold it yet (idempotent on (source, platform lead id), AC-64-27), each
    mapped with that source's own map and delivered to that tenant only.
    Commits, then hands the deliveries to the worker."""
    leadgen_id = _clean_id(raw.get("id"))
    if not leadgen_id or not sources:
        return []
    todo = _missing(db, sources, leadgen_id)
    if not todo:
        return []
    dev = bool(token.get("dev")) or not meta.configured
    lead_form = _clean_id(raw.get("form_id")) or form_id_hint
    ad_id = _clean_id(raw.get("ad_id"))
    if dev:
        is_test = True
    elif ad_id:
        is_test = False
    else:
        test_ids = meta.test_lead_ids(token["pageToken"], lead_form)
        is_test = bool(test_ids and leadgen_id in test_ids)

    answers = mapping.answers_from(raw.get("field_data"))
    platform_created = mapping.parse_meta_time(raw.get("created_time")) or mapping.parse_meta_time(created_time)
    attribution = {
        "pageId": page_id,
        "formId": lead_form or None,
        "adId": ad_id or None,
        "adsetId": _clean_id(raw.get("adset_id")) or None,
        "campaignId": _clean_id(raw.get("campaign_id")) or None,
        "isOrganic": raw.get("is_organic") if isinstance(raw.get("is_organic"), bool) else None,
    }
    now = datetime.now(timezone.utc)
    # L-A gap (b): on a shared Page, Meta's test lead reaches every product,
    # but only the source(s) that asked for it pass their test. A test lead
    # nobody asked for (Meta's own Testing Tool) passes every waiting source.
    askers = (
        {s.id for s in _live_sources(db, page_id) if test_requested(s, lead_form, now)} if is_test else set()
    )
    created_ids: List[str] = []
    delivery_ids: List[str] = []
    form_name = _form_name(meta, todo, token, lead_form, dev)
    target_cache: Dict[str, List] = {}
    for source in todo:
        if source.tenant_id not in target_cache:
            target_cache[source.tenant_id] = field_service.targets(db, source.tenant_id)
        targets = target_cache[source.tenant_id]
        form_map, has_map = mapping.form_map_for(source.field_map_json, lead_form)
        fields, unmapped = mapping.map_answers(answers, form_map, targets)
        lead = LcLead(
            tenant_id=source.tenant_id,
            source_id=source.id,
            platform=PLATFORM_FACEBOOK,
            platform_lead_id=leadgen_id,
            form_id=lead_form or None,
            form_name=form_name,
            received_at=now,
            platform_created_at=platform_created,
            fields_encrypted=encrypt_secret({"fields": fields, "answers": answers}),
            raw_encrypted=encrypt_secret({"raw": raw}),
            attribution_json=attribution,
            phone_e164=mapping.normalise_phone(mapping.typed_value(fields, targets, "phone")),
            email=mapping.normalise_email(mapping.typed_value(fields, targets, "email")),
            is_test=is_test,
        )
        try:
            with db.begin_nested():
                db.add(lead)
                db.flush()
        except IntegrityError:
            continue  # a parallel run stored it first (AC-64-27)
        source.last_lead_at = now
        if (
            is_test
            and source.status == SOURCE_WAITING_FOR_TEST
            and (not askers or source.id in askers)
        ):
            source.status = SOURCE_LIVE  # the source passed its test (AC-64-16)
        if lead_form and not has_map and unmapped:
            notice = dict(source.needs_mapping_json or {})
            notice[lead_form] = {"formId": lead_form, "formName": form_name, "unmappedCount": unmapped}
            source.needs_mapping_json = notice
        body = mapping.lead_body(
            lead_id=lead.id,
            source_id=source.id,
            source_name=source.name,
            platform=PLATFORM_FACEBOOK,
            platform_lead_id=leadgen_id,
            page_id=page_id,
            form_id=lead_form or None,
            form_name=form_name,
            received_at=now,
            platform_created_at=platform_created,
            is_test=is_test,
            duplicate_of=None,
            fields=fields,
            answers=answers,
            attribution=attribution,
        )
        delivery_ids += delivery_service.queue_event(
            db, source.tenant_id, delivery_service.EVENT_LEAD_CREATED, body, lead_id=lead.id
        )
        created_ids.append(lead.id)
    db.commit()
    delivery_service.enqueue(delivery_ids)
    return created_ids


# ── test-lead requests (L-A gaps a/b) ──────────────────────────────────────
TEST_REQUESTS_KEY = "testLeadRequests"
TEST_REQUEST_WINDOW = timedelta(hours=1)


def _request_time(source: LcSource, form_id: str) -> Optional[datetime]:
    value = ((source.config_json or {}).get(TEST_REQUESTS_KEY) or {}).get(form_id)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def test_requested(source: LcSource, form_id: str, now: datetime) -> bool:
    """This source asked Meta for a test lead on ``form_id`` within the hour."""
    when = _request_time(source, form_id) if form_id else None
    return when is not None and now - when <= TEST_REQUEST_WINDOW


def last_test_request(source: LcSource, form_id: str) -> Optional[datetime]:
    return _request_time(source, form_id)


def note_test_request(source: LcSource, form_id: str, now: datetime) -> None:
    config = dict(source.config_json or {})
    requests = {
        k: v for k, v in (config.get(TEST_REQUESTS_KEY) or {}).items()
        if isinstance(v, str) and (_request_time(source, k) or now) > now - TEST_REQUEST_WINDOW
    }
    requests[form_id] = now.isoformat()
    config[TEST_REQUESTS_KEY] = requests
    source.config_json = config  # fresh dict: in-place JSON edits are not tracked


_FORM_NAMES_KEY = "formNames"


def _form_name(
    meta: MetaLeadClient, sources: List[LcSource], token: Dict[str, Any], form_id: str, dev: bool
) -> Optional[str]:
    """The form's name, cached per source in ``config_json["formNames"]`` (each
    tenant's own row; a shared Page reads it once and every source on the Page
    keeps a copy). Only a name actually read is cached, so a failed read is
    retried with the next lead. No commit here: the lead transaction owns it."""
    if not form_id:
        return None
    for source in sources:
        cached = ((source.config_json or {}).get(_FORM_NAMES_KEY) or {}).get(form_id)
        if isinstance(cached, str) and cached:
            name = cached
            break
    else:
        name = meta.form_name(token["pageToken"], form_id, dev=dev)
        if not name:
            return None
    for source in sources:
        config = dict(source.config_json or {})
        names = dict(config.get(_FORM_NAMES_KEY) or {})
        if names.get(form_id) != name:
            names[form_id] = name
            config[_FORM_NAMES_KEY] = names
            source.config_json = config  # fresh dict: in-place JSON edits are not tracked
    return name


def lead_item(lead: LcLead, source: LcSource) -> Dict[str, Any]:
    """Rebuild the documented lead body from a stored row (pull API)."""
    fields: Dict[str, Any] = {}
    answers: List[Dict[str, Any]] = []
    if lead.fields_encrypted and lead.purged_at is None:
        try:
            stored = decrypt_secret(lead.fields_encrypted)
            fields, answers = stored.get("fields") or fields, stored.get("answers") or []
        except Exception:  # noqa: BLE001 - undecryptable: ids only
            logger.warning("lead %s fields could not be decrypted", lead.id)
    attribution = lead.attribution_json or {}
    return mapping.lead_body(
        lead_id=lead.id,
        source_id=source.id,
        source_name=source.name,
        platform=lead.platform,
        platform_lead_id=lead.platform_lead_id,
        page_id=attribution.get("pageId") or source.account_ref,
        form_id=lead.form_id,
        form_name=lead.form_name,
        received_at=lead.received_at,
        platform_created_at=lead.platform_created_at,
        is_test=lead.is_test,
        duplicate_of=lead.duplicate_of,
        fields=fields,
        answers=answers,
        attribution=attribution,
    )
