"""Capability registry (sprint-3/10 D5) - the sanctioned cross-module call seam.

A provider module BOOT-registers ``CapabilityDef{key, version, provider_module,
handler}`` (e.g. omnichannel ``messaging.send@1``). A consumer resolves at
runtime via ``resolve_capability(db, tenant_id, key, version)`` → the handler
IFF the provider module is ACTIVE for that tenant AND the major version matches,
else ``None`` (the self-disable signal - NEVER raises for "absent"). The handler
``(db, tenant_id, payload) -> result`` tenant-scopes INTERNALLY (isolation is
never relaxed - the critical house invariant).

Versioning = integer major, exact-major match (breaking = new major; a provider
may keep old majors registered). Unique ``(key, version)`` → one provider; a
duplicate at boot is a LOUD error. A module never imports another's internals,
so a 3rd party can ship an alternative provider transparently.
"""
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

from sqlalchemy.orm import Session


class DuplicateCapability(Exception):
    """Two providers registered the same (key, version) at boot - fatal."""


@dataclass(frozen=True)
class CapabilityDef:
    key: str
    version: int
    provider_module: str
    handler: Callable  # (db, tenant_id, payload) -> result


_CAPS: Dict[Tuple[str, int], CapabilityDef] = {}


def register_capability(cap: CapabilityDef) -> None:
    """Boot-time registration. A duplicate (key, version) is a loud error
    (per-tenant multi-provider selection = backlog)."""
    existing = _CAPS.get((cap.key, cap.version))
    if existing is not None and existing.provider_module != cap.provider_module:
        raise DuplicateCapability(
            f"Capability {cap.key}@{cap.version} already provided by "
            f"'{existing.provider_module}'; '{cap.provider_module}' conflicts."
        )
    _CAPS[(cap.key, cap.version)] = cap


def reset_capabilities() -> None:
    """Test hook - clear the registry between boot simulations."""
    _CAPS.clear()


def resolve_capability(
    db: Session, tenant_id: str, key: str, version: int
) -> Optional[Callable]:
    """Return the handler iff the provider module is ACTIVE for this tenant and
    the major version matches exactly; else ``None`` (self-disable signal -
    never raises for absence). Works cross-process (web + Celery both boot the
    registry; resolution takes a live ``db``)."""
    cap = _CAPS.get((key, version))
    if cap is None:
        return None
    from app.module_platform.active import active_modules

    if cap.provider_module not in active_modules(db, tenant_id):
        return None
    return cap.handler


def has_capability(key: str, version: int) -> bool:
    """Boot-time presence check (ignores tenant activation)."""
    return (key, version) in _CAPS


def list_capabilities() -> list:
    return list(_CAPS.values())
