"""Canonical record base — provenance every canonical record carries.

``source_system`` + ``source_ref`` are specified by the consumer's own
`SCM_Module_Build_Plan.md`; they are not an ESB invention. Together they are the
correlation handle for every downstream operation: dedupe, re-push, divergence
detection and (slice 4+) write-back correlation.

``source_ref`` is the vendor's **``DocKey``**, never ``DocNo``. ``DocNo`` is
MUTABLE (the vendor exposes ``NewDocNo``) — correlating on it would silently
fork a document into two the first time a customer renumbers one. ``DocNo`` is
carried for DISPLAY only.
"""
from typing import Any, Dict

from pydantic import Field

from app.schemas.base import ApiModel

# The system these records were read FROM. A second source system (a different
# ERP) would set its own value; consumers branch on this, never on the module.
SOURCE_SYSTEM = "autocount"


class CanonicalRecord(ApiModel):
    """Base for every canonical record.

    Inherits ``ApiModel`` so datetimes leave the API Z-suffixed UTC (house rule);
    every datetime held in memory is aware-UTC.
    """

    source_system: str = SOURCE_SYSTEM
    # Vendor DocKey — stable across a DocNo change (see module docstring).
    source_ref: str
    # The canonical entity key ("goods_received_note"), so a consumer can route
    # a heterogeneous batch without inspecting the payload shape.
    entity_type: str

    def identity(self) -> str:
        """Stable cross-system identity: ``autocount:goods_received_note:12345``."""
        return f"{self.source_system}:{self.entity_type}:{self.source_ref}"

    def comparable(self) -> Dict[str, Any]:
        """A JSON-safe dict for diffing before → after (AC-13-12).

        ``mode="json"`` coerces Decimal/date/datetime to primitives so a diff
        compares like with like and the result is directly storable in a JSON
        column.
        """
        return self.model_dump(mode="json")


class CanonicalLine(ApiModel):
    """Base for a nested document line. Lines are always NESTED under their
    header (AC-13-06) — never fetched or stored as free-standing records."""

    # Vendor detail key. Casing differs PER ENTITY at the source (``DtlKey`` on
    # GRN, ``Dtlkey`` on DO); that difference is resolved by mapping rows, so by
    # the time a value reaches here it has exactly one name.
    source_ref: str = Field(default="")
    # 1-based position within the document, assigned by the mapper. Used to name
    # the offending line in a per-document failure (AC-13-10).
    line_no: int = 0
