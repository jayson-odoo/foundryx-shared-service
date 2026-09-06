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

from pydantic import BaseModel, ConfigDict


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
    for the contacts phase."""

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
