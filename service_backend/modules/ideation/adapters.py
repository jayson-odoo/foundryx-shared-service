"""Adapter-kind registry (AC-A-07) — code-side, metadata-only.

Mirrors the product-kind (``app/catalog/kinds.py``) / status-entity registry
pattern: an adapter ``kind`` is a validated label, never a behavior branch. A
software Product's ``ProductAdapter`` rows carry a ``kind`` validated here.

Phase A wires ONLY ``embed_connection`` (the embed-exchange binding — the other
end of the product-domain link, AC-A-09/A-39). ``github`` / ``agent_runner`` /
``deploy`` are **registered-but-dormant** (Phase C build/deploy plane): the kinds
are known and validate, but nothing acts on them yet.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class AdapterKind:
    key: str            # stored on ProductAdapter.kind (immutable contract)
    label: str          # display
    wired: bool         # True = Phase-A active; False = registered-but-dormant
    sort: int = 100


_REGISTRY: dict[str, AdapterKind] = {}


def register_adapter_kind(kind: AdapterKind) -> None:
    """Idempotent — last registration for a key wins (boot re-runs are safe)."""
    _REGISTRY[kind.key] = kind


def _ensure_registered() -> None:
    if _REGISTRY:
        return
    register_adapter_kind(AdapterKind("embed_connection", "Embed Connection", True, 1))
    register_adapter_kind(AdapterKind("github", "GitHub", False, 2))
    register_adapter_kind(AdapterKind("agent_runner", "Agent Runner", False, 3))
    register_adapter_kind(AdapterKind("deploy", "Deploy", False, 4))


def registered_adapter_kinds() -> list[AdapterKind]:
    _ensure_registered()
    return sorted(_REGISTRY.values(), key=lambda k: (k.sort, k.label))


def active_adapter_kind(key: str) -> AdapterKind:
    """The registered kind for ``key`` (raises KeyError if unknown)."""
    _ensure_registered()
    return _REGISTRY[key]


def is_valid_adapter_kind(key: str) -> bool:
    _ensure_registered()
    return key in _REGISTRY
