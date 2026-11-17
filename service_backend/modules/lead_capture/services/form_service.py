"""A connected source's Instant Forms: questions and the Meta test lead
(plan 64 AC-64-24/30, S-META F7).

Both read the source's stored Page token (tenant-scoped lookup, AC-64-70) and
call Meta through ``MetaLeadClient`` (token in the header only, sanitised error
text, AC-64-71). A Meta refusal becomes a typed ``FormError``
(``token_invalid`` / ``meta_refused``), never a 500.

Test lead (F7): Meta keeps ONE test lead per form; a second POST answers
subcode 1892058. So: list the form's test leads, delete each, RE-READ the list
(a delete answering 1892035 "Could Not Delete Lead" usually did delete - never
trust the answer, trust the list), then POST. A 1892058 on the POST (a test
lead created in between) gets one more clear-and-send. The lead itself then
arrives through the normal ``leadgen`` webhook, marked ``isTest``, and flips a
``WAITING_FOR_TEST`` source to ``LIVE`` (``leadgen_service``).
"""
from __future__ import annotations

import logging
import re
import secrets
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.secrets import decrypt_secret

from ..meta_leads import SUBCODE_TEST_LEAD_EXISTS, MetaLeadClient, MetaLeadError
from ..models import PLATFORM_FACEBOOK, SOURCE_ROUTING_STATES, LcSource

logger = logging.getLogger(__name__)

_FORM_ID_RE = re.compile(r"^[0-9]{1,32}$")
_LEAD_ID_RE = re.compile(r"^[0-9]{1,32}$")
SEND_ATTEMPTS = 2


class FormError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _meta_error(exc: MetaLeadError) -> FormError:
    if exc.unreachable:
        return FormError(502, "meta_unreachable", "Meta could not be reached. Try again.")
    if exc.token_invalid:
        return FormError(400, "token_invalid", "Meta no longer accepts this Page's token. Reconnect the Page.")
    return FormError(400, "meta_refused", exc.message)


def _check_form_id(form_id: str) -> str:
    form_id = (form_id or "").strip()
    if not _FORM_ID_RE.fullmatch(form_id):
        raise FormError(422, "invalid_form_id", "Enter the Instant Form id (digits only).")
    return form_id


def _source(db: Session, tenant_id: str, source_id: str) -> LcSource:
    row = (
        db.query(LcSource)
        .filter(LcSource.id == source_id, LcSource.tenant_id == tenant_id)
        .first()
    )
    if row is None:
        raise FormError(404, "source_not_found", "Source not found.")
    return row


def _page_token(source: LcSource, meta: MetaLeadClient) -> Dict[str, Any]:
    """``{"pageToken", "dev"}`` of a Facebook source, or ``token_invalid``."""
    if source.platform != PLATFORM_FACEBOOK or not source.credentials_encrypted:
        raise FormError(400, "token_invalid", "This source has no Page token. Reconnect the Page.")
    try:
        creds = decrypt_secret(source.credentials_encrypted)
    except Exception:  # noqa: BLE001 - undecryptable: a clean refusal, never a 500
        logger.warning("lead source %s credentials could not be decrypted", source.id)
        creds = {}
    if not creds.get("pageToken") or (meta.configured and creds.get("dev")):
        raise FormError(400, "token_invalid", "This source has no usable Page token. Reconnect the Page.")
    return creds


def form_questions(
    db: Session, tenant_id: str, source_id: str, form_id: str, *, client: Optional[MetaLeadClient] = None
) -> Dict[str, Any]:
    """``{"formId", "formName", "data": [{key, label, type, options}]}``."""
    form_id = _check_form_id(form_id)
    source = _source(db, tenant_id, source_id)
    meta = client or MetaLeadClient()
    creds = _page_token(source, meta)
    try:
        read = meta.form_questions(creds["pageToken"], form_id, dev=bool(creds.get("dev")))
    except MetaLeadError as exc:
        logger.info("form questions read refused (code %s)", exc.code)
        raise _meta_error(exc) from None
    return {"formId": form_id, "formName": read.get("formName"), "data": read.get("questions") or []}


def _clear_test_leads(meta: MetaLeadClient, token: str, form_id: str) -> None:
    """Delete the form's test leads, then re-read: only the list decides."""
    existing = [i for i in meta.list_test_leads(token, form_id) if _LEAD_ID_RE.fullmatch(i)]
    if not existing:
        return
    for lead_id in existing:
        try:
            meta.delete_lead(token, lead_id)
        except MetaLeadError as exc:  # 1892035 is answered even when the delete worked (F7)
            logger.info("test lead delete answered code %s subcode %s", exc.code, exc.subcode)
    if meta.list_test_leads(token, form_id):
        raise FormError(
            409,
            "test_lead_exists",
            "Meta still holds this form's previous test lead. Delete it in Meta's Lead Ads Testing Tool and try again.",
        )


def send_test_lead(
    db: Session, tenant_id: str, source_id: str, form_id: str, *, client: Optional[MetaLeadClient] = None
) -> Dict[str, str]:
    """Ask Meta for a fresh test lead on the form. Answers ``{"formId"}``; the
    lead arrives later through the webhook."""
    form_id = _check_form_id(form_id)
    source = _source(db, tenant_id, source_id)
    if source.status not in SOURCE_ROUTING_STATES:
        # the lead would be dropped at the webhook: say so instead of a 202
        raise FormError(409, "source_not_connected", "This source is not receiving leads. Reconnect the Page.")
    meta = client or MetaLeadClient()
    creds = _page_token(source, meta)
    if creds.get("dev") or not meta.configured:
        if settings.environment != "development":
            raise FormError(400, "token_invalid", "This source has no usable Page token. Reconnect the Page.")
        _dev_test_lead(source, form_id)
        return {"formId": form_id}
    token = creds["pageToken"]
    try:
        for attempt in range(SEND_ATTEMPTS):
            _clear_test_leads(meta, token, form_id)
            try:
                meta.create_test_lead(token, form_id)
                return {"formId": form_id}
            except MetaLeadError as exc:
                if exc.subcode != SUBCODE_TEST_LEAD_EXISTS:
                    raise
                logger.info("test lead create answered 1892058 (attempt %s)", attempt + 1)
    except MetaLeadError as exc:
        logger.info("test lead refused (code %s subcode %s)", exc.code, exc.subcode)
        raise _meta_error(exc) from None
    raise FormError(
        409,
        "test_lead_exists",
        "Meta still holds this form's previous test lead. Delete it in Meta's Lead Ads Testing Tool and try again.",
    )


def _dev_test_lead(source: LcSource, form_id: str) -> None:
    """No Meta app, ``ENVIRONMENT=development`` only: run the canned test lead
    through the normal ingest task, so the LIVE gate can be tried without Meta."""
    from app.workflow_engine.worker import lead_capture_process_leadgen

    leadgen_id = "9" + "".join(secrets.choice("0123456789") for _ in range(14))
    try:
        lead_capture_process_leadgen.delay(source.account_ref or "", leadgen_id, form_id, None)
    except Exception:  # noqa: BLE001 - dev convenience only
        logger.exception("dev test lead enqueue failed")

