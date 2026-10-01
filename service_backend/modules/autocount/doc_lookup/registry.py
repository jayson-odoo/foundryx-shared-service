"""The AutoCount doc-type registry (plan 17 section 3, D2).

One ``AcDocType`` per AutoCount document type: its day doors, field names,
number prefixes and the stored history it maps to. The search code reads ONLY
this registry, so a new type (Invoice, Cash Sale, SO, RMA ...) is one
``register_doc_type`` call once its vendor paths are confirmed on the host.
Mirrors the module's other code-side registries (StatusEntity / FactSource):
duplicate keys are a loud boot error.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Literal, Optional, Tuple

from ..doc_feed.constants import (
    DO_BY_DOC_DATE_PATH,
    DO_BY_LAST_MODIFIED_PATH,
    FEED_DELIVERY_ORDERS,
    FEED_GOODS_RECEIVE_NOTES,
    GRN_BY_DOC_DATE_PATH,
    GRN_BY_LAST_MODIFIED_PATH,
)

DEFAULT_DOC_TYPE = "delivery_order"


class DocTypeRegistryError(Exception):
    """A malformed or duplicate registry entry (boot-time, loud)."""


@dataclass(frozen=True)
class ByDocNoDoor:
    """A direct by-number door (D6). Reserved slot: no host we serve answers
    one today (crew probe 2026-10-01: ``POST .../DeliveryOrder/GetDeliveryOrder``
    is 404 on hapi.sorento.cc.cd), so no entry sets it and the search never
    sends it. Declared so the registry shape is stable when one appears."""

    method: Literal["GET", "POST"]
    path: str
    body: Optional[Callable[[str], dict]] = None
    param: Optional[str] = None


@dataclass(frozen=True)
class AcDocType:
    key: str
    label: str
    feed: str  # the doc feed whose AutoCount connection the lookup reads through
    by_doc_date_path: str
    by_doc_date_param: str = "DocDate"
    by_last_modified_path: Optional[str] = None
    by_last_modified_param: str = "lastModified"
    doc_no_field: str = "DocNo"
    doc_key_field: str = "DocKey"
    doc_date_field: str = "DocDate"
    last_modified_field: str = "LastModified"
    last_modified_user_field: str = "LastModifiedUserID"
    cancelled_field: str = "Cancelled"  # "T" / "F"
    lines_field: str = "Details"
    doc_no_prefixes: Tuple[str, ...] = ()
    snapshot_entity_type: Optional[str] = None  # ac_pull_snapshot.entity_type
    ledger_feed: Optional[str] = None  # ac_doc_feed_ledger.feed
    by_doc_no: Optional[ByDocNoDoor] = None
    module: str = "autocount"


_REGISTRY: Dict[str, AcDocType] = {}


def register_doc_type(doc_type: AcDocType) -> None:
    existing = _REGISTRY.get(doc_type.key)
    if existing is not None:
        if existing is doc_type:
            return  # idempotent re-registration of the SAME object
        raise DocTypeRegistryError(f"AutoCount doc type '{doc_type.key}' is already registered.")
    if not doc_type.by_doc_date_path.startswith("/"):
        raise DocTypeRegistryError(f"'{doc_type.key}': by_doc_date_path must start with '/'.")
    _REGISTRY[doc_type.key] = doc_type


def get_doc_type(key: str) -> Optional[AcDocType]:
    return _REGISTRY.get(key)


def all_doc_types() -> List[AcDocType]:
    return list(_REGISTRY.values())


def detect_doc_type(doc_no: str) -> AcDocType:
    """The type whose LONGEST prefix starts the number (case-insensitive);
    the default type when nothing matches."""
    wanted = doc_no.strip().casefold()
    best: Optional[AcDocType] = None
    best_len = 0
    for doc_type in _REGISTRY.values():
        for prefix in doc_type.doc_no_prefixes:
            folded = prefix.casefold()
            if wanted.startswith(folded) and len(folded) > best_len:
                best, best_len = doc_type, len(folded)
    return best or _REGISTRY[DEFAULT_DOC_TYPE]


DELIVERY_ORDER = AcDocType(
    key="delivery_order",
    label="Delivery order",
    feed=FEED_DELIVERY_ORDERS,
    by_doc_date_path=DO_BY_DOC_DATE_PATH,
    by_last_modified_path=DO_BY_LAST_MODIFIED_PATH,
    doc_no_prefixes=("PS", "DO"),
    snapshot_entity_type=FEED_DELIVERY_ORDERS,
    ledger_feed=FEED_DELIVERY_ORDERS,
)

GOODS_RECEIVE_NOTE = AcDocType(
    key="goods_receive_note",
    label="Goods received note",
    feed=FEED_GOODS_RECEIVE_NOTES,
    by_doc_date_path=GRN_BY_DOC_DATE_PATH,
    by_last_modified_path=GRN_BY_LAST_MODIFIED_PATH,
    doc_no_prefixes=("GRN", "GR"),
    ledger_feed=FEED_GOODS_RECEIVE_NOTES,
)

register_doc_type(DELIVERY_ORDER)
register_doc_type(GOODS_RECEIVE_NOTE)
