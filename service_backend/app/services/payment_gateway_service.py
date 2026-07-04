"""Payment-gateway webhook ingest (sprint-4/07 Cluster F slice 3) — CORE.

Plumbing only (plan §1): resolve the tenant from ``connection_id``, verify +
parse the webhook via the provider adapter, write the MASKED idempotency log,
then hand the normalised event to the FINANCE business reaction via the
``finance.apply_payment_event@1`` capability (no cross-module import). The
business flip (Pending→Succeeded, derive Paid) lives in finance.

Idempotency (AC-07-30) = ``UNIQUE(tenant, provider, external_event_id)`` on
``integration_logs`` (a 2nd delivery collides → no-op). Out-of-order events
(AC-07-34) raise ``RetryableWebhook`` so the Celery task retries instead of
hard-failing.
"""
import logging
from typing import Dict, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations import PaymentError, get_provider
from app.integrations.base import WebhookEvent
from app.integrations.masking import mask_payload
from app.models.integration_log import (
    LOG_STATUS_PROCESSED,
    LOG_STATUS_RECEIVED,
    LOG_STATUS_REJECTED,
    IntegrationLog,
)
from app.repositories.connection_repository import ConnectionRepository
from app.repositories.integration_log_repository import IntegrationLogRepository
from app.secrets import decrypt_secret

logger = logging.getLogger("foundryx.payments.webhook")


class RetryableWebhook(Exception):
    """The event is valid but references state not yet present (out-of-order,
    AC-07-34). The worker retries; never a hard fail."""


class PaymentGatewayService:
    def __init__(self, db: Session):
        self.db = db
        self.conn_repo = ConnectionRepository(db)
        self.log_repo = IntegrationLogRepository(db)

    def ingest_webhook(
        self, provider_key: str, connection_id: str, body: bytes, headers: Dict[str, str]
    ) -> Dict[str, str]:
        """Verify + log + dispatch one inbound webhook. Returns a small status
        dict. Tenant is resolved from the connection (AC-07-28) — NEVER from the
        body."""
        # Resolve the connection → tenant (unscoped lookup, then the tenant is
        # taken FROM the row; the webhook is unauthenticated so there is no JWT
        # tenant — this row IS the trust anchor, AC-07-28/49).
        conn = self.conn_repo.get_by_id(connection_id)
        if conn is None or conn.provider != provider_key:
            # No tenant to scope a log to → reject without persisting (can't
            # enumerate connections either way).
            logger.warning("webhook for unknown connection %s (%s)", connection_id, provider_key)
            return {"status": "rejected", "reason": "unknown_connection"}
        tenant_id = conn.tenant_id

        provider = get_provider(provider_key)
        if provider is None or getattr(provider, "type", None) != "payment":
            self._log(tenant_id, conn.id, provider_key, None, None, LOG_STATUS_REJECTED,
                      body, error="provider not available")
            self.db.commit()
            return {"status": "rejected", "reason": "no_provider"}

        config = conn.config_json or {}
        try:
            credentials = decrypt_secret(conn.credentials_json) if conn.credentials_json else {}
        except Exception:  # noqa: BLE001 — InvalidToken etc.
            self._log(tenant_id, conn.id, provider_key, None, None, LOG_STATUS_REJECTED,
                      body, error="credentials undecryptable")
            self.db.commit()
            return {"status": "rejected", "reason": "bad_credentials"}

        # ── signature + timestamp tolerance (AC-07-29) ──
        from app.config import settings

        try:
            event: WebhookEvent = provider.verify_webhook(
                config, credentials,
                body=body, headers=headers,
                tolerance_seconds=settings.payment_webhook_tolerance_seconds,
            )
        except PaymentError as e:
            self._log(tenant_id, conn.id, provider_key, None, None, LOG_STATUS_REJECTED,
                      body, error=str(e))
            self.db.commit()
            return {"status": "rejected", "reason": "verify_failed"}

        # ── idempotent ingest (AC-07-30) ──
        if event.event_id:
            existing = self.log_repo.get_by_event(tenant_id, provider_key, event.event_id)
            if existing is not None:
                logger.info("duplicate webhook %s/%s — no-op", provider_key, event.event_id)
                return {"status": "duplicate"}

        log = self._log(
            tenant_id, conn.id, provider_key, event.event_id, event.event_type,
            LOG_STATUS_RECEIVED, body,
        )
        try:
            self.db.commit()  # claim the idempotency slot before doing work
        except IntegrityError:
            # Concurrent duplicate delivery raced us to the unique slot — no-op.
            self.db.rollback()
            logger.info("race duplicate webhook %s/%s — no-op", provider_key, event.event_id)
            return {"status": "duplicate"}

        # ── dispatch the business reaction (finance, via capability) ──
        try:
            result = self._dispatch_to_finance(tenant_id, provider_key, event)
        except RetryableWebhook:
            # Out-of-order (AC-07-34): mark the log RETRY and re-raise so the
            # Celery task retries. We must DELETE the idempotency row so the retry
            # isn't swallowed as a duplicate.
            self.db.delete(log)
            self.db.commit()
            raise
        log.status = LOG_STATUS_PROCESSED
        log.response_json = mask_payload(result or {})
        self.db.commit()
        # Nest the finance result so its own ``status`` key doesn't clobber the
        # ingest outcome.
        return {"status": "processed", "result": result or {}}

    def _dispatch_to_finance(
        self, tenant_id: str, provider_key: str, event: WebhookEvent
    ) -> Optional[Dict]:
        """Hand the normalised event to finance's reaction capability. Finance is
        a module — call via the capability seam, never import it here. Returns
        the finance result dict (or None when finance is not installed)."""
        from app.module_platform import resolve_capability

        handler = resolve_capability(self.db, tenant_id, "finance.apply_payment_event", 1)
        if handler is None:
            logger.warning("finance.apply_payment_event unavailable for tenant %s", tenant_id)
            return None
        payload = {
            "provider": provider_key,
            "eventId": event.event_id,
            "eventType": event.event_type,
            "externalRef": event.external_ref,
            "externalPaymentId": event.external_payment_id,
            "amount": str(event.amount) if event.amount is not None else None,
            "gatewayFee": str(event.gateway_fee) if event.gateway_fee is not None else None,
        }
        return handler(self.db, tenant_id, payload)

    def _log(
        self, tenant_id, connection_id, provider, event_id, event_type, status, body: bytes, error=None
    ) -> IntegrationLog:
        import json

        try:
            parsed = json.loads(body or b"{}")
        except ValueError:
            # form-encoded (Billplz) or non-JSON — store the raw text masked.
            import urllib.parse

            parsed = {k: v[0] if v else "" for k, v in urllib.parse.parse_qs(body.decode(errors="replace")).items()}
        return self.log_repo.create(
            IntegrationLog(
                tenant_id=tenant_id,
                connection_id=connection_id,
                provider=provider,
                external_event_id=event_id,
                event_type=event_type,
                status=status,
                request_json=mask_payload(parsed),
                error=error,
            )
        )
