"""Canonical shapes — the FoundryX-neutral middle of the two-hop translation
(plan §8, D7).

**Canonical is DERIVED from the consumer's proven shapes, not designed fresh.**
Designing a "product-neutral" abstraction from a sample size of one produces
something that fits nobody, so these fields mirror the consumer's existing
document models (and `SCM_Module_Build_Plan.md`, which already specifies
``source_system`` / ``source_ref``).

Hard rule for this package: **no vendor concept leaks in.** ``"T"``/``"F"``,
``GRDTL``, ``DtlKey`` vs ``Dtlkey``, three date formats, 8-dp numeric strings —
all of that is absorbed by hop 1 (``mapping.py``) and must never appear here. If
a canonical field name reads like AutoCount jargon, it is in the wrong layer.
"""
from .base import CanonicalRecord, SOURCE_SYSTEM
from .grn import ENTITY_GOODS_RECEIVED_NOTE, CanonicalGrn, CanonicalGrnLine

__all__ = [
    "SOURCE_SYSTEM",
    "CanonicalRecord",
    "CanonicalGrn",
    "CanonicalGrnLine",
    "ENTITY_GOODS_RECEIVED_NOTE",
]
