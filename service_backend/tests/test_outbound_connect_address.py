"""Outbound requests only ever connect to an address the guard allows.

Every guarded outbound path is driven through its real entry point against
REAL loopback TCP listeners (127.0.0.1 and ::1 on the same port). Nothing about
the transport is faked: the only scripted pieces are the DNS answers
(``socket.getaddrinfo``, which the sync stack AND the async stack both reach)
and the address predicate (``url_guard._is_blocked_ip``), because both listener
addresses are really loopback and the real predicate would block both.

Convention: 127.0.0.1 is "allowed", ::1 is "blocked". A connection that is
accepted on the "blocked" listener is a connection that reached an address the
guard treats as blocked.

Rules pinned for every path:
- whatever the resolver answers on any call, no TCP connection reaches a blocked address
- a resolver failure is not a refusal
- a name with no answer at all fails through the path's normal connection handling
- a name or literal blocked on the first check is refused with today's message
- the name stays the name (Host header, TLS server name)
- redirects are not followed automatically; manual redirect loops apply the rule per hop
- the development carve-out for local hosts in the AutoCount client keeps working
"""
from __future__ import annotations

import datetime as _dt
import ipaddress
import os
import socket
import ssl
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from app.services import url_guard

ALLOWED_ADDR = "127.0.0.1"
BLOCKED_ADDR = "::1"
# A Meta CDN suffix so the one path with a host allowlist can be driven with the
# same name as the others. It is only ever resolved by the scripted resolver.
NAME = "asset.edge-test.fbcdn.net"
HOP_NAME = "hop.edge-test.fbcdn.net"
WAIT_SECONDS = 30.0

SEQ_ALLOWED_THEN_BLOCKED = ["allowed", "blocked"]
SEQ_ALLOWED_ALLOWED_BLOCKED = ["allowed", "allowed", "blocked"]
SEQ_FAILURE_THEN_BLOCKED = ["fail", "blocked"]
SEQ_FAILURE_THEN_ALLOWED = ["fail", "allowed"]
SEQ_BLOCKED = ["blocked"]
SEQ_FAILURE = ["fail"]
SEQ_ALLOWED = ["allowed"]


# ── TLS material (only used by the tests that need a server that answers) ─────
@pytest.fixture(scope="session")
def tls_material(tmp_path_factory):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = _dt.datetime.now(_dt.timezone.utc)

    def _name(cn):
        return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(_name("test-ca"))
        .issuer_name(_name("test-ca"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(days=1))
        .not_valid_after(now + _dt.timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=True, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    leaf_cert = (
        x509.CertificateBuilder()
        .subject_name(_name(NAME))
        .issuer_name(ca_cert.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(days=1))
        .not_valid_after(now + _dt.timedelta(days=2))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(NAME), x509.DNSName(HOP_NAME)]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    folder = tmp_path_factory.mktemp("outbound-tls")
    ca_path = folder / "ca.pem"
    cert_path = folder / "leaf.pem"
    key_path = folder / "leaf.key"
    ca_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(leaf_cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return SimpleNamespace(ca=str(ca_path), cert=str(cert_path), key=str(key_path))


# ── The rig: listeners, scripted resolver, spies ──────────────────────────────
class Rig:
    def __init__(self, tls_material, monkeypatch):
        self._tls = tls_material
        self._monkeypatch = monkeypatch
        self.stop = threading.Event()
        self.cond = threading.Condition()
        self.accepted = {ALLOWED_ADDR: [], BLOCKED_ADDR: []}
        self.sentinels = set()
        self.requests = []  # (address, Host header) seen by the TLS responder
        self.tls_hostnames = []  # server_hostname values reaching a client TLS start
        self.scripts = {}
        self.calls = {}
        self.mode = "close"  # close | ok | redirect
        self.redirect_to = ""
        self.threads = []
        self._socks = []
        self.port = self._bind_both()
        self._server_ctx = None
        self._install_patches()
        for addr, sock in zip((ALLOWED_ADDR, BLOCKED_ADDR), self._socks):
            thread = threading.Thread(target=self._accept_loop, args=(sock, addr), daemon=True)
            thread.start()
            self.threads.append(thread)

    # sockets
    def _bind_both(self):
        last = None
        for _ in range(50):
            s4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            try:
                s4.bind((ALLOWED_ADDR, 0))
                port = s4.getsockname()[1]
                s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                s6.bind((BLOCKED_ADDR, port))
            except OSError as exc:
                s4.close()
                s6.close()
                last = exc
                if exc.errno in (49, 99, 97, 47):  # address not available / family unsupported
                    break
                continue
            s4.listen(16)
            s6.listen(16)
            self._socks = [s4, s6]
            return port
        pytest.fail(f"cannot bind {ALLOWED_ADDR} and {BLOCKED_ADDR} on one port: {last!r}", pytrace=False)

    def _accept_loop(self, sock, addr):
        sock.settimeout(0.2)
        while not self.stop.is_set():
            try:
                conn, peer = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self.cond:
                self.accepted[addr].append(peer[1])
                self.cond.notify_all()
            handler = threading.Thread(target=self._handle, args=(conn, addr), daemon=True)
            handler.start()

    def _handle(self, conn, addr):
        try:
            if self.mode == "close":
                return
            conn.settimeout(10)
            if self._server_ctx is None:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ctx.load_cert_chain(self._tls.cert, self._tls.key)
                self._server_ctx = ctx
            tls = self._server_ctx.wrap_socket(conn, server_side=True)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = tls.recv(65536)
                if not chunk:
                    return
                data += chunk
            host = ""
            for line in data.split(b"\r\n")[1:]:
                if line.lower().startswith(b"host:"):
                    host = line.split(b":", 1)[1].strip().decode("latin-1")
            self.requests.append((addr, host))
            if self.mode == "redirect":
                reply = (
                    "HTTP/1.1 302 Found\r\nLocation: %s\r\nContent-Length: 0\r\n"
                    "Connection: close\r\n\r\n" % self.redirect_to
                )
            else:
                reply = (
                    "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n"
                    "Connection: close\r\n\r\nok"
                )
            tls.sendall(reply.encode("latin-1"))
            tls.close()
        except (OSError, ssl.SSLError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    # patches
    def _install_patches(self):
        mp = self._monkeypatch
        real_getaddrinfo = socket.getaddrinfo
        rig = self

        def scripted_getaddrinfo(host, port, *args, **kwargs):
            key = host.decode() if isinstance(host, bytes) else host
            script = rig.scripts.get(key)
            if script is None:
                return real_getaddrinfo(host, port, *args, **kwargs)
            with rig.cond:
                n = rig.calls.get(key, 0)
                rig.calls[key] = n + 1
            step = script[min(n, len(script) - 1)]
            if step == "oserror":
                raise OSError("scripted: resolver input/output error")
            if step == "fail":
                raise socket.gaierror(socket.EAI_NONAME, "scripted: no answer")
            try:
                number = int(port) if port not in (None, "") else 0
            except (TypeError, ValueError):
                number = 0
            if step in ("mixed_allowed_first", "mixed_blocked_first", "two_loopback"):
                pair = (ALLOWED_ADDR, BLOCKED_ADDR)
                if step == "mixed_blocked_first":
                    pair = (BLOCKED_ADDR, ALLOWED_ADDR)
                return [
                    (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (a, number, 0, 0))
                    if ":" in a
                    else (socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, number))
                    for a in pair
                ]
            addr = ALLOWED_ADDR if step == "allowed" else BLOCKED_ADDR
            if ":" in addr:
                return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (addr, number, 0, 0))]
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, number))]

        mp.setattr(socket, "getaddrinfo", scripted_getaddrinfo)

        real_wrap_socket = ssl.SSLContext.wrap_socket
        real_wrap_bio = ssl.SSLContext.wrap_bio

        def spy_wrap_socket(self_ctx, sock, *args, **kwargs):
            if not kwargs.get("server_side", False) and not (args and args[0]):
                rig.tls_hostnames.append(kwargs.get("server_hostname"))
            return real_wrap_socket(self_ctx, sock, *args, **kwargs)

        def spy_wrap_bio(self_ctx, incoming, outgoing, *args, **kwargs):
            if not kwargs.get("server_side", False) and not (args and args[0]):
                rig.tls_hostnames.append(kwargs.get("server_hostname"))
            return real_wrap_bio(self_ctx, incoming, outgoing, *args, **kwargs)

        mp.setattr(ssl.SSLContext, "wrap_socket", spy_wrap_socket)
        mp.setattr(ssl.SSLContext, "wrap_bio", spy_wrap_bio)
        mp.setenv("SSL_CERT_FILE", self._tls.ca)

    def block_by_address(self):
        """Treat ::1 as blocked and 127.0.0.1 as allowed, where the guard looks it up."""
        blocked = ipaddress.ip_address(BLOCKED_ADDR)
        self._monkeypatch.setattr(url_guard, "_is_blocked_ip", lambda ip: ip == blocked)
        self._monkeypatch.setattr(settings, "environment", "production")

    # script helpers
    def script(self, name, steps):
        self.scripts[name] = list(steps)
        self.calls[name] = 0

    def base(self, name=NAME):
        return f"https://{name}:{self.port}"

    def respond(self, mode, redirect_to=""):
        self.mode = mode
        self.redirect_to = redirect_to

    # observation: a sentinel per listener proves every earlier connection was accepted
    def settle(self, addrs=(ALLOWED_ADDR, BLOCKED_ADDR)):
        for addr in addrs:
            probe = socket.create_connection((addr, self.port), timeout=5)
            try:
                mine = probe.getsockname()[1]
                self.sentinels.add((addr, mine))
                deadline = time.monotonic() + WAIT_SECONDS
                with self.cond:
                    while mine not in self.accepted[addr]:
                        left = deadline - time.monotonic()
                        if left <= 0:
                            pytest.fail("the listener did not accept the settle probe in time", pytrace=False)
                        self.cond.wait(left)
            finally:
                probe.close()

    def count(self, addr, only=False):
        self.settle((addr,) if only else (ALLOWED_ADDR, BLOCKED_ADDR))
        with self.cond:
            return len([p for p in self.accepted[addr] if (addr, p) not in self.sentinels])

    def close(self):
        self.stop.set()
        for sock in self._socks:
            try:
                sock.close()
            except OSError:
                pass
        for thread in self.threads:
            thread.join(5)


@pytest.fixture
def rig(tls_material, monkeypatch):
    r = Rig(tls_material, monkeypatch)
    yield r
    r.close()


@pytest.fixture
def guarded(rig):
    rig.block_by_address()
    return rig


# ── Outcomes ──────────────────────────────────────────────────────────────────
class Outcome:
    def __init__(self, kind, detail=""):
        self.kind = kind  # refused | conn_failed | completed | none | other
        self.detail = detail

    def __repr__(self):
        return f"Outcome({self.kind!r}, {self.detail!r})"


# Each driver: callable(env, base_url) -> Outcome, through the path's real entry point.
def _drive_workflow_action(env, base):
    from app.workflow_engine.actions.http_actions import ActionError, http_request

    try:
        http_request(None, DEFAULT_TENANT_ID, {"method": "GET", "url": base + "/x"}, {})
    except ActionError as exc:
        text = str(exc)
        if text.startswith("URL refused: "):
            return Outcome("refused", text)
        if text.startswith("Request failed: "):
            return Outcome("conn_failed", text)
        return Outcome("other", text)
    return Outcome("completed")


def _drive_autocount_probe(env, base):
    from modules.autocount.http_client import OpenProbeError, probe_open_connection

    try:
        probe_open_connection(base)
    except OpenProbeError as exc:
        text = exc.message
        if "Could not reach" in text:
            return Outcome("conn_failed", text)
        if "private or reserved" in text or "localhost" in text:
            return Outcome("refused", text)
        return Outcome("completed", text)  # reached the server, the body was not usable
    return Outcome("completed")


def _drive_autocount_paged_get(env, base):
    from modules.autocount.http_source.client import HttpApiClient, HttpTransportError

    client = HttpApiClient(base)
    try:
        client.get("/x", {})
    except HttpTransportError as exc:
        text = exc.message
        if text.startswith("Could not reach"):
            return Outcome("conn_failed", text)
        return Outcome("refused", text)
    finally:
        client.close()
    return Outcome("completed")


def _drive_connector(env, base):
    from modules.connector.registry import Product
    from modules.connector.services import product_client

    product = Product(
        key="p", display_name="P", tenant_slug="default", connection_id="c",
        consent_url="https://consent.test/x", api_base_url=base,
        ss_to_product_secret="s" * 32, call_audience="aud", guard_outbound=True,
    )
    env.monkeypatch.setattr(product_client, "TRANSPORT", None)
    try:
        product_client.send(
            product, method="GET", raw_path="/x", query="", body=b"", sub="",
            grant_id="", consented_at=0, tool="",
        )
    except httpx.TransportError as exc:
        if str(exc) == "blocked target":
            return Outcome("refused", str(exc))
        return Outcome("conn_failed", f"{type(exc).__name__}: {exc}")
    return Outcome("completed")


def _drive_messenger(env, base):
    from modules.omnichannel.adapters.messenger import MessengerAdapter

    env.monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    env.monkeypatch.setattr(settings, "meta_app_secret", "test-app-secret")
    result = MessengerAdapter().fetch_media_url({"access_token": "tok"}, base + "/v/img.png")
    return Outcome("none" if result is None else "completed")


def _drive_migration_media(env, base):
    from modules.omnichannel.services import migration_media

    db = env.session_factory()
    try:
        result = migration_media.fetch_and_store_media(
            db, tenant_id=DEFAULT_TENANT_ID, workspace_id="ws-conn", message_id="msg-conn",
            url=base + "/m/img.png", filename=None, declared_kind="IMAGE",
        )
    finally:
        db.close()
    if result.ok:
        return Outcome("completed")
    reason = result.reason or ""
    if reason.startswith("Source URL rejected: ") or reason.startswith("Redirected source URL rejected: "):
        return Outcome("refused", reason)
    if reason.startswith("Could not fetch source media"):
        return Outcome("conn_failed", reason)
    return Outcome("other", reason)


def _drive_webhook_delivery(env, base):
    from modules.omnichannel.models import WebhookDelivery, WebhookEndpoint
    from modules.omnichannel.security import encrypt_secret
    from modules.omnichannel.services import webhook_delivery

    db = env.session_factory()
    endpoint = WebhookEndpoint(
        tenant_id=DEFAULT_TENANT_ID, workspace_id="ws-conn", channel_id="ch-conn", name="hook",
        url=base + "/hook", secret_encrypted=encrypt_secret("signing-secret"),
        events_json=["message.inbound"], status="ACTIVE",
    )
    db.add(endpoint)
    db.commit()
    delivery = WebhookDelivery(
        tenant_id=DEFAULT_TENANT_ID, endpoint_id=endpoint.id, event_id="evt-conn",
        event_type="message.inbound", payload_json={"hello": "world"}, status="PENDING",
    )
    db.add(delivery)
    db.commit()
    delivery_id = delivery.id
    db.close()

    webhook_delivery.dispatch(env.session_factory(), delivery_id)

    db = env.session_factory()
    try:
        row = db.query(WebhookDelivery).filter(WebhookDelivery.id == delivery_id).first()
        error = row.error or ""
        status = row.response_status
    finally:
        db.close()
    if error.startswith("Delivery refused: "):
        return Outcome("refused", error)
    if error.startswith("Delivery failed: "):
        return Outcome("conn_failed", error)
    if status is not None:
        return Outcome("completed", error)
    return Outcome("other", error)


def _drive_gateway_fetch(env, base):
    from app.api_errors import ApiError
    from modules.omnichannel.services.public_gateway_service import PublicGatewayService

    db = env.session_factory()
    try:
        PublicGatewayService(db)._fetch_url(base + "/m/img.png")
    except ApiError as exc:
        if exc.code == "invalid_media_url":
            return Outcome("refused", exc.message)
        if exc.code == "media_fetch_failed":
            return Outcome("conn_failed", exc.message)
        return Outcome("other", f"{exc.code}: {exc.message}")
    finally:
        db.close()
    return Outcome("completed")


# name -> (driver, how a refusal reads, kind of a connection failure)
# ``refusal(tail)`` is the exact message today for a given guard tail.
PATHS = {
    "workflow_action": (_drive_workflow_action, lambda tail: f"URL refused: URL {tail}", "conn_failed"),
    "autocount_probe": (_drive_autocount_probe, lambda tail: f"baseUrl {tail}", "conn_failed"),
    "autocount_paged_get": (_drive_autocount_paged_get, lambda tail: f"baseUrl {tail}", "conn_failed"),
    "connector": (_drive_connector, lambda tail: "blocked target", "conn_failed"),
    "messenger_attachment": (_drive_messenger, None, "none"),
    "migration_media": (
        _drive_migration_media, lambda tail: f"Source URL rejected: URL {tail}", "conn_failed",
    ),
    "webhook_delivery": (
        _drive_webhook_delivery, lambda tail: f"Delivery refused: Callback URL {tail}", "conn_failed",
    ),
    "gateway_media_fetch": (
        _drive_gateway_fetch, lambda tail: f"Callback URL {tail}", "conn_failed",
    ),
}
NAME_TAIL = "resolves to a private or reserved IP."
LITERAL_TAIL = "cannot target a private or reserved IP."


@pytest.fixture
def env(session_factory, monkeypatch):
    return SimpleNamespace(session_factory=session_factory, monkeypatch=monkeypatch)


def _run(guarded, env, path, steps, name=NAME):
    driver = PATHS[path][0]
    guarded.script(name, steps)
    started = time.monotonic()
    outcome = driver(env, guarded.base(name))
    assert time.monotonic() - started < WAIT_SECONDS, "the path took too long"
    return outcome


def _assert_refused_as_today(path, outcome, tail):
    _driver, refusal, conn_kind = PATHS[path]
    if refusal is None:
        assert outcome.kind == "none", f"{path}: expected no result, got {outcome!r}"
        return
    assert outcome.kind == "refused", f"{path}: expected a refusal, got {outcome!r}"
    assert outcome.detail == refusal(tail), f"{path}: refusal message changed: {outcome.detail!r}"


# ── Controls: prove the rig itself works ──────────────────────────────────────
def test_control_a_direct_connection_to_each_listener_is_recorded(guarded):
    assert guarded.count(ALLOWED_ADDR) == 0 and guarded.count(BLOCKED_ADDR) == 0
    for addr in (ALLOWED_ADDR, BLOCKED_ADDR):
        sock = socket.create_connection((addr, guarded.port), timeout=5)
        sock.close()
    assert guarded.count(ALLOWED_ADDR) == 1, "direct connection to the allowed address not recorded"
    assert guarded.count(BLOCKED_ADDR) == 1, "direct connection to the blocked address not recorded"


def test_control_the_predicate_patch_and_the_scripted_resolver_work(guarded):
    assert url_guard._is_blocked_ip(ipaddress.ip_address(BLOCKED_ADDR)) is True
    assert url_guard._is_blocked_ip(ipaddress.ip_address(ALLOWED_ADDR)) is False
    guarded.script(NAME, SEQ_ALLOWED)
    url_guard.assert_deliverable(guarded.base())  # allowed answer: no refusal
    guarded.script(NAME, SEQ_BLOCKED)
    with pytest.raises(url_guard.UrlGuardError) as info:
        url_guard.assert_deliverable(guarded.base())
    assert str(info.value) == f"URL {NAME_TAIL}"
    assert guarded.calls[NAME] == 1


def test_control_the_scripted_resolver_reaches_the_async_path(guarded):
    import asyncio

    guarded.script(NAME, SEQ_ALLOWED)

    async def go():
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.get(guarded.base() + "/x")
        except httpx.HTTPError:
            pass  # the listener closes without a handshake: that is fine here

    asyncio.run(asyncio.wait_for(go(), WAIT_SECONDS))
    assert guarded.calls[NAME] >= 1, "the async client did not resolve through socket.getaddrinfo"
    assert guarded.count(ALLOWED_ADDR) >= 1, "the async client did not connect to the scripted address"
    assert guarded.count(BLOCKED_ADDR) == 0


def test_control_the_sync_client_resolves_through_the_scripted_resolver(guarded):
    guarded.script(NAME, SEQ_ALLOWED)
    try:
        httpx.get(guarded.base() + "/x", timeout=10.0)
    except httpx.HTTPError:
        pass
    assert guarded.calls[NAME] >= 1
    assert guarded.count(ALLOWED_ADDR) >= 1
    assert guarded.count(BLOCKED_ADDR) == 0


# ── C1/C2: the connection goes only to an allowed address ─────────────────────
@pytest.mark.parametrize("path", sorted(PATHS))
@pytest.mark.parametrize(
    "steps", [SEQ_ALLOWED_THEN_BLOCKED, SEQ_FAILURE_THEN_BLOCKED], ids=["allowed_then_blocked", "failure_then_blocked"]
)
def test_connection_goes_only_to_an_allowed_address(guarded, env, path, steps):
    _run(guarded, env, path, steps)
    assert guarded.count(BLOCKED_ADDR) == 0, f"{path}: connected to the blocked address, answers {steps}"


@pytest.mark.parametrize("path", sorted(PATHS))
def test_a_third_answer_that_is_blocked_is_never_connected_to(guarded, env, path):
    _run(guarded, env, path, SEQ_ALLOWED_ALLOWED_BLOCKED)
    assert guarded.count(BLOCKED_ADDR) == 0, f"{path}: connected to the blocked address"


@pytest.mark.parametrize("path", sorted(PATHS))
def test_a_resolver_failure_is_not_a_refusal(guarded, env, path):
    outcome = _run(guarded, env, path, SEQ_FAILURE_THEN_ALLOWED)
    assert outcome.kind != "refused", f"{path}: a failed first lookup was treated as a refusal: {outcome!r}"
    assert guarded.count(ALLOWED_ADDR) >= 1, f"{path}: never connected to the allowed address"
    assert guarded.count(BLOCKED_ADDR) == 0


@pytest.mark.parametrize("path", sorted(PATHS))
def test_an_allowed_address_is_connected_to(guarded, env, path):
    outcome = _run(guarded, env, path, SEQ_ALLOWED)
    assert outcome.kind != "refused", f"{path}: an allowed address was refused: {outcome!r}"
    assert guarded.count(ALLOWED_ADDR) >= 1, f"{path}: never connected to the allowed address"
    assert guarded.count(BLOCKED_ADDR) == 0


# ── C3: no answer at all is the path's normal connection failure ──────────────
@pytest.mark.parametrize("path", sorted(PATHS))
def test_a_name_with_no_answer_fails_through_normal_connection_handling(guarded, env, path):
    outcome = _run(guarded, env, path, SEQ_FAILURE)
    assert outcome.kind == PATHS[path][2], f"{path}: expected the connection failure outcome, got {outcome!r}"
    assert guarded.count(ALLOWED_ADDR) == 0 and guarded.count(BLOCKED_ADDR) == 0


# ── C4: blocked on the first check is refused as today, never connected to ────
@pytest.mark.parametrize("path", sorted(PATHS))
def test_a_name_blocked_on_the_first_check_is_refused_as_today(guarded, env, path):
    outcome = _run(guarded, env, path, SEQ_BLOCKED)
    _assert_refused_as_today(path, outcome, NAME_TAIL)
    assert guarded.count(BLOCKED_ADDR) == 0 and guarded.count(ALLOWED_ADDR) == 0


@pytest.mark.parametrize("path", sorted(PATHS))
def test_a_blocked_ip_literal_is_refused_as_today_and_never_connected_to(guarded, env, path):
    driver = PATHS[path][0]
    outcome = driver(env, f"https://[{BLOCKED_ADDR}]:{guarded.port}")
    if path == "messenger_attachment":
        assert outcome.kind == "none"
    else:
        _assert_refused_as_today(path, outcome, LITERAL_TAIL)
    assert guarded.count(BLOCKED_ADDR) == 0


# ── C5: the name stays the name ───────────────────────────────────────────────
@pytest.mark.parametrize("path", sorted(PATHS))
def test_the_host_header_and_tls_server_name_are_the_url_hostname(guarded, env, path):
    guarded.respond("ok")
    outcome = _run(guarded, env, path, SEQ_ALLOWED)
    assert outcome.kind != "refused", f"{path}: {outcome!r}"
    assert guarded.tls_hostnames, f"{path}: no TLS start was observed"
    assert set(guarded.tls_hostnames) == {NAME}, f"{path}: TLS server name was {guarded.tls_hostnames}"
    assert guarded.requests, f"{path}: the server saw no request"
    assert {host for _addr, host in guarded.requests} == {f"{NAME}:{guarded.port}"}, guarded.requests


# ── C6: redirects are never followed automatically ────────────────────────────
@pytest.mark.parametrize(
    "path",
    sorted(set(PATHS) - {"messenger_attachment", "migration_media"}),
)
def test_a_redirect_is_not_followed_automatically(guarded, env, path):
    guarded.script(HOP_NAME, SEQ_ALLOWED)
    guarded.respond("redirect", redirect_to=f"https://{HOP_NAME}:{guarded.port}/next")
    _run(guarded, env, path, SEQ_ALLOWED)
    assert guarded.requests, f"{path}: the first request was never answered"
    assert {host for _addr, host in guarded.requests} == {f"{NAME}:{guarded.port}"}, (
        f"{path}: followed a redirect: {guarded.requests}"
    )
    assert guarded.calls[HOP_NAME] == 0, f"{path}: looked up the redirect target"


@pytest.mark.parametrize("path", ["messenger_attachment", "migration_media"])
def test_a_hand_followed_redirect_is_checked_again_and_a_blocked_hop_is_not_connected_to(guarded, env, path):
    guarded.script(HOP_NAME, SEQ_BLOCKED)
    guarded.respond("redirect", redirect_to=f"https://{HOP_NAME}:{guarded.port}/next")
    outcome = _run(guarded, env, path, SEQ_ALLOWED)
    assert guarded.requests, f"{path}: the first hop was never requested"
    assert outcome.kind != "completed"
    assert guarded.count(BLOCKED_ADDR) == 0, f"{path}: connected to a blocked redirect target"
    assert {host for _addr, host in guarded.requests} == {f"{NAME}:{guarded.port}"}


@pytest.mark.parametrize("path", ["messenger_attachment", "migration_media"])
@pytest.mark.parametrize(
    "hop_steps",
    [SEQ_ALLOWED_THEN_BLOCKED, SEQ_FAILURE_THEN_BLOCKED],
    ids=["allowed_then_blocked", "failure_then_blocked"],
)
def test_a_hand_followed_hop_connects_only_to_an_allowed_address(guarded, env, path, hop_steps):
    guarded.script(HOP_NAME, hop_steps)
    guarded.respond("redirect", redirect_to=f"https://{HOP_NAME}:{guarded.port}/next")
    _run(guarded, env, path, SEQ_ALLOWED)
    assert guarded.requests, f"{path}: the first hop was never requested"
    # Nothing but the first hop may have been accepted on the blocked listener.
    blocked_hosts = [host for addr, host in guarded.requests if addr == BLOCKED_ADDR]
    assert guarded.count(BLOCKED_ADDR) == 0, (
        f"{path}: connected to the blocked address on the second hop, answers {hop_steps}; saw {blocked_hosts}"
    )


# ── C7: the development carve-out for local hosts keeps working ───────────────
@pytest.mark.parametrize("driver_name", ["autocount_probe", "autocount_paged_get"])
@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_development_keeps_the_local_host_exemption(rig, env, driver_name, host):
    env.monkeypatch.setattr(settings, "environment", "development")
    outcome = PATHS[driver_name][0](env, f"https://{host}:{rig.port}")
    assert outcome.kind != "refused", f"{driver_name}: a local host was refused in development: {outcome!r}"
    total = rig.count(ALLOWED_ADDR) + rig.count(BLOCKED_ADDR)
    assert total >= 1, f"{driver_name}: no connection reached the local {host} listener in development"


@pytest.mark.parametrize("driver_name", ["autocount_probe", "autocount_paged_get"])
def test_outside_development_a_local_literal_is_refused_and_not_connected_to(rig, env, driver_name):
    env.monkeypatch.setattr(settings, "environment", "production")
    outcome = PATHS[driver_name][0](env, f"https://127.0.0.1:{rig.port}")
    assert outcome.kind == "refused", f"{driver_name}: {outcome!r}"
    assert rig.count(ALLOWED_ADDR) == 0 and rig.count(BLOCKED_ADDR) == 0


@pytest.mark.parametrize("driver_name", ["autocount_probe", "autocount_paged_get"])
def test_development_does_not_exempt_a_name_that_resolves_to_a_blocked_address(guarded, env, driver_name):
    env.monkeypatch.setattr(settings, "environment", "development")
    outcome = _run(guarded, env, driver_name, SEQ_BLOCKED)
    assert outcome.kind == "refused", f"{driver_name}: {outcome!r}"
    assert guarded.count(BLOCKED_ADDR) == 0


# ── A resolver error that is not a name failure is still a connection failure ─
@pytest.mark.parametrize("path", sorted(PATHS))
@pytest.mark.parametrize(
    "steps", [["allowed", "fail"], ["allowed", "oserror"]], ids=["allowed_then_failure", "allowed_then_oserror"]
)
def test_a_later_resolver_error_is_the_normal_connection_failure(guarded, env, path, steps):
    try:
        outcome = _run(guarded, env, path, steps)
    except OSError as exc:
        pytest.fail(f"{path}: the resolver error escaped as {type(exc).__name__}: {exc}", pytrace=False)
    assert outcome.kind == PATHS[path][2], f"{path}: expected the connection failure outcome, got {outcome!r}"
    assert guarded.count(ALLOWED_ADDR) == 0 and guarded.count(BLOCKED_ADDR) == 0


# ── Mixed answers: one blocked address among the answer refuses the whole name ─
@pytest.mark.parametrize("path", sorted(PATHS))
@pytest.mark.parametrize(
    "steps",
    [
        ["mixed_allowed_first"],
        ["mixed_blocked_first"],
        ["allowed", "mixed_allowed_first"],
        ["allowed", "mixed_blocked_first"],
    ],
    ids=["mixed_allowed_first", "mixed_blocked_first", "later_mixed_allowed_first", "later_mixed_blocked_first"],
)
def test_an_answer_with_a_blocked_address_among_allowed_ones_connects_to_none(guarded, env, path, steps):
    outcome = _run(guarded, env, path, steps)
    if PATHS[path][1] is None:
        assert outcome.kind == "none", f"{path}: {outcome!r}"
    else:
        assert outcome.kind == "refused", f"{path}: expected a refusal for {steps}, got {outcome!r}"
    assert guarded.count(BLOCKED_ADDR) == 0, f"{path}: connected to the blocked address, answers {steps}"
    assert guarded.count(ALLOWED_ADDR) == 0, f"{path}: connected to the allowed address of a mixed answer {steps}"


# ── The next address is tried when the first refuses the connection ───────────
@pytest.mark.parametrize("path", ["workflow_action", "gateway_media_fetch"])
def test_the_next_allowed_address_is_tried_when_the_first_refuses(rig, env, path):
    rig.block_by_address()
    env.monkeypatch.setattr(url_guard, "_is_blocked_ip", lambda ip: False)  # both loopbacks allowed
    rig._socks[0].close()  # nothing listens on 127.0.0.1 now: that connection is refused
    rig.script(NAME, ["two_loopback"])
    PATHS[path][0](env, rig.base())
    assert rig.count(BLOCKED_ADDR, only=True) >= 1, f"{path}: never reached the second address"


# ── Gateway: the connect-time refusal reads like the pre-flight one ───────────
def test_the_gateway_answers_a_connect_time_refusal_like_the_pre_flight_one(guarded, env):
    from app.api_errors import ApiError
    from modules.omnichannel.services.public_gateway_service import PublicGatewayService

    guarded.script(NAME, SEQ_ALLOWED_THEN_BLOCKED)
    db = env.session_factory()
    try:
        with pytest.raises(ApiError) as info:
            PublicGatewayService(db)._fetch_url(guarded.base() + "/m/img.png")
    finally:
        db.close()
    assert info.value.status_code == 422
    assert info.value.code == "invalid_media_url"
    assert info.value.message == f"Callback URL {NAME_TAIL}"
    assert guarded.count(BLOCKED_ADDR) == 0


# ── The development exemption depends on the environment ──────────────────────
LOCAL_LOOKING_NAME = "127.edge-test.example.test"


def test_a_local_looking_name_with_a_blocked_answer_is_refused_outside_development(guarded, monkeypatch):
    from modules.autocount.http_client import autocount_guarded_client

    monkeypatch.setattr(settings, "environment", "production")
    guarded.script(LOCAL_LOOKING_NAME, SEQ_BLOCKED)
    client = autocount_guarded_client(10.0)
    try:
        with pytest.raises(url_guard.UrlGuardError):
            client.get(guarded.base(LOCAL_LOOKING_NAME) + "/x")
    finally:
        client.close()
    assert guarded.count(BLOCKED_ADDR) == 0


def test_a_local_looking_name_is_connected_to_in_development(guarded, monkeypatch):
    from modules.autocount.http_client import autocount_guarded_client

    monkeypatch.setattr(settings, "environment", "development")
    guarded.script(LOCAL_LOOKING_NAME, SEQ_BLOCKED)
    client = autocount_guarded_client(10.0)
    try:
        try:
            client.get(guarded.base(LOCAL_LOOKING_NAME) + "/x")
        except httpx.HTTPError:
            pass  # the listener closes without a handshake
    finally:
        client.close()
    assert guarded.count(BLOCKED_ADDR) >= 1, "the development carve-out did not connect"


# ── The transports themselves ─────────────────────────────────────────────────
def test_the_sync_transport_refuses_a_blocked_literal_without_connecting(guarded):
    client = httpx.Client(transport=url_guard.GuardedTransport(), timeout=10.0)
    try:
        with pytest.raises(url_guard.UrlGuardError):
            client.get(f"https://[{BLOCKED_ADDR}]:{guarded.port}/x")
    finally:
        client.close()
    assert guarded.count(BLOCKED_ADDR) == 0


def test_the_async_transport_refuses_a_blocked_literal_without_connecting(guarded):
    import asyncio

    async def go():
        async with httpx.AsyncClient(transport=url_guard.GuardedAsyncTransport(), timeout=10.0) as client:
            await client.get(f"https://[{BLOCKED_ADDR}]:{guarded.port}/x")

    with pytest.raises(url_guard.UrlGuardError):
        asyncio.run(asyncio.wait_for(go(), WAIT_SECONDS))
    assert guarded.count(BLOCKED_ADDR) == 0


@pytest.mark.parametrize("step", ["oserror", "fail"])
def test_the_async_transport_turns_a_resolver_error_into_a_connect_error(guarded, step):
    import asyncio

    guarded.script(NAME, [step])

    async def go():
        async with httpx.AsyncClient(transport=url_guard.GuardedAsyncTransport(), timeout=10.0) as client:
            await client.get(guarded.base() + "/x")

    with pytest.raises(httpx.ConnectError):
        asyncio.run(asyncio.wait_for(go(), WAIT_SECONDS))
    assert guarded.count(ALLOWED_ADDR) == 0 and guarded.count(BLOCKED_ADDR) == 0


@pytest.mark.parametrize("step", ["oserror", "fail"])
def test_the_sync_transport_turns_a_resolver_error_into_a_connect_error(guarded, step):
    guarded.script(NAME, [step])
    client = httpx.Client(transport=url_guard.GuardedTransport(), timeout=10.0)
    try:
        with pytest.raises(httpx.ConnectError):
            client.get(guarded.base() + "/x")
    finally:
        client.close()


# ── Messenger: a connect-time refusal is not logged as a failure ──────────────
def test_a_connect_time_refusal_on_the_attachment_path_is_not_logged_as_an_error(guarded, env, caplog):
    import logging

    caplog.set_level(logging.ERROR)
    outcome = _run(guarded, env, "messenger_attachment", SEQ_ALLOWED_THEN_BLOCKED)
    assert outcome.kind == "none"
    assert guarded.count(BLOCKED_ADDR) == 0
    assert not [r for r in caplog.records if "media URL fetch failed" in r.getMessage()]


# ── Several checked addresses: the async path behaves like the plain client ───
# One address of the name never answers; the other is the live listener. The
# wrapped backend call stands in for a host that does not respond, without any
# traffic leaving the machine.
class _Attempts:
    def __init__(self):
        self.started = []
        self.cancelled = []
        self.timed_out = []


def _make_unanswered(monkeypatch, unanswered):
    import anyio
    import httpcore

    attempts = _Attempts()
    real = httpcore.AnyIOBackend.connect_tcp

    async def wrapped(self, host, port, timeout=None, local_address=None, socket_options=None):
        attempts.started.append(host)
        if host in unanswered:
            try:
                with anyio.move_on_after(timeout):
                    await anyio.sleep_forever()
            except BaseException:
                attempts.cancelled.append(host)
                raise
            attempts.timed_out.append(host)
            raise httpcore.ConnectTimeout("scripted: no answer")
        return await real(self, host, port, timeout, local_address, socket_options)

    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", wrapped)
    return attempts


def _two_addresses(rig, monkeypatch):
    monkeypatch.setattr(url_guard, "_is_blocked_ip", lambda ip: False)
    rig.script(NAME, ["two_loopback"])  # 127.0.0.1 first, ::1 second
    rig.respond("ok")


BUDGET = 3.0


def _timed_get(rig, budget=BUDGET, after=None):
    import asyncio

    async def go():
        started = time.monotonic()
        result = None
        error = None
        async with httpx.AsyncClient(
            transport=url_guard.GuardedAsyncTransport(), timeout=budget
        ) as client:
            try:
                result = (await client.get(rig.base() + "/x")).status_code
            except httpx.HTTPError as exc:
                error = exc
        elapsed = time.monotonic() - started
        if after is not None:
            await after()
        return result, error, elapsed

    return asyncio.run(asyncio.wait_for(go(), WAIT_SECONDS))


def test_an_unanswered_first_address_does_not_hold_back_a_live_second_one(rig, monkeypatch):
    _two_addresses(rig, monkeypatch)
    _make_unanswered(monkeypatch, {ALLOWED_ADDR})
    status, error, elapsed = _timed_get(rig)
    assert error is None and status == 200, f"the request did not complete: {error!r}"
    assert elapsed < 1.5, f"took {elapsed:.2f}s of a {BUDGET:.0f}s budget with a live second address"


def test_every_address_unanswered_fails_within_one_budget(rig, monkeypatch):
    _two_addresses(rig, monkeypatch)
    _make_unanswered(monkeypatch, {ALLOWED_ADDR, BLOCKED_ADDR})
    status, error, elapsed = _timed_get(rig)
    assert isinstance(error, httpx.ConnectTimeout), f"expected a connect timeout, got {error!r} / {status}"
    assert 2.0 <= elapsed < 4.5, f"took {elapsed:.2f}s for a {BUDGET:.0f}s budget over two addresses"


def test_the_losing_attempt_is_cancelled_and_nothing_is_left_running(rig, monkeypatch):
    import asyncio

    _two_addresses(rig, monkeypatch)
    attempts = _make_unanswered(monkeypatch, {ALLOWED_ADDR})

    async def settled():
        deadline = time.monotonic() + 5.0
        while len(asyncio.all_tasks()) > 1 and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        assert len(asyncio.all_tasks()) == 1, f"tasks left running: {asyncio.all_tasks()}"

    status, error, _elapsed = _timed_get(rig, after=settled)
    assert error is None and status == 200, f"the request did not complete: {error!r}"
    assert attempts.cancelled == [ALLOWED_ADDR], (
        f"the unanswered attempt was not cancelled (cancelled={attempts.cancelled}, "
        f"timed_out={attempts.timed_out})"
    )


def test_the_gateway_fetch_is_not_held_back_by_an_unanswered_first_address(rig, env, monkeypatch):
    from app.api_errors import ApiError
    from modules.omnichannel.services.public_gateway_service import PublicGatewayService

    _two_addresses(rig, monkeypatch)
    _make_unanswered(monkeypatch, {ALLOWED_ADDR})
    db = env.session_factory()
    started = time.monotonic()
    body = None
    failure = None
    try:
        body = PublicGatewayService(db)._fetch_url(rig.base() + "/m/img.png")
    except ApiError as exc:
        failure = exc
    finally:
        db.close()
    elapsed = time.monotonic() - started
    assert failure is None and body == b"ok", f"the fetch did not complete: {failure and failure.message}"
    assert elapsed < 5.0, f"the fetch took {elapsed:.2f}s with a live second address"
