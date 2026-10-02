"""Plain pydantic mirrors of the respond.io Developer API v2's EXACT field
names (plan 33 §5.1, D-A6 risk note) - deliberately NOT ``ApiModel``/camelCase
translation, because these model the VENDOR's wire, not ours. Every model
carries ``extra="ignore"`` so an added vendor field never breaks a run - a
shape mismatch is a fix here, not a redesign (plan §9 risk).

S1 only needs ``SpaceChannel``/``SpaceUser``/``CustomField``/``Contact``
(preflight + the connection test). Slice S3 adds the message-item union
(``ContactChannel``, message shapes) alongside the identity/message writer
that consumes them - kept out of S1 to avoid guessing at a shape nobody
exercises yet.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class VendorModel(BaseModel):
    """Base for every respond.io wire mirror - unknown vendor fields are
    dropped, never rejected (extra="ignore")."""

    model_config = ConfigDict(extra="ignore")


class RespondIoErrorBody(VendorModel):
    """The vendor's ``Error`` shape (§5.1) - carried verbatim on
    ``RespondIoError`` for a caller that needs the raw vendor code (AC-MIG-16)."""

    code: Optional[Any] = None
    message: Optional[str] = None


class SpaceChannel(VendorModel):
    """``GET /space/channel`` item - preflight + ``test()`` (AC-MIG-13/14)."""

    id: int
    name: str
    source: str
    created_at: Optional[int] = None


class SpaceUserTeam(VendorModel):
    id: int
    name: str


class SpaceUser(VendorModel):
    """``GET /space/user`` item - the user + team map (AC-MIG-14)."""

    id: int
    firstName: str
    lastName: Optional[str] = ""
    email: str
    role: Optional[str] = None
    team: Optional[SpaceUserTeam] = None
    restrictions: Optional[List[Any]] = None


class CustomField(VendorModel):
    """``GET /space/custom_field`` item - the field-type map (AC-MIG-14/24)."""

    id: int
    name: str
    description: Optional[str] = None
    dataType: str
    allowedValues: Optional[List[str]] = None


class ContactAssignee(VendorModel):
    id: int
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: Optional[str] = None


class Contact(VendorModel):
    """``POST /contact/list`` / ``GET /contact/{id}`` item (§5.1). S1 only
    reads ``lifecycle`` (the preflight distinct pass); S2 consumes the rest
    for the contacts phase. S3's messages phase re-fetches this shape per
    contact (``GET /contact/{identifier}``) purely for ``created_at`` - the
    D-A6-9 timestamp fallback."""

    id: int
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    language: Optional[str] = None
    countryCode: Optional[str] = None
    custom_fields: Optional[List[Dict[str, Any]]] = None
    status: Optional[str] = None
    tags: Optional[List[str]] = None
    assignee: Optional[ContactAssignee] = None
    lifecycle: Optional[str] = None
    created_at: Optional[int] = None


# ═══════════════════════════════════════════════════════════════════════════
# S3 - channel identities + message history (AC-MIG-30..38, plan §5.1/§5.4)
# ═══════════════════════════════════════════════════════════════════════════


class ContactChannel(VendorModel):
    """``GET /contact/{identifier}/channels`` item - one per channel the
    contact has been reached on. The vendor's own published shape carries no
    dedicated "external user id" field; ``meta`` is documented only as a free
    ``{...}`` bag, so the real per-channel identifier (a WhatsApp number, a
    Messenger PSID, ...) has to be read out of it defensively (D-A6-10,
    AC-MIG-30) - see ``channel_map.derive_external_user_id``. ``id`` is the
    vendor's own stable identity-row id, used as this row's ``migration_refs``
    external id (there is no other natural key)."""

    id: int
    name: Optional[str] = None
    source: str
    meta: Optional[Dict[str, Any]] = None
    lastMessageTime: Optional[int] = None
    lastIncomingMessageTime: Optional[int] = None
    created_at: Optional[int] = None


class MessageStatus(VendorModel):
    """One entry of a message item's ``status[]`` (§5.1) - receipt-driven,
    so an INBOUND message routinely carries none at all (D-A6-9/F2)."""

    value: Optional[str] = None
    timestamp: Optional[int] = None
    message: Optional[str] = None


class MessageSender(VendorModel):
    source: Optional[str] = None
    userId: Optional[int] = None
    teamId: Optional[int] = None
    workflowId: Optional[Any] = None
    broadcastHistoryId: Optional[Any] = None


class MessageContent(BaseModel):
    """The message item's ``message`` union object (§5.1/§5.4). Deliberately
    ``extra="allow"`` - NOT the house ``VendorModel`` ``extra="ignore"`` -
    because the ``custom_payload`` variant's real fields are, by definition,
    arbitrary tenant-authored payload; dropping unknown keys there would
    silently lose the row the writer is supposed to preserve verbatim in
    ``payload_json.custom`` (AC-MIG-35). Every other documented variant's
    fields are still declared explicitly below so a normal read never falls
    back to the untyped bag."""

    model_config = ConfigDict(extra="allow")

    type: Optional[str] = None
    text: Optional[str] = None
    attachment: Optional[Dict[str, Any]] = None
    title: Optional[str] = None
    replies: Optional[List[Any]] = None
    subject: Optional[str] = None
    cc: Optional[List[str]] = None
    bcc: Optional[List[str]] = None
    attachments: Optional[List[Any]] = None
    template: Optional[Dict[str, Any]] = None


class MessageItem(VendorModel):
    """``GET /contact/{identifier}/message/list`` item (§5.1). NO top-level
    timestamp (F2, D-A6-9) - only the receipt-driven ``status[]``."""

    messageId: int
    channelMessageId: Optional[Any] = None
    contactId: Optional[int] = None
    channelId: Optional[int] = None
    traffic: str
    message: MessageContent = Field(default_factory=MessageContent)
    status: Optional[List[MessageStatus]] = None
    sender: Optional[MessageSender] = None
