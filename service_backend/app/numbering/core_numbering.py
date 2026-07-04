"""Core numbered document types (sprint-4/07 seed).

The numbering registry is CORE; the concrete finance/crm doc types register from
their own module bootstraps (``module="finance"`` / ``module="crm"``) so the
``active_modules`` filter (AC-07-03) is actually exercised. Core itself seeds a
single generic example so the catalog is non-empty on a bare install (no modules
yet) and the engine is demoable day one.
"""
from app.numbering.registry import (
    RESET_YEARLY,
    NumberSequenceDef,
    register_number_sequence,
)

CORE_SEQUENCES = [
    NumberSequenceDef(
        key="document_no",
        label="Document number",
        module="core",
        default_prefix="DOC-",
        default_format="{prefix}{YYYY}-{NNNN}",
        default_reset=RESET_YEARLY,
    ),
]


def register_core_numbering() -> None:
    for seq in CORE_SEQUENCES:
        register_number_sequence(seq)
