"""Phone step behind a feedback share link (lane FEEDBACK-SUBSCRIBE).

Owner 17 Nov: anyone may READ a shared item; to follow, comment or upvote the
visitor gives their phone, the item's PRODUCT checks it is one of its contacts
and proves it with a WhatsApp code, then the visitor continues as that contact
(their own personal board link + portal session).

Contract (crew, 17 Nov, final): SS makes and checks the code (6 digits,
hashed, 10 minutes, 5 tries, single use - the same rules as the CRM's own
sign-in code); every product implements only two generic calls:

- ``POST {base}/api/v1/external/ideation/contacts/lookup`` ``{phone, phoneDigits}``
  -> 200 ``{contactId, name, phone}`` | 404 not one of our contacts;
- ``POST {base}/api/v1/external/ideation/phone/send-code`` ``{phone, phoneDigits, code}``
  -> 2xx sent over the product's existing WhatsApp code template (Sorento:
  ``portal_otp``, only param ``otp_code``) | 429 | else unavailable.

The product is reached over the tenant's consumer connection for the item's
product: an active ``consumer`` connection whose ``config.productId`` is the
item's product, else the tenant's ONE active consumer connection without a
product tag. No product-specific code. Keys never logged.
"""
import hashlib
import hmac
import math
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models.catalog import Product
from app.services.throttle import Throttled, ThrottleService
from modules.omnichannel.models import Contact, Workspace

from ..models import Idea, IdeaPhoneCode
from .feedback_links import get_or_create_link, mint_board_link
from .ownership import find_contacts_by_phone, phone_digits
from .portal import (
    KIND_CONTACT,
    PortalError,
    PortalPrincipal,
    _session_out,
    first_name,
    share_principal,
)

logger = logging.getLogger(__name__)

LOOKUP_PATH = "/api/v1/external/ideation/contacts/lookup"
SEND_CODE_PATH = "/api/v1/external/ideation/phone/send-code"
CODE_DIGITS = 6
CODE_TTL_MINUTES = 10
CODE_MAX_ATTEMPTS = 5
TIMEOUT_SECONDS = 8.0
CONSUMER_TYPE = "consumer"

# Test seam (like ``crm_poke._transport``).
_transport: Optional[httpx.BaseTransport] = None


def _unavailable() -> PortalError:
    return PortalError(503, "unavailable", "We could not check your number right now. Try again.")


def _not_set_up() -> PortalError:
    """The product refused us (403): its integration user lacks the phone
    check permission. Not retryable by the visitor, so not "try again"."""
    return PortalError(503, "not_set_up", "Phone check is not set up for this product yet.")


def _too_many(retry_after_seconds: int) -> PortalError:
    """Same words as the CRM sign-in: the wait in whole minutes."""
    minutes = max(1, math.ceil(retry_after_seconds / 60))
    unit = "minute" if minutes == 1 else "minutes"
    return PortalError(
        429, "too_many_attempts", f"Too many tries. Try again in {minutes} {unit}.", retry_after_seconds
    )


def _throttled(exc: Throttled) -> PortalError:
    return _too_many(exc.retry_after_seconds)


def product_target(db: Session, tenant_id: str, product_id: Optional[str]) -> Optional[Tuple[str, str]]:
    """``(base_url, api_key)`` of the connection that speaks for this product,
    else ``None``. Tenant-scoped; never an ERROR or inactive connection."""
    from app.models.connection import CONNECTION_STATUS_ERROR, Connection
    from app.secrets import decrypt_secret

    rows = (
        db.query(Connection)
        .filter(
            Connection.tenant_id == tenant_id,
            Connection.type == CONSUMER_TYPE,
            Connection.is_active.is_(True),
        )
        .order_by(Connection.created_at.asc(), Connection.id.asc())
        .all()
    )
    active = len(rows)
    rows = [r for r in rows if r.status != CONNECTION_STATUS_ERROR]
    tagged = [r for r in rows if product_id and (r.config_json or {}).get("productId") == product_id]
    untagged = [r for r in rows if not (r.config_json or {}).get("productId")]
    conn = tagged[0] if tagged else (untagged[0] if len(untagged) == 1 else None)
    if conn is None:
        if not active:
            _no_target("no active consumer connection")
        elif not rows:
            _no_target("every active consumer connection is in error")
        elif len(untagged) > 1:
            _no_target(f"no connection tagged for the product and {len(untagged)} untagged ones")
        else:
            _no_target("no connection tagged for the product and no untagged one")
        return None
    base = str((conn.config_json or {}).get("baseUrl") or "").strip().rstrip("/")
    if not base:
        _no_target("connection has no base URL", conn.id)
        return None
    if not conn.credentials_json:
        _no_target("connection has no stored key", conn.id)
        return None
    try:
        key = str(decrypt_secret(conn.credentials_json).get("apiKey") or "").strip()
    except Exception:  # noqa: BLE001 - an undecryptable key = no target
        _no_target("connection key cannot be decrypted", conn.id)
        return None
    if not key:
        _no_target("connection has an empty key", conn.id)
        return None
    return base, key


def _no_target(reason: str, connection_id: Optional[str] = None) -> None:
    """Why the phone step found no product to ask. Names the branch and the
    connection id only: never a key, URL or phone."""
    logger.warning(
        "feedback phone step: no product target: %s%s",
        reason,
        f" (connection {connection_id})" if connection_id else "",
    )


def _product_name(db: Session, tenant_id: str, product_id: Optional[str]) -> str:
    row = (
        db.query(Product.name)
        .filter(Product.id == product_id, Product.tenant_id == tenant_id)
        .first()
        if product_id
        else None
    )
    return (row[0] if row else None) or "us"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(row_id: str, code: str) -> str:
    """Keyed hash of the code, bound to its row (a hash never verifies another
    row's code). The code itself is never stored or logged."""
    return hmac.new(
        settings.jwt_secret.encode("utf-8"), f"{row_id}:{code}".encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _phone_key(tenant_id: str, digits: str) -> str:
    """Throttle key for a phone: per tenant, so traffic in one tenant never
    locks the same person out of another."""
    return f"{tenant_id}:{digits}"


def _wrong_code(tries_left: int) -> PortalError:
    """Same words as the CRM sign-in: how many tries this code has left."""
    if tries_left <= 0:
        return PortalError(400, "wrong_code", "That code is not right.")
    unit = "try" if tries_left == 1 else "tries"
    return PortalError(400, "wrong_code", f"That code is not right. {tries_left} {unit} left.")


def _code_expired() -> PortalError:
    return PortalError(400, "code_expired", "That code has expired. Send a new one.")


def _call(target: Tuple[str, str], path: str, body: Dict[str, Any]) -> httpx.Response:
    base, key = target
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, transport=_transport) as client:
            return client.post(f"{base}{path}", json=body, headers={"X-API-Key": key})
    except httpx.HTTPError as exc:
        logger.warning("feedback phone step: product call failed: %s", type(exc).__name__)
        raise _unavailable()


class PhoneStep:
    def __init__(self, db: Session, token: str, ip: str):
        self.db = db
        self.ip = ip
        self.p, self.idea_id = share_principal(db, token)
        self.idea = (
            db.query(Idea).filter(Idea.id == self.idea_id, Idea.tenant_id == self.p.tenant_id).first()
        )

    def _prepare(self, phone: str) -> Tuple[str, Tuple[str, str], Dict[str, Any]]:
        digits = phone_digits(phone)
        if not digits:
            raise PortalError(422, "invalid_phone", "Enter a valid phone number.")
        throttle = ThrottleService(self.db)
        try:
            throttle.enforce_idea_follow_phone(ip=self.ip, phone_key=_phone_key(self.p.tenant_id, digits))
        except Throttled as exc:
            raise _throttled(exc)
        throttle.record_idea_follow_phone(ip=self.ip, phone_key=_phone_key(self.p.tenant_id, digits))
        target = product_target(self.db, self.p.tenant_id, self.p.product_id)
        if target is None:
            raise _unavailable()
        return digits, target, {"phone": f"+{digits}", "phoneDigits": digits}

    def _not_registered(self) -> PortalError:
        name = _product_name(self.db, self.p.tenant_id, self.p.product_id)
        return PortalError(
            404,
            "not_registered",
            f"This number isn't registered with {name}. Ask your {name} contact to add you.",
        )

    def _common_errors(self, res: httpx.Response) -> None:
        if res.status_code == 404:
            raise self._not_registered()
        if res.status_code == 429:
            raise _too_many(900)
        if res.status_code == 403:
            raise _not_set_up()

    def send_code(self, phone: str) -> Dict[str, Any]:
        """Ask the product whether this phone is one of its contacts; if so,
        issue a fresh code (earlier ones for this phone are cancelled) and have
        the product deliver it over WhatsApp."""
        digits, target, body = self._prepare(phone)
        res = _call(target, LOOKUP_PATH, body)
        if res.status_code not in (200, 404):
            logger.warning("feedback phone step: lookup refused: HTTP %s", res.status_code)
        self._common_errors(res)
        if res.status_code != 200:
            raise _unavailable()
        try:
            name = str((res.json() or {}).get("name") or "").strip() or None
        except ValueError:
            raise _unavailable()

        now = _now()
        self.db.query(IdeaPhoneCode).filter(
            IdeaPhoneCode.tenant_id == self.p.tenant_id,
            IdeaPhoneCode.phone_digits == digits,
            IdeaPhoneCode.used_at.is_(None),
        ).update({IdeaPhoneCode.used_at: now}, synchronize_session=False)
        code = f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"
        row_id = str(uuid.uuid4())
        row = IdeaPhoneCode(
            id=row_id,
            code_hash=_hash(row_id, code),
            tenant_id=self.p.tenant_id,
            phone_digits=digits,
            contact_name=name,
            attempts=0,
            created_at=now,
            expires_at=now + timedelta(minutes=CODE_TTL_MINUTES),
        )
        self.db.add(row)
        self.db.commit()

        try:
            sent = _call(target, SEND_CODE_PATH, {**body, "code": code})
        except PortalError:
            self._void(row_id)
            raise
        if 200 <= sent.status_code < 300:
            return {"sent": True}
        # Not delivered: the code must not stay usable.
        self._void(row_id)
        logger.warning("feedback phone step: send-code refused: HTTP %s", sent.status_code)
        self._common_errors(sent)
        raise _unavailable()

    def verify(self, phone: str, code: str) -> Dict[str, Any]:
        """Check the code SS issued for this phone; on success the visitor
        continues as their own contact. 5 wrong tries end the code."""
        code = (code or "").strip()
        digits = phone_digits(phone)
        if not digits:
            raise PortalError(422, "invalid_phone", "Enter a valid phone number.")
        throttle = ThrottleService(self.db)
        try:
            throttle.enforce_idea_follow_phone(ip=self.ip, phone_key=_phone_key(self.p.tenant_id, digits))
        except Throttled as exc:
            raise _throttled(exc)
        # Every attempt counts BEFORE the code is compared (a parallel burst
        # cannot slip past the throttle's read-then-write window).
        throttle.record_idea_follow_phone(ip=self.ip, phone_key=_phone_key(self.p.tenant_id, digits))
        row = (
            self.db.query(IdeaPhoneCode)
            .filter(
                IdeaPhoneCode.tenant_id == self.p.tenant_id,
                IdeaPhoneCode.phone_digits == digits,
                IdeaPhoneCode.used_at.is_(None),
                IdeaPhoneCode.expires_at > _now(),
            )
            .order_by(IdeaPhoneCode.created_at.desc())
            .first()
        )
        # Claim one try atomically (``attempts < MAX`` in the UPDATE itself):
        # concurrent guesses can never exceed the cap, whatever the interleave.
        claimed = 0
        used_before = row.attempts if row is not None else 0
        if row is not None:
            claimed = (
                self.db.query(IdeaPhoneCode)
                .filter(
                    IdeaPhoneCode.id == row.id,
                    IdeaPhoneCode.used_at.is_(None),
                    IdeaPhoneCode.attempts < CODE_MAX_ATTEMPTS,
                )
                .update({IdeaPhoneCode.attempts: IdeaPhoneCode.attempts + 1}, synchronize_session=False)
            )
            self.db.commit()
        if not claimed:
            raise _code_expired()
        if not (code.isdigit() and hmac.compare_digest(row.code_hash, _hash(row.id, code))):
            # The try that used up the last attempt ends the code.
            self.db.query(IdeaPhoneCode).filter(
                IdeaPhoneCode.id == row.id, IdeaPhoneCode.attempts >= CODE_MAX_ATTEMPTS
            ).update({IdeaPhoneCode.used_at: _now()}, synchronize_session=False)
            self.db.commit()
            raise _wrong_code(CODE_MAX_ATTEMPTS - (used_before + 1))
        # Single use, atomically: only the first correct request wins.
        won = (
            self.db.query(IdeaPhoneCode)
            .filter(IdeaPhoneCode.id == row.id, IdeaPhoneCode.used_at.is_(None))
            .update({IdeaPhoneCode.used_at: _now()}, synchronize_session=False)
        )
        if not won:
            self.db.commit()
            raise _code_expired()
        contact = self._contact_for(digits, row.contact_name)
        return self._session(contact)

    def _void(self, row_id: str) -> None:
        self.db.query(IdeaPhoneCode).filter(
            IdeaPhoneCode.id == row_id, IdeaPhoneCode.used_at.is_(None)
        ).update({IdeaPhoneCode.used_at: _now()}, synchronize_session=False)
        self.db.commit()

    def _contact_for(self, digits: str, name: Optional[str]) -> Contact:
        """The SS contact for the proven phone (same-phone rule), created in the
        tenant's workspace when absent so status updates have a recipient."""
        tenant_id = self.p.tenant_id
        found = find_contacts_by_phone(self.db, tenant_id, f"+{digits}")
        if found:
            return found[0]
        workspace = (
            self.db.query(Workspace)
            .filter(Workspace.tenant_id == tenant_id)
            .order_by(Workspace.created_at.asc(), Workspace.id.asc())
            .first()
        )
        if workspace is None:
            raise _unavailable()
        contact = Contact(
            tenant_id=tenant_id,
            workspace_id=workspace.id,
            first_name=name,
            phone=f"+{digits}",
            phone_digits=digits,
        )
        self.db.add(contact)
        self.db.flush()
        return contact

    def _session(self, contact: Contact) -> Dict[str, Any]:
        """A contact portal session for ``contact`` (the same shape the personal
        link exchange returns) + their personal board link opening this item."""
        board_url = mint_board_link(self.db, self.idea, contact.id) if self.idea is not None else None
        # One live link per contact PER PRODUCT (lane SS-MULTI-PRODUCT-BOARD):
        # the session is the same per-product link ``mint_board_link`` opens.
        product_id = self.idea.product_id if self.idea is not None else None
        link = get_or_create_link(self.db, self.p.tenant_id, contact.id, product_id)
        self.db.commit()
        p = PortalPrincipal(
            tenant_id=self.p.tenant_id,
            kind=KIND_CONTACT,
            subject=contact.id,
            name=first_name(contact.first_name),
            phone=contact.phone,
            link_id=link.id,
            product_id=link.product_id,
        )
        return {**_session_out(self.db, p), "boardUrl": board_url}
