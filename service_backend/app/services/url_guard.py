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
import threading
import time
import typing
import weakref
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


# RFC 6598 shared address space: not covered by `is_private` on every Python
# version, and reachable on carrier-grade NAT networks.
_SHARED_ADDRESS_SPACE = ipaddress.ip_network("100.64.0.0/10")
# Deprecated 6to4 relay anycast block (RFC 7526): not covered by the stdlib flags.
_SIX_TO_FOUR_RELAY = ipaddress.ip_network("192.88.99.0/24")


def _is_blocked_ip(ip: "ipaddress._BaseAddress") -> bool:
    # One rule for the IPv4 form and its IPv4-mapped IPv6 spelling, whatever the
    # Python version does with the mapped form.
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        return _is_blocked_ip(mapped)
    if isinstance(ip, ipaddress.IPv4Address) and (
        ip in _SHARED_ADDRESS_SPACE or ip in _SIX_TO_FOUR_RELAY
    ):
        return True
    return (
        getattr(ip, "is_site_local", False)  # IPv6 fec0::/10, deprecated but routable
        or ip.is_private
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

# With an overall deadline, at most this many distinct resolved addresses are
# tried (a caller without a deadline keeps trying all of them).
_MAX_CONNECT_ADDRESSES = 4


def call_within(seconds: float, fn: typing.Callable[..., typing.Any], *args: typing.Any, **kwargs: typing.Any):
    """Run ``fn`` on a helper thread and stop waiting after ``seconds``: raises
    ``TimeoutError`` (the helper is left to finish on its own, its result
    dropped). For blocking calls that take no timeout, such as name resolution."""
    box: typing.Dict[str, typing.Any] = {}

    def work() -> None:
        try:
            box["value"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - handed to the waiting caller
            box["error"] = exc

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(max(seconds, 0.0))
    if worker.is_alive():
        raise TimeoutError("timed out")
    if "error" in box:
        raise box["error"]
    return box.get("value")


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
    def __init__(self, subject: str, exempt_host: HostExemption, budget: typing.Optional[float] = None) -> None:
        super().__init__()
        self._subject = subject
        self._exempt_host = exempt_host
        # Overall budget for resolving and connecting, counted from now.
        self._deadline = None if budget is None else time.monotonic() + budget
        # Sockets opened through this backend, so a caller's overall deadline can
        # cut a blocked exchange short (see ``GuardedTransport.abort_connections``).
        self._sockets: "weakref.WeakSet[socket.socket]" = weakref.WeakSet()
        self._aborted = False

    def abort_connections(self) -> None:
        # From now on any socket this backend opens is shut as soon as it
        # exists, so an address tried after the deadline cannot outlive it.
        self._aborted = True
        for sock in list(self._sockets):
            self._shut(sock)

    @staticmethod
    def _shut(sock) -> None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        return self._track(self._connect_tcp(host, port, timeout, local_address, socket_options))

    def _track(self, stream):
        sock = stream.get_extra_info("socket")
        if sock is not None:
            self._sockets.add(sock)
            if self._aborted:
                self._shut(sock)
        start_tls = stream.start_tls

        def tracked_start_tls(*args, **kwargs):
            # TLS wraps the socket in a new object: track that one too.
            return self._track(start_tls(*args, **kwargs))

        stream.start_tls = tracked_start_tls
        return stream

    def _connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if self._exempt_host is not None and self._exempt_host(host):
            return super().connect_tcp(host, port, timeout, local_address, socket_options)
        literal = _literal_ip(host)
        if literal is not None:
            addresses = _literal_addresses(host, literal, self._subject)
        else:
            try:
                if self._deadline is None:
                    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
                else:
                    infos = call_within(
                        self._remaining(), socket.getaddrinfo, host, port, type=socket.SOCK_STREAM
                    )
            except TimeoutError as exc:
                raise httpcore.ConnectTimeout(str(exc)) from exc
            except (OSError, UnicodeError) as exc:
                raise httpcore.ConnectError(str(exc)) from exc
            addresses = _checked_addresses(host, infos, self._subject)
        if self._deadline is not None:
            addresses = addresses[:_MAX_CONNECT_ADDRESSES]
        last: typing.Optional[Exception] = None
        for address in addresses:
            step = timeout
            if self._deadline is not None:
                remaining = self._remaining()
                if remaining <= 0:
                    break
                step = remaining if timeout is None else min(timeout, remaining)
            try:
                return super().connect_tcp(address, port, step, local_address, socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last = exc
        if last is None:
            raise httpcore.ConnectTimeout("The overall time limit ran out while connecting.")
        raise last

    def _remaining(self) -> float:
        assert self._deadline is not None
        return self._deadline - time.monotonic()


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
        budget: typing.Optional[float] = None,
    ) -> None:
        """``budget`` (seconds, optional) bounds resolving plus connecting as a
        whole; without it each step keeps only its own timeout."""
        limits = limits or _default_limits()
        ctx = httpx.create_ssl_context(verify=verify, trust_env=trust_env)
        super().__init__(verify=ctx, trust_env=trust_env, limits=limits)
        self._pool.close()
        self._backend = _GuardedSyncBackend(subject, exempt_host, budget)
        self._pool = httpcore.ConnectionPool(
            ssl_context=ctx,
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
            http1=True,
            http2=False,
            retries=0,
            network_backend=self._backend,
        )

    def abort_connections(self) -> None:
        """Shut down every socket this transport opened. A blocked read in
        another thread then fails at once (used for an overall deadline)."""
        self._backend.abort_connections()


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
