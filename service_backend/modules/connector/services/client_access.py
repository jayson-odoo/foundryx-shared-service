"""Source-IP allow-list for the Claude-facing endpoints (CONNECTOR_ALLOWED_CLIENT_CIDRS).

Unset/blank = off. Any invalid entry = fail closed (nobody allowed). The caller
passes the resolved client IP (the throttle's resolver, so X-Forwarded-For is
honoured only behind a trusted proxy).
"""
from __future__ import annotations

import ipaddress
from typing import Optional

from .. import registry


def client_allowed(ip: str, raw_cidrs: Optional[str] = None) -> bool:
    raw = registry.allowed_client_cidrs() if raw_cidrs is None else raw_cidrs.strip() or None
    if raw is None:
        return True
    try:
        networks = [ipaddress.ip_network(p.strip(), strict=False) for p in raw.split(",") if p.strip()]
        if not networks:
            return False
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in networks if net.version == addr.version)
