"""Module-owned public CORS prefixes (plan sprint-4/34 review round 1, S9).

A module may mount a router `"public": true` on a prefix whose CORS answer
core CANNOT compute: the allowed origins are TENANT data (a channel's own
allowlist), not this service's `CORS_ORIGINS` env, so the stock
`CORSMiddleware` answers the browser's preflight `400 Disallowed CORS origin`
and the real request never leaves the page.

Rather than teaching core a module's path (which is what the first cut of this
did - a hardcoded `/public/omnichannel/webchat/` constant in `app/main.py`),
the MODULE registers its prefix plus a resolver at boot, exactly like
`register_capability`. Core keeps zero knowledge of any module's routes; the
generic `PublicCorsMiddleware` (`app/module_platform/public_cors_middleware.py`)
walks this registry.

Contract for a provider:

    register_public_cors_prefix(
        "/public/<module>/<thing>/",
        provider_module="<module>",
        resolver=lambda path, origin: <bool>,
    )

`resolver` answers ONE question - "may this exact origin be echoed back for a
request on this exact path?" - and must be cheap (it runs on a preflight, which
browsers repeat per unique path/method/header set once the `Max-Age` lapses)
and total (never raises; a failure is `False`). A preflight carries no body and
no credentials, so the echo discloses nothing beyond "this origin may talk to
this path", which the real response would say anyway.
"""
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

# (path, origin) -> may this origin be echoed
OriginResolver = Callable[[str, str], bool]


class DuplicatePublicCorsPrefix(Exception):
    """Two modules claimed the same public prefix at boot - fatal, same rule
    as `DuplicateCapability` (one owner per seam, decided at boot not at
    request time)."""


@dataclass(frozen=True)
class PublicCorsPrefix:
    prefix: str
    provider_module: str
    resolver: OriginResolver


_PREFIXES: Dict[str, PublicCorsPrefix] = {}


def register_public_cors_prefix(
    prefix: str, *, provider_module: str, resolver: OriginResolver
) -> None:
    """Boot-time registration; idempotent per (prefix, module)."""
    existing = _PREFIXES.get(prefix)
    if existing is not None and existing.provider_module != provider_module:
        raise DuplicatePublicCorsPrefix(
            f"Public CORS prefix {prefix!r} already owned by "
            f"'{existing.provider_module}'; '{provider_module}' conflicts."
        )
    _PREFIXES[prefix] = PublicCorsPrefix(prefix, provider_module, resolver)


def reset_public_cors_prefixes() -> None:
    """Test hook - clear the registry between boot simulations."""
    _PREFIXES.clear()


def public_cors_prefixes() -> List[PublicCorsPrefix]:
    return list(_PREFIXES.values())


def match_public_cors_prefix(path: str) -> Optional[PublicCorsPrefix]:
    """The registered prefix this path sits under, or `None`. `None` is the
    hot path (every request in the app that is not one of these), so this
    stays a plain prefix scan over a registry with a handful of entries."""
    for entry in _PREFIXES.values():
        if path.startswith(entry.prefix):
            return entry
    return None
