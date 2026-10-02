"""Shared outbound-URL SSRF guard (plan sprint-4/31 S5, D-A5-11/F5).

Extracted VERBATIM from ``modules/omnichannel/services/webhook_service.py``
(the already-reviewed consumer-webhook delivery guard) so a CORE
``http.request`` workflow action can share it without core importing a
module. Behaviour is byte-identical to the original - the module now
delegates to ``assert_deliverable``/``validate_public_https_url`` below
instead of keeping its own copy (a second copy would drift, the exact
failure mode this extraction exists to prevent).

Security invariants (unchanged from the original):
- https-only.
- Rejects private/loopback/link-local/reserved/multicast/unspecified targets
  given as an IP literal (dotted, decimal, or hex), OR a hostname that
  RESOLVES to one (DNS-rebinding guard).
- ``assert_deliverable`` re-runs the check immediately before EVERY delivery
  attempt - not only at registration/save time - because DNS can be
  re-pointed after a URL is accepted.
"""
import ipaddress
import socket
from urllib.parse import urlparse


class UrlGuardError(Exception):
    """A URL failed the outbound SSRF guard (non-https, private/loopback/
    link-local/reserved/multicast/unspecified target, or unresolvable under
    ``strict_dns=True``)."""


def _is_blocked_ip(ip: "ipaddress._BaseAddress") -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_public_https_url(
    url: str, *, strict_dns: bool = False, subject: str = "URL"
) -> str:
    """HTTPS-only + block SSRF targets. Rejects private/loopback/link-local/
    reserved IPs whether given as a literal, a numeric/hex-encoded IP, OR a
    hostname that RESOLVES to one (e.g. an A record pointing at
    169.254.169.254). ``strict_dns`` also rejects a host we cannot resolve.

    ``subject`` names the thing being validated in every raised message
    (plan sprint-4/31 S5 review) - the pre-extraction consumer-webhook guard
    said "Callback URL ..."; a caller with its own noun (the module's
    ``validate_callback_url`` passes ``subject="Callback URL"``) keeps its
    existing, already-documented 422 copy byte-identical after this
    extraction. Defaults to the generic "URL" for callers with no better noun
    (e.g. the core ``http.request`` action).

    Callers that only VALIDATE (registration/save) should keep
    ``strict_dns=False`` - a transient DNS failure must not reject a
    legitimate URL, and making registration depend on live resolution breaks
    offline CI. The authoritative guard is ``assert_deliverable``, which runs
    before EVERY delivery/request attempt."""
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise UrlGuardError(f"{subject} must use https://.")
    host = parsed.hostname
    if not host:
        raise UrlGuardError(f"{subject} is missing a host.")
    lowered = host.lower()
    if lowered == "localhost" or lowered.endswith(".localhost") or lowered.endswith(".local"):
        raise UrlGuardError(f"{subject} cannot target localhost.")

    # IP literal (dotted, numeric like 2130706433, or hex like 0x7f000001 - the
    # latter two fail ip_address, so resolve them below).
    try:
        ip = ipaddress.ip_address(host)
        if _is_blocked_ip(ip):
            raise UrlGuardError(f"{subject} cannot target a private or reserved IP.")
        return url
    except ValueError:
        pass

    # Hostname (incl. numeric/hex forms): resolve + block if ANY address is
    # internal.
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        if strict_dns:
            raise UrlGuardError("Could not resolve the host.")
        return url
    for info in infos:
        addr = info[4][0]
        try:
            if _is_blocked_ip(ipaddress.ip_address(addr)):
                raise UrlGuardError(f"{subject} resolves to a private or reserved IP.")
        except ValueError:
            continue
    return url


def assert_deliverable(url: str, *, subject: str = "URL") -> None:
    """Re-check the target IMMEDIATELY before making the request.

    Registration/save-time validation is not sufficient alone: DNS can be
    re-pointed afterwards (rebinding), and the URL is often settable by a
    tenant/API-key holder - so a fail-open registration would otherwise let a
    caller aim the outbound request at a link-local or RFC1918 address (a
    blind SSRF pivot into the deployment's network). Raises ``UrlGuardError``;
    the caller records a failed attempt and never sends.

    NOT strict on resolution failure. Blocking an UNRESOLVABLE host buys no
    security - there is nothing to connect to, the HTTP client fails on its
    own - but it does turn every transient DNS blip into a refused delivery.
    What matters is that a host resolving to an internal address is never
    connected to."""
    validate_public_https_url(url, strict_dns=False, subject=subject)
