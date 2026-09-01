"""NumberSequenceDef registry (sprint-4/07, Cluster F) - code-side, mirrors the
terminology / rule / status engines.

``register_number_sequence(NumberSequenceDef)`` declares a numbered document
type's DEFAULTS (prefix / format pattern / per-period reset). Core registers
its example types at ``lazy_once`` (``core_numbering.py``); a module registers
its own at install - same contract as ``register_term``.

A tenant's ``number_formats`` override row supersedes these defaults (the
terminology_overrides pattern); absence = use the registered default.

The ``module`` tag (F9 plan-10) filters the catalog by ``active_modules`` at
consumption - ``'core'`` is always visible, a module's types only while ACTIVE.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.lazy_registry import lazy_once

# Reset cadence - keyed by a period bucket so the running counter restarts per
# period without losing history. ``never`` keeps one bucket forever.
RESET_NEVER = "never"
RESET_YEARLY = "yearly"
RESET_MONTHLY = "monthly"
RESET_PERIODS = (RESET_NEVER, RESET_YEARLY, RESET_MONTHLY)


@dataclass(frozen=True)
class NumberSequenceDef:
    """One numbered document type. ``key`` is the stable doc_type (e.g.
    ``invoice``); ``default_format`` is the token pattern (see ``format_number``)."""

    key: str
    label: str
    module: str = "core"
    default_prefix: str = ""
    default_format: str = "{prefix}{YYYY}-{NNNN}"
    default_reset: str = RESET_YEARLY


_REGISTRY: Dict[str, NumberSequenceDef] = {}


def register_number_sequence(seq: NumberSequenceDef) -> None:
    """Idempotent - re-registration on every bootstrap simply overwrites."""
    if seq.default_reset not in RESET_PERIODS:
        raise ValueError(f"Invalid reset period for {seq.key}: {seq.default_reset}")
    _REGISTRY[seq.key] = seq


def get_sequence(key: str) -> Optional[NumberSequenceDef]:
    ensure_core()
    return _REGISTRY.get(key)


def list_sequences() -> List[NumberSequenceDef]:
    """All registered defs, module then key ordered (drives the catalog)."""
    ensure_core()
    return sorted(_REGISTRY.values(), key=lambda s: (s.module, s.key))


def is_registered(key: str) -> bool:
    ensure_core()
    return key in _REGISTRY


def _register_core() -> None:
    from app.numbering.core_numbering import register_core_numbering

    register_core_numbering()


# Call before any registry read - core registers exactly once.
ensure_core = lazy_once(_register_core)
