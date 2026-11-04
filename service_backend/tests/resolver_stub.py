"""Resolver stub that answers only the hosts a test names.

``socket`` is one global module, so patching ``socket.getaddrinfo`` covers every
caller (the URL guard included). A mapped host answers its address; ``localhost``
(the realtime Redis client) goes to the real resolver; any other name raises
``UnexpectedLookup`` and is recorded, so a lookup the test never meant to make is
visible instead of silently resolving to a public address.
"""
import socket
from typing import Dict, List


class UnexpectedLookup(AssertionError):
    """A name the test did not list was resolved."""


def stub_resolver(monkeypatch, hosts: Dict[str, str]) -> List[str]:
    """Patch ``socket.getaddrinfo``; returns the list of unexpected lookups
    (assert it is empty at the end of the test)."""
    real = socket.getaddrinfo
    unexpected: List[str] = []

    def resolve(host, port=None, *args, **kwargs):
        if host in hosts:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (hosts[host], port or 0))]
        if host == "localhost":
            return real(host, port, *args, **kwargs)
        unexpected.append(str(host))
        raise UnexpectedLookup(f"unexpected DNS lookup for {host!r}")

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    return unexpected
