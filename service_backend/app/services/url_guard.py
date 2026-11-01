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
import typing
from urllib.parse import urlparse

import anyio
import httpcore
import httpx


class UrlGuardError(Exception):
    """A URL failed the outbound SSRF guard (non-https, private/loopback/
    link-local/reserved/multicast/unspecified target, or unresolvable under
    ``strict_dns=True``)."""


class UnparseableUrlError(UrlGuardError):
    """The URL text cannot be parsed at all (as opposed to being refused)."""


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
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme
        host = parsed.hostname
        if scheme == "https" and host:
            httpx.URL(url)
    except (ValueError, httpx.InvalidURL):
        raise UnparseableUrlError(f"{subject} is not a valid URL.") from None
    if scheme != "https":
        raise UrlGuardError(f"{subject} must use https://.")
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


# ── Connect-time check ───────────────────────────────────────────────────────
# The pre-flight above answers early with the caller's own refusal text. The
# transports below make the connection itself the authority: the host is
# resolved once, every returned address is checked, and the TCP connection is
# opened to one of those checked addresses. TLS and the Host header keep using
# the name from the URL (httpcore starts TLS with the origin host).

# Delay before the next address is tried while an earlier attempt is pending.
_CONNECT_ATTEMPT_DELAY = 0.25

HostExemption = typing.Optional[typing.Callable[[str], bool]]


def _literal_ip(host: str) -> "typing.Optional[ipaddress._BaseAddress]":
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _checked_addresses(host: str, infos: typing.Iterable[tuple], subject: str) -> typing.List[str]:
    """Addresses from a resolver answer, in order and de-duplicated. Raises
    ``UrlGuardError`` when ANY of them is blocked (same rule as
    ``validate_public_https_url``)."""
    addresses: typing.List[str] = []
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            raise UrlGuardError(f"{subject} resolves to a private or reserved IP.")
        if addr not in addresses:
            addresses.append(addr)
    if not addresses:
        raise httpcore.ConnectError(f"No usable address for {host}")
    return addresses


def _literal_addresses(host: str, ip: "ipaddress._BaseAddress", subject: str) -> typing.List[str]:
    if _is_blocked_ip(ip):
        raise UrlGuardError(f"{subject} cannot target a private or reserved IP.")
    return [host]


class _GuardedSyncBackend(httpcore.SyncBackend):
    def __init__(self, subject: str, exempt_host: HostExemption) -> None:
        super().__init__()
        self._subject = subject
        self._exempt_host = exempt_host

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if self._exempt_host is not None and self._exempt_host(host):
            return super().connect_tcp(host, port, timeout, local_address, socket_options)
        literal = _literal_ip(host)
        if literal is not None:
            addresses = _literal_addresses(host, literal, self._subject)
        else:
            try:
                infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            except TimeoutError as exc:
                raise httpcore.ConnectTimeout(str(exc)) from exc
            except (OSError, UnicodeError) as exc:
                raise httpcore.ConnectError(str(exc)) from exc
            addresses = _checked_addresses(host, infos, self._subject)
        last: typing.Optional[Exception] = None
        for address in addresses:
            try:
                return super().connect_tcp(address, port, timeout, local_address, socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last = exc
        assert last is not None
        raise last


class _GuardedAsyncBackend(httpcore.AnyIOBackend):
    def __init__(self, subject: str, exempt_host: HostExemption) -> None:
        super().__init__()
        self._subject = subject
        self._exempt_host = exempt_host

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if self._exempt_host is not None and self._exempt_host(host):
            return await super().connect_tcp(host, port, timeout, local_address, socket_options)
        try:
            # One budget covers resolving and connecting.
            with anyio.fail_after(timeout):
                literal = _literal_ip(host)
                if literal is not None:
                    addresses = _literal_addresses(host, literal, self._subject)
                else:
                    try:
                        infos = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
                    except (OSError, UnicodeError) as exc:
                        raise httpcore.ConnectError(str(exc)) from exc
                    addresses = _checked_addresses(host, infos, self._subject)
                return await self._connect_any(addresses, port, timeout, local_address, socket_options)
        except TimeoutError as exc:
            raise httpcore.ConnectTimeout(str(exc)) from exc

    async def _connect_any(self, addresses, port, timeout, local_address, socket_options):
        """Start an attempt per checked address (the next one at once when the
        previous failed, otherwise after a short delay); the first connection
        wins and the rest are cancelled."""
        connect_one = super().connect_tcp
        winner: typing.List[typing.Any] = []
        errors: typing.List[Exception] = []

        async def attempt(address: str, done: anyio.Event) -> None:
            try:
                stream = await connect_one(address, port, timeout, local_address, socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                errors.append(exc)
                return
            finally:
                done.set()
            if winner:
                await stream.aclose()
                return
            winner.append(stream)
            group.cancel_scope.cancel()

        async with anyio.create_task_group() as group:
            for address in addresses:
                done = anyio.Event()
                group.start_soon(attempt, address, done)
                with anyio.move_on_after(_CONNECT_ATTEMPT_DELAY):
                    await done.wait()
        if winner:
            return winner[0]
        raise errors[-1]


def _default_limits() -> httpx.Limits:
    return httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=5.0)


class GuardedTransport(httpx.HTTPTransport):
    """``httpx.HTTPTransport`` whose TCP connections go only to an address that
    passed the block rule at connect time. ``exempt_host`` lets a caller leave
    a host out of the check (it is called with the origin host)."""

    def __init__(
        self,
        subject: str = "URL",
        *,
        exempt_host: HostExemption = None,
        verify: typing.Union[bool, str] = True,
        trust_env: bool = True,
        limits: typing.Optional[httpx.Limits] = None,
    ) -> None:
        limits = limits or _default_limits()
        ctx = httpx.create_ssl_context(verify=verify, trust_env=trust_env)
        super().__init__(verify=ctx, trust_env=trust_env, limits=limits)
        self._pool.close()
        self._pool = httpcore.ConnectionPool(
            ssl_context=ctx,
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
            http1=True,
            http2=False,
            retries=0,
            network_backend=_GuardedSyncBackend(subject, exempt_host),
        )


class GuardedAsyncTransport(httpx.AsyncHTTPTransport):
    """Async twin of ``GuardedTransport``."""

    def __init__(
        self,
        subject: str = "URL",
        *,
        exempt_host: HostExemption = None,
        verify: typing.Union[bool, str] = True,
        trust_env: bool = True,
        limits: typing.Optional[httpx.Limits] = None,
    ) -> None:
        limits = limits or _default_limits()
        ctx = httpx.create_ssl_context(verify=verify, trust_env=trust_env)
        super().__init__(verify=ctx, trust_env=trust_env, limits=limits)
        if not hasattr(self, "_pool"):  # the pool is replaced below: fail loudly if httpx renames it
            raise AttributeError("httpx transport has no _pool to replace")
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ctx,
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
            http1=True,
            http2=False,
            retries=0,
            network_backend=_GuardedAsyncBackend(subject, exempt_host),
        )
