"""Core outbound-URL SSRF guard (plan sprint-4/31 S5, D-A5-11/F5).

`app/services/url_guard.py` is a verbatim extraction of the pre-existing,
already-reviewed omnichannel consumer-webhook delivery guard - this suite
pins its behaviour directly (scheme allowlist, private/loopback/link-local/
reserved/multicast/unspecified ranges given as literal/decimal/hex, DNS-
rebinding re-check, redirects-disabled policy documented at the call site).
`tests/test_omnichannel_consumer_webhooks.py::test_ssrf_guard_unit` and
`tests/test_omnichannel_api_gateway.py::test_delivery_refuses_a_target_that_
resolves_internally` cover the SAME guard through the module's delegating
wrapper and must stay green untouched (the reviewer's diff check).
"""
import pytest

from app.services.url_guard import (
    UrlGuardError,
    assert_deliverable,
    validate_public_https_url,
)


def test_scheme_allowlist_rejects_non_https():
    with pytest.raises(UrlGuardError):
        validate_public_https_url("http://example.com/hook")
    with pytest.raises(UrlGuardError):
        validate_public_https_url("ftp://example.com/hook")


def test_rejects_missing_host():
    with pytest.raises(UrlGuardError):
        validate_public_https_url("https:///no-host")


def test_rejects_localhost_names():
    for url in ("https://localhost", "https://a.localhost/x", "https://box.local/x"):
        with pytest.raises(UrlGuardError):
            validate_public_https_url(url)


def test_rejects_private_loopback_link_local_ip_literals():
    blocked = (
        "https://192.168.1.10/h",   # private
        "https://10.0.0.1",         # private
        "https://172.16.0.5",       # private
        "https://127.0.0.1/",       # loopback
        "https://169.254.169.254",  # link-local (cloud metadata)
        "https://0.0.0.0",          # unspecified
        "https://224.0.0.1",        # multicast
    )
    for url in blocked:
        with pytest.raises(UrlGuardError):
            validate_public_https_url(url)


def test_rejects_decimal_and_hex_encoded_loopback():
    # 2130706433 == 127.0.0.1 as a decimal integer; 0x7f000001 is the hex form.
    # Neither parses via `ipaddress.ip_address` directly - both fall through to
    # the resolve-then-pin path, where `socket.getaddrinfo` resolves them to
    # the literal address for HTTP purposes.
    for url in ("https://2130706433/", "https://0x7f000001/"):
        with pytest.raises(UrlGuardError):
            validate_public_https_url(url)


def test_allows_a_normal_public_https_url():
    assert (
        validate_public_https_url("https://example.com/hook")
        == "https://example.com/hook"
    )


def test_strict_dns_rejects_unresolvable_host(monkeypatch):
    import socket as socket_mod

    def _fail(host, port):
        raise socket_mod.gaierror("nope")

    monkeypatch.setattr(socket_mod, "getaddrinfo", _fail)
    with pytest.raises(UrlGuardError):
        validate_public_https_url("https://does-not-resolve.example/", strict_dns=True)


def test_non_strict_dns_allows_unresolvable_host(monkeypatch):
    import socket as socket_mod

    def _fail(host, port):
        raise socket_mod.gaierror("nope")

    monkeypatch.setattr(socket_mod, "getaddrinfo", _fail)
    # Registration-time (non-strict) must not depend on live DNS.
    assert validate_public_https_url("https://does-not-resolve.example/") == (
        "https://does-not-resolve.example/"
    )


def test_dns_rebinding_guard_blocks_a_host_that_now_resolves_internally(monkeypatch):
    """The re-check that actually closes the pivot: a URL that looked public at
    registration can be re-pointed by DNS afterwards - `assert_deliverable` (run
    immediately before every delivery/request) must refuse it."""
    import socket as socket_mod

    monkeypatch.setattr(
        socket_mod,
        "getaddrinfo",
        lambda host, port: [(None, None, None, "", ("169.254.169.254", 0))],
    )
    with pytest.raises(UrlGuardError):
        assert_deliverable("https://rebound.example.com/hook")

    monkeypatch.setattr(
        socket_mod,
        "getaddrinfo",
        lambda host, port: [(None, None, None, "", ("93.184.216.34", 0))],
    )
    assert_deliverable("https://ok.example.com/hook")  # public -> allowed
