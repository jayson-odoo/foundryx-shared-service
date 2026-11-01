"""Storage URL reads (hardening slice over `app/integrations/s3_provider.py`).

A tenant's storage connection carries an editable `cdnBaseUrl` / `endpointUrl`.
`S3CompatibleAdapter.resolve(key)` turns it into `("url", ...)` or
`("presigned", ...)`, and four places then open that URL:

  * `DocumentService._read_blob`          (ZIP download jobs)
  * `ImportService._read_content`         (import preview / validate / commit)
  * `ImportService.error_file`            (import error report)
  * `S3CompatibleAdapter.run_probe`       (connection test, via `_http_get`)

Rules covered here:

  R1  saving a connection with a non-https or blocked-address URL is refused
  R2  a stored URL that is not a public https URL is never opened by any reader
  R3  the same, through the real routes (import preview, document ZIP job)
  R4  redirects are not followed on these reads
  R5  reads carry a timeout and stop at the import size limit
  R6  local paths, presigned https, public https CDN and platform storage keep
      working

Test doubles (no outside network, no real system files):
  * `socket.getaddrinfo` is scripted: only the `*.storage.test` names below
    resolve, everything else raises `gaierror`.
  * `socket.socket.connect` is redirected at the lowest seam: any outbound TCP
    connect lands on the in-process listener (or is refused when none runs) and
    is RECORDED with the socket timeout in force. A reader that never connects
    leaves `net.attempts` empty.
  * TLS: a throwaway CA built with `cryptography` is trusted through the
    standard CA-bundle variables, so a real certificate check happens.
  * boto3 is stubbed at the adapter `_build_client` seam, as in
    `tests/test_storage_resolution.py`.
"""
import gzip
import io
import socket
import ssl
import threading
import zipfile
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pytest

from app.integrations.s3_provider import S3CompatibleAdapter
from app.models.connection import Connection
from app.models.document import File, FileVersion
from app.models.import_job import ImportJob
from app.models.tenant import DEFAULT_TENANT_ID, PLATFORM_TENANT_ID
from app.services import storage as storage_module
from app.services.document_service import DocumentService
from app.services.storage import StorageReadError, read_object, read_url, storage_for_tenant
from app.import_engine.service import ImportService
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from tests.test_storage_providers import StubS3Client
from tests.test_storage_resolution import S3_PAYLOAD, R2_PAYLOAD, _login, _storage_connection

CANARY = "canary-7f3a91c2d4e85b60"
CANARY_BYTES = CANARY.encode()
MIB = 1024 * 1024

# Scripted name resolution (no outside lookups).
PUBLIC_IP = "93.184.216.34"
HOSTS = {
    "cdn.storage.test": PUBLIC_IP,
    "other.storage.test": "93.184.216.35",
    "internal.storage.test": "10.0.0.5",
    "meta.storage.test": "169.254.169.254",
    "localhost": "127.0.0.1",
    "seq.storage.test": PUBLIC_IP,
}


# ═══════════════════════════════════════════════════════════════════════════
# harness
# ═══════════════════════════════════════════════════════════════════════════


def _tls_material(directory: Path):
    """Throwaway CA + a server certificate for the scripted names and 127.0.0.1."""
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.now(timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "storage test CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
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
    sans: List[x509.GeneralName] = [x509.DNSName(h) for h in HOSTS]
    sans.append(x509.DNSName("localhost"))
    sans.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "cdn.storage.test")]))
        .issuer_name(ca_name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    ca_pem = directory / "ca.pem"
    chain_pem = directory / "server.pem"
    key_pem = directory / "server.key"
    ca_pem.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    chain_pem.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key_pem.write_bytes(
        leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return ca_pem, chain_pem, key_pem


class Listener:
    """In-process loopback listener. Records connections, requests, bytes sent.

    mode "serve"    200 with `objects[path]` or `body`
    mode "redirect" first path answers 302 to another host; `/landing` serves
    mode "big"      200 streaming `big_bytes` bytes in 64 KiB pieces
    mode "ftp"      sends an FTP greeting then hangs up
    """

    def __init__(self, ctx: Optional[ssl.SSLContext], mode: str = "serve", big_bytes: int = 0):
        self.ctx = ctx
        self.mode = mode
        self.big_bytes = big_bytes
        self.framing = "exact"  # for mode "framed": exact | none | chunked | stall
        self.body = CANARY_BYTES
        self.objects: Dict[str, bytes] = {}
        self.requests: List[str] = []
        self.request_headers: List[str] = []
        self.encoding = "gzip"  # for mode "compressed": gzip | deflate
        self.extra_headers = b""  # added to a plain served answer
        self.connections = 0
        self.bytes_sent = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self._sock.settimeout(0.2)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self._lock:
                self.connections += 1
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        try:
            conn.settimeout(5)
            if self.mode == "ftp":
                conn.sendall(b"220 ready\r\n")
                conn.recv(1024)
                return
            if self.ctx is not None:
                conn = self.ctx.wrap_socket(conn, server_side=True)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                data += chunk
            path = data.split(b"\r\n")[0].decode("latin-1").split(" ")[1]
            with self._lock:
                self.requests.append(path)
            bare = path.split("?")[0]
            with self._lock:
                self.request_headers.append(data.split(b"\r\n\r\n")[0].decode("latin-1").lower())
            if self.mode == "compressed":
                raw = self.objects.get(bare, b"A" * (4 * MIB))
                body = gzip.compress(raw) if self.encoding == "gzip" else zlib.compress(raw)
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Encoding: %s\r\nContent-Length: %d\r\n"
                    b"Connection: close\r\n\r\n" % (self.encoding.encode(), len(body))
                    + body
                )
                return
            if self.mode == "redirect" and bare != "/landing":
                conn.sendall(
                    b"HTTP/1.1 302 Found\r\nLocation: https://other.storage.test/landing\r\n"
                    b"Content-Length: 0\r\nConnection: close\r\n\r\n"
                )
                return
            if self.mode == "notfound":
                conn.sendall(
                    b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
                return
            if self.mode == "framed":
                self._send_framed(conn)
                return
            if self.mode == "big":
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n"
                    % self.big_bytes
                )
                piece = b"x" * 65536
                sent = 0
                while sent < self.big_bytes:
                    n = min(len(piece), self.big_bytes - sent)
                    conn.sendall(piece[:n])
                    sent += n
                    with self._lock:
                        self.bytes_sent += n
                return
            body = self.objects.get(bare, self.body)
            conn.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n" % len(body)
                + self.extra_headers
                + b"Connection: close\r\n\r\n"
                + body
            )
        except Exception:  # noqa: BLE001 - a client that hangs up mid-send is expected
            pass
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    def _send_framed(self, conn):
        if self.framing == "stall":
            conn.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % self.big_bytes
            )
            self._stop.wait(8)
            return
        if self.framing == "exact":
            head = b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % self.big_bytes
        elif self.framing == "chunked":
            head = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
        else:
            head = b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n"
        conn.sendall(head)
        piece = b"x" * 65536
        sent = 0
        while sent < self.big_bytes:
            n = min(len(piece), self.big_bytes - sent)
            if self.framing == "chunked":
                conn.sendall(b"%x\r\n" % n + piece[:n] + b"\r\n")
            else:
                conn.sendall(piece[:n])
            sent += n
            with self._lock:
                self.bytes_sent += n
        if self.framing == "chunked":
            conn.sendall(b"0\r\n\r\n")

    def close(self):
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass


class Net:
    def __init__(self, tmp_path: Path, tls_files):
        self.tmp_path = tmp_path
        self.listener: Optional[Listener] = None
        self.attempts: List[tuple] = []  # (host, port, socket timeout at connect)
        self.sequences: Dict[str, List[str]] = {}  # name -> answers, one per lookup
        ca, chain, key = tls_files
        self.ca = ca
        self._ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._ctx.load_cert_chain(str(chain), str(key))

    def start(self, *, tls: bool, mode: str = "serve", big_bytes: int = 0) -> Listener:
        assert self.listener is None, "one listener per test"
        self.listener = Listener(self._ctx if tls else None, mode, big_bytes)
        return self.listener

    @property
    def port(self) -> int:
        assert self.listener is not None
        return self.listener.port


@pytest.fixture(scope="session")
def _tls_files(tmp_path_factory):
    # One CA per process: the standard library keeps the trust store it first
    # loaded, so every test in the process must share the same CA.
    return _tls_material(tmp_path_factory.mktemp("storage-tls"))


@pytest.fixture
def net(tmp_path, monkeypatch, _tls_files):
    n = Net(tmp_path, _tls_files)
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        monkeypatch.setenv(var, str(n.ca))

    real_getaddrinfo = socket.getaddrinfo

    def scripted_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):  # noqa: A002
        name = host.decode() if isinstance(host, bytes) else host
        try:
            socket.inet_aton(name)
            return real_getaddrinfo(name, port, family, type, proto, flags)
        except OSError:
            pass
        ip = HOSTS.get(name.lower())
        answers = n.sequences.get(name.lower())
        if answers:
            ip = answers.pop(0) if len(answers) > 1 else answers[0]
            if ip == "FAIL":
                raise socket.gaierror(socket.EAI_AGAIN, "scripted: lookup failed")
        if ip is None:
            raise socket.gaierror(socket.EAI_NONAME, "scripted: unknown name")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0))]

    real_connect = socket.socket.connect

    def redirected_connect(self, address):
        if not isinstance(address, tuple):  # unix sockets etc. are not outbound reads
            return real_connect(self, address)
        host, port = address[0], address[1]
        if n.listener is not None and host == "127.0.0.1" and port == n.listener.port:
            n.attempts.append((host, port, self.gettimeout()))
            return real_connect(self, address)
        n.attempts.append((host, port, self.gettimeout()))
        if n.listener is None:
            raise ConnectionRefusedError("no listener in this test")
        return real_connect(self, ("127.0.0.1", n.listener.port))

    monkeypatch.setattr(socket, "getaddrinfo", scripted_getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", redirected_connect)
    yield n
    if n.listener is not None:
        n.listener.close()


class MirrorClient(StubS3Client):
    """Stub bucket whose stored objects are also visible through the CDN side
    (listener path or a directory), so a probe round-trip can succeed when the
    CDN really is reachable."""

    def __init__(self, on_put=None):
        super().__init__()
        self.on_put = on_put

    def put_object(self, Bucket, Key, Body, ContentType):  # noqa: N803
        super().put_object(Bucket, Key, Body, ContentType)
        if self.on_put is not None:
            self.on_put(Key, Body)

    def generate_presigned_url(self, op, Params, ExpiresIn):  # noqa: N803
        self.presigned.append(Params["Key"])
        return f"https://cdn.storage.test/{Params['Key']}?sig=abc"


@pytest.fixture
def bucket(monkeypatch):
    client = MirrorClient()
    monkeypatch.setattr(S3CompatibleAdapter, "_build_client", lambda self: client)
    storage_module.clear_adapter_cache()
    return client


@pytest.fixture
def canary_dir(tmp_path):
    d = tmp_path / "objects"
    d.mkdir()
    (d / "obj.bin").write_bytes(CANARY_BYTES)
    return d


def _mirror_into_dir(bucket: MirrorClient, directory: Path):
    def put(key, body):
        target = directory / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)

    bucket.on_put = put


def _mirror_into_listener(bucket: MirrorClient, listener: Listener):
    bucket.on_put = lambda key, body: listener.objects.__setitem__("/" + key, body)


# ── readers: the four places that open a resolved URL ──────────────────────


class Outcome:
    def __init__(self, ok: bool, data: bytes = b""):
        self.ok = ok
        self.data = data


def _new_job(db, **fields) -> ImportJob:
    job = ImportJob(
        tenant_id=DEFAULT_TENANT_ID, entity_type="user", status="pending", **fields
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def read_blob(db, conn, raw="obj.bin") -> Outcome:
    storage = storage_for_tenant(db, DEFAULT_TENANT_ID)
    data = DocumentService._read_blob(storage, f"conn:{conn.id}:{raw}")
    return Outcome(data is not None, data or b"")


def read_import(db, conn, raw="obj.bin") -> Outcome:
    job = _new_job(db, file_storage_key=f"conn:{conn.id}:{raw}")
    try:
        return Outcome(True, ImportService(db)._read_content(job))
    except Exception:  # noqa: BLE001 - a failed read is reported as an exception here
        return Outcome(False)


def read_errors(db, conn, raw="obj.bin") -> Outcome:
    job = _new_job(db, error_report_key=f"conn:{conn.id}:{raw}")
    try:
        content, _name = ImportService(db).error_file(DEFAULT_TENANT_ID, job.id)
        return Outcome(True, content)
    except Exception:  # noqa: BLE001
        return Outcome(False)


def read_probe(db, conn, raw="obj.bin") -> Outcome:
    adapter = storage_module._adapter_for(conn)
    return Outcome(adapter.run_probe().ok)


READERS = {
    "document_blob": read_blob,
    "import_content": read_import,
    "import_error_report": read_errors,
    "connection_probe": read_probe,
}
CONTENT_READERS = ["document_blob", "import_content", "import_error_report"]


def _connect(db, cdn: str, tenant: str = DEFAULT_TENANT_ID) -> Connection:
    conn = _storage_connection(db, tenant, cdn=cdn)
    storage_module.clear_adapter_cache()
    return conn


# ═══════════════════════════════════════════════════════════════════════════
# R2  a stored URL that is not a public https URL is never opened
# ═══════════════════════════════════════════════════════════════════════════
# Each target builder returns the stored `cdnBaseUrl` value. Listener-backed
# targets also expose their object through the listener, canary-dir targets
# through the directory, so a probe round-trip would succeed if it were read.


def _file_uri(d: Path) -> str:
    return d.as_uri()


def t_file(net, d, bucket):
    _mirror_into_dir(bucket, d)
    return _file_uri(d)


def t_file_upper(net, d, bucket):
    _mirror_into_dir(bucket, d)
    return "FILE" + _file_uri(d)[4:]


def t_file_leading_space(net, d, bucket):
    _mirror_into_dir(bucket, d)
    return " " + _file_uri(d)


def t_ftp(net, d, bucket):
    net.start(tls=False, mode="ftp")
    return f"ftp://127.0.0.1:{net.port}"


def t_http(net, d, bucket):
    _mirror_into_listener(bucket, net.start(tls=False))
    return f"http://127.0.0.1:{net.port}"


def t_http_upper(net, d, bucket):
    _mirror_into_listener(bucket, net.start(tls=False))
    return f"HTTP://127.0.0.1:{net.port}"


def t_http_leading_space(net, d, bucket):
    _mirror_into_listener(bucket, net.start(tls=False))
    return f" http://127.0.0.1:{net.port}"


def t_data(net, d, bucket):
    return f"data:text/plain,{CANARY}"


def t_https_loopback(net, d, bucket):
    _mirror_into_listener(bucket, net.start(tls=True))
    return f"https://127.0.0.1:{net.port}"


def t_https_private_name(net, d, bucket):
    _mirror_into_listener(bucket, net.start(tls=True))
    return "https://internal.storage.test"


def t_https_link_local_name(net, d, bucket):
    _mirror_into_listener(bucket, net.start(tls=True))
    return "https://meta.storage.test"


def t_https_localhost(net, d, bucket):
    _mirror_into_listener(bucket, net.start(tls=True))
    return f"https://localhost:{net.port}"


TARGETS = {
    "file": t_file,
    "file_upper": t_file_upper,
    "file_leading_space": t_file_leading_space,
    "ftp": t_ftp,
    "http": t_http,
    "http_upper": t_http_upper,
    "http_leading_space": t_http_leading_space,
    "data": t_data,
    "https_loopback": t_https_loopback,
    "https_private_name": t_https_private_name,
    "https_link_local_name": t_https_link_local_name,
    "https_localhost": t_https_localhost,
}


@pytest.mark.parametrize("reader", list(READERS))
@pytest.mark.parametrize("target", list(TARGETS))
def test_a_stored_url_that_is_not_public_https_is_not_read(
    reader, target, net, bucket, canary_dir, session_factory
):
    """R2: the read fails the way the place already reports a failed read, the
    target's bytes never reach the caller, and nothing connects to the target."""
    if reader == "connection_probe" and target == "data":
        pytest.skip("a data: value carries no object the probe could round-trip")
    db = session_factory()
    cdn = TARGETS[target](net, canary_dir, bucket)
    conn = _connect(db, cdn)
    out = READERS[reader](db, conn)
    assert not out.ok, f"{reader} reported a successful read of {cdn!r}"
    assert CANARY_BYTES not in out.data
    assert net.attempts == [], f"{reader} connected out for {cdn!r}: {net.attempts}"
    if net.listener is not None:
        assert net.listener.connections == 0
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# R4  redirects are not followed
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("reader", list(READERS))
def test_a_redirect_from_a_storage_url_is_not_followed(reader, net, bucket, session_factory):
    db = session_factory()
    net.start(tls=True, mode="redirect")
    conn = _connect(db, "https://cdn.storage.test")
    out = READERS[reader](db, conn)
    assert not out.ok
    assert CANARY_BYTES not in out.data
    assert net.listener.connections == 1, "a second connection means the redirect was followed"
    assert net.listener.requests == ["/obj.bin"] or reader == "connection_probe"
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# R5  timeout and size limit
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("reader", list(READERS))
def test_storage_reads_carry_a_timeout(reader, net, bucket, session_factory):
    db = session_factory()
    listener = net.start(tls=True)
    _mirror_into_listener(bucket, listener)
    conn = _connect(db, "https://cdn.storage.test")
    READERS[reader](db, conn)
    assert net.attempts, "the read never connected"
    for _host, _port, timeout in net.attempts:
        assert timeout is not None and 0 < timeout <= 60, f"socket timeout was {timeout!r}"
    db.close()


def test_an_import_read_stops_at_the_import_size_limit(net, bucket, session_factory):
    """The tenant's import file limit (`ImportService.caps`) is the storage's own
    object size limit for an import file. A target sending 64 MiB against a
    1 MiB limit is cut off, not read to the end."""
    db = session_factory()
    ImportService(db).set_settings(DEFAULT_TENANT_ID, None, 1)
    listener = net.start(tls=True, mode="big", big_bytes=64 * MIB)
    conn = _connect(db, "https://cdn.storage.test")
    out = read_import(db, conn)
    assert len(out.data) <= 1 * MIB
    assert listener.bytes_sent < 32 * MIB, f"server sent {listener.bytes_sent} bytes"
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# R6  keeps working
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("reader", CONTENT_READERS)
def test_a_public_https_cdn_is_read(reader, net, bucket, session_factory):
    db = session_factory()
    net.start(tls=True)
    conn = _connect(db, "https://cdn.storage.test")
    out = READERS[reader](db, conn)
    assert out.ok
    assert out.data == CANARY_BYTES
    assert net.listener.requests == ["/obj.bin"]
    db.close()


def test_the_probe_round_trips_through_a_public_https_cdn(net, bucket, session_factory):
    db = session_factory()
    listener = net.start(tls=True)
    _mirror_into_listener(bucket, listener)
    conn = _connect(db, "https://cdn.storage.test")
    assert read_probe(db, conn).ok
    db.close()


@pytest.mark.parametrize("reader", CONTENT_READERS)
def test_a_presigned_https_url_is_read(reader, net, bucket, session_factory):
    db = session_factory()
    net.start(tls=True)
    conn = _connect(db, "")  # no CDN: reads go through the presigned URL
    out = READERS[reader](db, conn)
    assert out.ok
    assert out.data == CANARY_BYTES
    assert bucket.presigned == ["obj.bin"]
    assert net.listener.requests == ["/obj.bin?sig=abc"]
    db.close()


@pytest.mark.parametrize("reader", CONTENT_READERS)
def test_local_storage_is_read(reader, tmp_path, monkeypatch, session_factory):
    from app.config import settings

    media = tmp_path / "media"
    media.mkdir()
    (media / "local.bin").write_bytes(CANARY_BYTES)
    monkeypatch.setattr(settings, "media_root", str(media))
    db = session_factory()
    if reader == "document_blob":
        out = Outcome(True, DocumentService._read_blob(storage_for_tenant(db, DEFAULT_TENANT_ID), "local.bin"))
    elif reader == "import_content":
        job = _new_job(db, file_storage_key="local.bin")
        out = Outcome(True, ImportService(db)._read_content(job))
    else:
        job = _new_job(db, error_report_key="local.bin")
        out = Outcome(True, ImportService(db).error_file(DEFAULT_TENANT_ID, job.id)[0])
    assert out.data == CANARY_BYTES
    db.close()


def _seed_platform_storage(db, monkeypatch, cdn: str) -> Connection:
    from cryptography.fernet import Fernet

    from app.config import settings
    from app.seed import seed_platform_storage_connection

    monkeypatch.setattr(settings, "platform_storage_provider", "r2")
    monkeypatch.setattr(settings, "platform_storage_account_id", "acct1")
    monkeypatch.setattr(settings, "platform_storage_bucket", "platform-assets")
    monkeypatch.setattr(settings, "platform_storage_cdn_base_url", cdn)
    monkeypatch.setattr(settings, "fernet_key", Fernet.generate_key().decode())
    seed_platform_storage_connection(db)
    db.commit()
    storage_module.clear_adapter_cache()
    return (
        db.query(Connection)
        .filter(Connection.tenant_id == PLATFORM_TENANT_ID, Connection.type == "storage")
        .one()
    )


@pytest.mark.parametrize("reader", CONTENT_READERS)
def test_platform_storage_on_a_private_address_is_still_read(
    reader, net, bucket, monkeypatch, session_factory
):
    """The operator chose the platform storage address, so a private address
    there is accepted for a tenant that falls back to it."""
    db = session_factory()
    net.start(tls=True)
    platform = _seed_platform_storage(db, monkeypatch, "https://internal.storage.test")
    out = READERS[reader](db, platform)
    assert out.ok
    assert out.data == CANARY_BYTES
    assert net.listener.requests == ["/obj.bin"]
    db.close()


@pytest.mark.parametrize("target", ["file", "ftp", "data"])
@pytest.mark.parametrize("reader", CONTENT_READERS)
def test_platform_storage_with_a_non_http_scheme_is_not_read(
    reader, target, net, bucket, canary_dir, monkeypatch, session_factory
):
    db = session_factory()
    cdn = TARGETS[target](net, canary_dir, bucket)
    platform = _seed_platform_storage(db, monkeypatch, cdn)
    out = READERS[reader](db, platform)
    assert not out.ok
    assert CANARY_BYTES not in out.data
    assert net.attempts == []
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# R3  through the real routes
# ═══════════════════════════════════════════════════════════════════════════


def _admin(client):
    return _login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD)


def _preview(client, db, conn) -> Optional[object]:
    job = _new_job(db, file_storage_key=f"conn:{conn.id}:preview.csv")
    try:
        return client.get(f"/imports/{job.id}/preview", headers=_admin(client))
    except Exception:  # noqa: BLE001 - an unhandled read failure surfaces as a server error
        return None


def _everything_returned(res) -> bytes:
    if res is None:
        return b""
    return res.content + repr(dict(res.headers)).encode()


def test_import_preview_does_not_return_a_file_url_target(
    client, session_factory, bucket, canary_dir, net
):
    """R3: stored `file:` CDN value + import preview. The target holds a CSV whose
    header row carries the canary; the preview would echo headers back."""
    (canary_dir / "preview.csv").write_bytes(f"{CANARY},Email\n1,a@example.com\n".encode())
    db = session_factory()
    conn = _connect(db, _file_uri(canary_dir))
    res = _preview(client, db, conn)
    assert CANARY_BYTES not in _everything_returned(res)
    db.close()


def test_import_preview_returns_headers_from_a_public_https_cdn(
    client, session_factory, bucket, net
):
    """Control for the route above: the same route does return the file's
    headers when the CDN is a public https address."""
    listener = net.start(tls=True)
    listener.objects["/preview.csv"] = f"{CANARY},Email\n1,a@example.com\n".encode()
    db = session_factory()
    conn = _connect(db, "https://cdn.storage.test")
    res = _preview(client, db, conn)
    assert res is not None and res.status_code == 200, getattr(res, "text", "")
    assert CANARY in res.text
    db.close()


def _zip_job(client, db, conn):
    folder_file = File(tenant_id=DEFAULT_TENANT_ID, name="doc.txt")
    db.add(folder_file)
    db.flush()
    version = FileVersion(
        file_id=folder_file.id, ordinal=1, storage_key=f"conn:{conn.id}:obj.bin",
        size_bytes=len(CANARY_BYTES), mime="text/plain",
    )
    db.add(version)
    db.flush()
    folder_file.current_version_id = version.id
    db.commit()
    headers = _admin(client)
    created = client.post(
        "/documents/download-jobs", json={"fileIds": [folder_file.id]}, headers=headers
    )
    served = None
    if created.status_code == 201:
        served = client.get(
            f"/documents/download-jobs/{created.json()['id']}/content",
            headers=headers, follow_redirects=False,
        )
    return created, served


def _zip_members(bucket: MirrorClient) -> Dict[str, bytes]:
    members: Dict[str, bytes] = {}
    for key, body in bucket.objects.items():
        if key.startswith("downloads/"):
            with zipfile.ZipFile(io.BytesIO(body)) as zf:
                for name in zf.namelist():
                    members[name] = zf.read(name)
    return members


def test_download_job_zip_does_not_contain_a_file_url_target(
    client, session_factory, bucket, canary_dir, net
):
    """R3: stored `file:` CDN value + the document ZIP job. The ZIP is generated
    through the stub bucket; its members and every response are inspected."""
    db = session_factory()
    conn = _connect(db, _file_uri(canary_dir))
    created, served = _zip_job(client, db, conn)
    assert created.status_code == 201, created.text
    seen = _everything_returned(created) + _everything_returned(served)
    assert CANARY_BYTES not in seen
    for name, data in _zip_members(bucket).items():
        assert CANARY_BYTES not in data, f"zip member {name} carries the target bytes"
    db.close()


def test_download_job_zip_contains_the_file_from_a_public_https_cdn(
    client, session_factory, bucket, net
):
    """Control for the route above: with a public https CDN the ZIP carries the file."""
    net.start(tls=True)
    db = session_factory()
    conn = _connect(db, "https://cdn.storage.test")
    created, _served = _zip_job(client, db, conn)
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "ready"
    assert _zip_members(bucket) == {"doc.txt": CANARY_BYTES}
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# R1  saving a connection
# ═══════════════════════════════════════════════════════════════════════════

BAD_SAVE_VALUES = [
    "http://cdn.storage.test",
    "ftp://cdn.storage.test/files",
    "file:///tmp/objects",
    "data:text/plain,hello",
    "cdn.storage.test",
    " http://cdn.storage.test",
    "HTTP://cdn.storage.test",
    "https://127.0.0.1:9000",
    "https://10.0.0.5",
    "https://169.254.169.254",
    "https://localhost",
    "https://internal.storage.test",
    "https://meta.storage.test",
]


def _storage_rows(session_factory) -> List[Connection]:
    db = session_factory()
    try:
        return (
            db.query(Connection)
            .filter(Connection.tenant_id == DEFAULT_TENANT_ID, Connection.type == "storage")
            .all()
        )
    finally:
        db.close()


def _payload(base: dict, **config) -> dict:
    return {**base, "config": {**base["config"], **config}}


@pytest.mark.parametrize("field", ["cdnBaseUrl", "endpointUrl"])
@pytest.mark.parametrize("value", BAD_SAVE_VALUES)
def test_saving_a_storage_connection_requires_a_public_https_url(
    field, value, client, session_factory, net
):
    headers = _admin(client)
    res = client.post(
        "/integrations/connections", json=_payload(S3_PAYLOAD, **{field: value}), headers=headers
    )
    assert res.status_code == 422, res.text
    assert isinstance(res.json()["detail"], (str, list))
    assert _storage_rows(session_factory) == []


@pytest.mark.parametrize("value", BAD_SAVE_VALUES)
def test_saving_an_r2_connection_requires_a_public_https_cdn_url(
    value, client, session_factory, net
):
    headers = _admin(client)
    res = client.post(
        "/integrations/connections", json=_payload(R2_PAYLOAD, cdnBaseUrl=value), headers=headers
    )
    assert res.status_code == 422, res.text
    assert _storage_rows(session_factory) == []


@pytest.mark.parametrize("field", ["cdnBaseUrl", "endpointUrl"])
@pytest.mark.parametrize("value", BAD_SAVE_VALUES)
def test_updating_a_storage_connection_requires_a_public_https_url(
    field, value, client, session_factory, net
):
    headers = _admin(client)
    created = client.post(
        "/integrations/connections",
        json=_payload(S3_PAYLOAD, cdnBaseUrl="https://cdn.storage.test"),
        headers=headers,
    )
    assert created.status_code == 201, created.text
    res = client.patch(
        f"/integrations/connections/{created.json()['id']}",
        json={"config": {field: value}},
        headers=headers,
    )
    assert res.status_code == 422, res.text
    rows = _storage_rows(session_factory)
    assert len(rows) == 1
    assert rows[0].config_json.get("cdnBaseUrl") == "https://cdn.storage.test"
    assert rows[0].config_json.get(field, "") in ("", "https://cdn.storage.test")


@pytest.mark.parametrize("field", ["cdnBaseUrl", "endpointUrl"])
def test_an_empty_storage_url_is_allowed(field, client, session_factory, net):
    headers = _admin(client)
    res = client.post(
        "/integrations/connections", json=_payload(S3_PAYLOAD, **{field: ""}), headers=headers
    )
    assert res.status_code == 201, res.text
    patched = client.patch(
        f"/integrations/connections/{res.json()['id']}",
        json={"config": {field: ""}},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text


@pytest.mark.parametrize("field", ["cdnBaseUrl", "endpointUrl"])
def test_a_public_https_storage_url_is_saved(field, client, session_factory, net):
    headers = _admin(client)
    res = client.post(
        "/integrations/connections",
        json=_payload(S3_PAYLOAD, **{field: "https://cdn.storage.test"}),
        headers=headers,
    )
    assert res.status_code == 201, res.text
    assert res.json()["config"][field] == "https://cdn.storage.test"
    patched = client.patch(
        f"/integrations/connections/{res.json()['id']}",
        json={"config": {field: "https://other.storage.test"}},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text


# ═══════════════════════════════════════════════════════════════════════════
# omnichannel outbound media read (`send_runner._read_media`)
# ═══════════════════════════════════════════════════════════════════════════


def read_media(db, conn, raw="obj.bin"):
    """Returns (Outcome, exception or None)."""
    from modules.omnichannel.services.send_runner import _read_media

    try:
        return Outcome(True, _read_media(db, DEFAULT_TENANT_ID, f"conn:{conn.id}:{raw}")), None
    except Exception as exc:  # noqa: BLE001 - the shape of the failure is asserted by the callers
        return Outcome(False), exc


def _media_refused(target, net, bucket, canary_dir, db):
    cdn = TARGETS[target](net, canary_dir, bucket)
    conn = _connect(db, cdn)
    out, exc = read_media(db, conn)
    assert not out.ok, f"media read reported a successful read of {cdn!r}"
    assert isinstance(exc, OSError), f"failure was {exc!r}"
    text = str(exc)
    for forbidden in ("127.0.0.1", "10.0.0.5", "169.254", "storage.test", "localhost", CANARY, str(canary_dir)):
        assert forbidden not in text, f"message {text!r} carries {forbidden!r}"
    assert net.attempts == [], f"media read connected out for {cdn!r}: {net.attempts}"
    if net.listener is not None:
        assert net.listener.connections == 0


MEDIA_TARGETS = list(TARGETS)


@pytest.mark.parametrize("target", MEDIA_TARGETS)
def test_media_reads_refuse_stored_urls_that_are_not_public_https(
    target, net, bucket, canary_dir, session_factory
):
    db = session_factory()
    _media_refused(target, net, bucket, canary_dir, db)
    db.close()


def test_media_read_does_not_follow_a_redirect(net, bucket, session_factory):
    db = session_factory()
    net.start(tls=True, mode="redirect")
    conn = _connect(db, "https://cdn.storage.test")
    out, exc = read_media(db, conn)
    assert not out.ok
    assert net.listener.connections == 1
    db.close()


def test_media_read_carries_a_timeout(net, bucket, session_factory):
    db = session_factory()
    net.start(tls=True)
    conn = _connect(db, "https://cdn.storage.test")
    read_media(db, conn)
    assert net.attempts
    for _host, _port, timeout in net.attempts:
        assert timeout is not None and 0 < timeout <= 60
    db.close()


def test_media_read_from_a_public_https_cdn(net, bucket, session_factory):
    db = session_factory()
    net.start(tls=True)
    out, _ = read_media(db, _connect(db, "https://cdn.storage.test"))
    assert out.ok and out.data == CANARY_BYTES
    db.close()


def test_media_read_from_a_presigned_https_url(net, bucket, session_factory):
    db = session_factory()
    net.start(tls=True)
    out, _ = read_media(db, _connect(db, ""))
    assert out.ok and out.data == CANARY_BYTES
    db.close()


def test_media_read_from_local_storage(tmp_path, monkeypatch, session_factory):
    from app.config import settings
    from modules.omnichannel.services.send_runner import _read_media

    media = tmp_path / "media"
    media.mkdir()
    (media / "local.bin").write_bytes(CANARY_BYTES)
    monkeypatch.setattr(settings, "media_root", str(media))
    db = session_factory()
    assert _read_media(db, DEFAULT_TENANT_ID, "local.bin") == CANARY_BYTES
    db.close()


def test_media_read_from_platform_storage_on_a_private_address(
    net, bucket, monkeypatch, session_factory
):
    db = session_factory()
    net.start(tls=True)
    platform = _seed_platform_storage(db, monkeypatch, "https://internal.storage.test")
    out, _ = read_media(db, platform)
    assert out.ok and out.data == CANARY_BYTES
    db.close()


def test_media_read_reports_the_status_of_a_failed_response(net, bucket, session_factory):
    db = session_factory()
    net.start(tls=True, mode="notfound")
    out, exc = read_media(db, _connect(db, "https://cdn.storage.test"))
    assert not out.ok
    assert str(exc) == "Media read failed with status 404"
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# the address is checked again when the connection is made
# ═══════════════════════════════════════════════════════════════════════════

ANSWER_SEQUENCES = {
    "public_then_private": [PUBLIC_IP, "10.0.0.5"],
    "public_then_link_local": [PUBLIC_IP, "169.254.169.254"],
    "public_then_loopback": [PUBLIC_IP, "127.0.0.1"],
    "failure_then_private": ["FAIL", "10.0.0.5"],
    "failure_then_link_local": ["FAIL", "169.254.169.254"],
}


@pytest.mark.parametrize("sequence", list(ANSWER_SEQUENCES))
def test_read_url_connects_only_to_an_address_that_passed_the_check(sequence, net):
    net.start(tls=True)
    net.sequences["seq.storage.test"] = list(ANSWER_SEQUENCES[sequence])
    with pytest.raises(StorageReadError):
        read_url("https://seq.storage.test/obj.bin", timeout=5)
    assert net.attempts == []
    assert net.listener.connections == 0


def test_read_url_reads_a_name_that_keeps_resolving_to_a_public_address(net):
    net.start(tls=True)
    net.sequences["seq.storage.test"] = [PUBLIC_IP]
    assert read_url("https://seq.storage.test/obj.bin", timeout=5) == CANARY_BYTES


@pytest.mark.parametrize("sequence", list(ANSWER_SEQUENCES))
@pytest.mark.parametrize("reader", list(READERS))
def test_every_storage_read_connects_only_to_an_address_that_passed_the_check(
    reader, sequence, net, bucket, session_factory
):
    db = session_factory()
    listener = net.start(tls=True)
    _mirror_into_listener(bucket, listener)
    net.sequences["seq.storage.test"] = list(ANSWER_SEQUENCES[sequence])
    conn = _connect(db, "https://seq.storage.test")
    out = READERS[reader](db, conn)
    assert not out.ok
    assert CANARY_BYTES not in out.data
    assert net.attempts == []
    db.close()


@pytest.mark.parametrize("sequence", list(ANSWER_SEQUENCES))
def test_media_read_connects_only_to_an_address_that_passed_the_check(
    sequence, net, bucket, session_factory
):
    db = session_factory()
    net.start(tls=True)
    net.sequences["seq.storage.test"] = list(ANSWER_SEQUENCES[sequence])
    out, exc = read_media(db, _connect(db, "https://seq.storage.test"))
    assert not out.ok
    assert net.attempts == []
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# size limits on the read, each on its own
# ═══════════════════════════════════════════════════════════════════════════


def test_read_url_stops_on_a_declared_length_over_the_limit(net):
    """The declared length alone refuses the read: the body never arrives, so a
    read that waited for it would run into the timeout instead."""
    import time

    listener = net.start(tls=True, mode="framed", big_bytes=10 * MIB)
    listener.framing = "stall"
    started = time.monotonic()
    with pytest.raises(StorageReadError):
        read_url("https://cdn.storage.test/obj.bin", timeout=5, max_bytes=1 * MIB)
    assert time.monotonic() - started < 3


@pytest.mark.parametrize("framing", ["none", "chunked"])
def test_read_url_stops_when_a_body_without_a_declared_length_crosses_the_limit(framing, net):
    listener = net.start(tls=True, mode="framed", big_bytes=8 * MIB)
    listener.framing = framing
    with pytest.raises(StorageReadError):
        read_url("https://cdn.storage.test/obj.bin", timeout=10, max_bytes=1 * MIB)


@pytest.mark.parametrize("framing", ["none", "chunked", "exact"])
def test_read_url_returns_a_body_within_the_limit(framing, net):
    listener = net.start(tls=True, mode="framed", big_bytes=512 * 1024)
    listener.framing = framing
    assert len(read_url("https://cdn.storage.test/obj.bin", timeout=10, max_bytes=1 * MIB)) == 512 * 1024


def test_an_import_error_report_read_stops_at_the_import_size_limit(net, bucket, session_factory):
    db = session_factory()
    ImportService(db).set_settings(DEFAULT_TENANT_ID, None, 1)
    listener = net.start(tls=True, mode="big", big_bytes=64 * MIB)
    conn = _connect(db, "https://cdn.storage.test")
    out = read_errors(db, conn)
    assert not out.ok or len(out.data) <= 1 * MIB
    assert listener.bytes_sent < 32 * MIB, f"server sent {listener.bytes_sent} bytes"
    db.close()


def test_an_import_error_report_within_the_limit_is_read(net, bucket, session_factory):
    db = session_factory()
    ImportService(db).set_settings(DEFAULT_TENANT_ID, None, 1)
    net.start(tls=True)
    out = read_errors(db, _connect(db, "https://cdn.storage.test"))
    assert out.ok and out.data == CANARY_BYTES
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# a tenant connection holding a stored bad endpoint
# ═══════════════════════════════════════════════════════════════════════════

BAD_ENDPOINTS = [
    "http://127.0.0.1:9000",
    "https://10.0.0.5",
    "https://internal.storage.test",
    "https://meta.storage.test",
    "ftp://cdn.storage.test",
    "file:///tmp/objects",
]


@pytest.fixture
def client_builds(monkeypatch, bucket):
    """Counts the storage clients that get built (a built client is the first
    step towards any connection to the endpoint)."""
    builds: List[object] = []

    def build(self):
        builds.append(self.endpoint_url)
        return bucket

    monkeypatch.setattr(S3CompatibleAdapter, "_build_client", build)
    return builds


def _with_endpoint(db, conn: Connection, endpoint: str) -> Connection:
    conn.config_json = {**(conn.config_json or {}), "endpointUrl": endpoint}
    conn.updated_at = datetime.now(timezone.utc) + timedelta(seconds=5)
    db.commit()
    db.refresh(conn)
    storage_module.clear_adapter_cache()
    return conn


@pytest.mark.parametrize("endpoint", BAD_ENDPOINTS)
def test_import_preview_fails_cleanly_for_a_connection_with_a_bad_endpoint(
    endpoint, client, session_factory, bucket, client_builds, net
):
    listener = net.start(tls=True)
    listener.objects["/preview.csv"] = f"{CANARY},Email\n1,a@example.com\n".encode()
    db = session_factory()
    conn = _with_endpoint(db, _connect(db, "https://cdn.storage.test"), endpoint)
    job = _new_job(db, file_storage_key=f"conn:{conn.id}:preview.csv")
    try:
        res = client.get(f"/imports/{job.id}/preview", headers=_admin(client))
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"unhandled {type(exc).__name__} from the preview route")
    assert 400 <= res.status_code < 500 or res.status_code == 502, res.text
    assert CANARY not in res.text
    assert client_builds == []
    assert net.attempts == []
    db.close()


@pytest.mark.parametrize("endpoint", BAD_ENDPOINTS)
def test_download_job_fails_cleanly_for_a_connection_with_a_bad_endpoint(
    endpoint, client, session_factory, bucket, client_builds, net
):
    net.start(tls=True)
    db = session_factory()
    conn = _with_endpoint(db, _connect(db, "https://cdn.storage.test"), endpoint)
    try:
        created, served = _zip_job(client, db, conn)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"unhandled {type(exc).__name__} from the download routes")
    assert created.status_code == 201, created.text
    assert served is None or served.status_code < 500
    assert CANARY_BYTES not in _everything_returned(created) + _everything_returned(served)
    assert _zip_members(bucket) == {}
    assert client_builds == []
    assert net.attempts == []
    db.close()


@pytest.fixture
def local_media(monkeypatch, tmp_path):
    from app.config import settings

    media = tmp_path / "local-media"
    media.mkdir()
    monkeypatch.setattr(settings, "media_root", str(media))
    return media


@pytest.mark.parametrize("endpoint", BAD_ENDPOINTS)
def test_an_upload_skips_a_connection_with_a_bad_endpoint_and_uses_local_storage(
    endpoint, session_factory, bucket, client_builds, net, local_media
):
    db = session_factory()
    _with_endpoint(db, _connect(db, "https://cdn.storage.test"), endpoint)
    key = storage_for_tenant(db, DEFAULT_TENANT_ID).save("avatars/u1", b"BYTES", "image/png")
    assert not key.startswith("conn:")
    assert (local_media / key).read_bytes() == b"BYTES"
    assert bucket.objects == {}
    assert client_builds == []
    assert net.attempts == []
    db.close()


@pytest.mark.parametrize("endpoint", BAD_ENDPOINTS)
def test_an_upload_skips_a_connection_with_a_bad_endpoint_and_uses_platform_storage(
    endpoint, session_factory, bucket, client_builds, net, monkeypatch, local_media
):
    db = session_factory()
    platform = _seed_platform_storage(db, monkeypatch, "https://cdn.storage.test")
    _with_endpoint(db, _connect(db, "https://cdn.storage.test"), endpoint)
    key = storage_for_tenant(db, DEFAULT_TENANT_ID).save("avatars/u1", b"BYTES", "image/png")
    assert key.startswith(f"conn:{platform.id}:")
    assert list(bucket.objects.values()) == [b"BYTES"]
    assert endpoint not in [str(b) for b in client_builds]
    assert net.attempts == []
    db.close()


def test_an_upload_uses_a_tenant_connection_with_a_public_endpoint(
    session_factory, bucket, client_builds, net, local_media
):
    db = session_factory()
    conn = _with_endpoint(db, _connect(db, "https://cdn.storage.test"), "https://s3.storage.test")
    key = storage_for_tenant(db, DEFAULT_TENANT_ID).save("avatars/u1", b"BYTES", "image/png")
    assert key.startswith(f"conn:{conn.id}:")
    assert list(bucket.objects.values()) == [b"BYTES"]
    db.close()


# ── the stored endpoint is checked again after the connection is edited ────


def test_a_stored_bad_endpoint_is_checked_when_the_connection_is_used(
    session_factory, bucket, client_builds, net
):
    net.start(tls=True)
    db = session_factory()
    conn = _with_endpoint(db, _connect(db, "https://cdn.storage.test"), "https://10.0.0.5")
    assert not read_blob(db, conn).ok
    assert net.attempts == []
    db.close()


def test_an_edited_endpoint_is_checked_again_after_the_adapter_was_cached(
    session_factory, bucket, client_builds, net
):
    net.start(tls=True)
    db = session_factory()
    conn = _connect(db, "https://cdn.storage.test")
    first = read_blob(db, conn)
    assert first.ok and first.data == CANARY_BYTES  # adapter is now cached
    connects_before = len(net.attempts)
    conn.config_json = {**conn.config_json, "endpointUrl": "https://10.0.0.5"}
    conn.updated_at = datetime.now(timezone.utc) + timedelta(seconds=30)
    db.commit()
    db.refresh(conn)
    second = read_blob(db, conn)
    assert not second.ok
    assert len(net.attempts) == connects_before
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# the Test button
# ═══════════════════════════════════════════════════════════════════════════

TEST_REFUSAL = "The storage URLs must be public https addresses."


@pytest.mark.parametrize(
    "field,value",
    [
        ("endpointUrl", "http://127.0.0.1:9000"),
        ("endpointUrl", "https://10.0.0.5"),
        ("endpointUrl", "https://internal.storage.test"),
        ("endpointUrl", "ftp://cdn.storage.test"),
        ("endpointUrl", " https://cdn.storage.test"),
        ("cdnBaseUrl", "http://127.0.0.1:9000"),
        ("cdnBaseUrl", "https://meta.storage.test"),
        ("cdnBaseUrl", "file:///tmp/objects"),
        ("cdnBaseUrl", " https://cdn.storage.test"),
    ],
)
def test_the_test_button_refuses_a_stored_bad_url_without_building_a_client(
    field, value, client, session_factory, bucket, client_builds, net
):
    net.start(tls=True)
    db = session_factory()
    conn = _connect(db, "https://cdn.storage.test")
    conn.config_json = {**conn.config_json, field: value}
    db.commit()
    storage_module.clear_adapter_cache()
    res = client.post(
        f"/integrations/connections/{conn.id}/test", json={}, headers=_admin(client)
    )
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is False
    assert res.json()["message"] == TEST_REFUSAL
    assert client_builds == []
    assert net.attempts == []
    assert bucket.objects == {}
    db.close()


def test_the_test_button_runs_for_a_public_https_connection(
    client, session_factory, bucket, client_builds, net
):
    listener = net.start(tls=True)
    _mirror_into_listener(bucket, listener)
    db = session_factory()
    conn = _connect(db, "https://cdn.storage.test")
    res = client.post(
        f"/integrations/connections/{conn.id}/test", json={}, headers=_admin(client)
    )
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    assert len(client_builds) == 1
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# saving platform storage (operator-owned) and the R2 account id
# ═══════════════════════════════════════════════════════════════════════════


def _platform_create(db, base: dict, **config):
    from app.schemas.integration import ConnectionCreateRequest
    from app.services.integration_service import IntegrationService

    body = ConnectionCreateRequest(**_payload(base, **config))
    return IntegrationService(db).create(PLATFORM_TENANT_ID, body)


def _storage_rows_for(session_factory, tenant_id):
    db = session_factory()
    try:
        return db.query(Connection).filter(
            Connection.tenant_id == tenant_id, Connection.type == "storage"
        ).all()
    finally:
        db.close()


@pytest.mark.parametrize("field", ["cdnBaseUrl", "endpointUrl"])
@pytest.mark.parametrize(
    "value", ["file:///tmp/objects", "ftp://cdn.storage.test", " https://cdn.storage.test", "cdn.storage.test"]
)
def test_platform_storage_refuses_a_value_that_is_not_http_or_https(field, value, session_factory):
    from fastapi import HTTPException

    db = session_factory()
    with pytest.raises(HTTPException) as caught:
        _platform_create(db, S3_PAYLOAD, **{field: value})
    assert caught.value.status_code == 422
    db.close()
    assert _storage_rows_for(session_factory, PLATFORM_TENANT_ID) == []


@pytest.mark.parametrize("field", ["cdnBaseUrl", "endpointUrl"])
@pytest.mark.parametrize(
    "value", ["http://cdn.storage.test", "https://10.0.0.5", "http://127.0.0.1:9000", "https://internal.storage.test"]
)
def test_platform_storage_accepts_http_and_private_addresses(field, value, session_factory):
    db = session_factory()
    created = _platform_create(db, S3_PAYLOAD, **{field: value})
    assert created.config[field] == value
    db.close()


BAD_ACCOUNT_IDS = [
    "x.internal#",
    "user@host",
    "acct.example.com",
    "acct/path",
    "acct:443",
    "acct id",
    "acct?x=1",
    "acct\\host",
    "acct_underscore",
]


@pytest.mark.parametrize("account_id", BAD_ACCOUNT_IDS)
def test_saving_an_r2_connection_requires_a_plain_account_id(
    account_id, client, session_factory, net
):
    res = client.post(
        "/integrations/connections",
        json=_payload(R2_PAYLOAD, accountId=account_id),
        headers=_admin(client),
    )
    assert res.status_code == 422, res.text
    assert _storage_rows(session_factory) == []


@pytest.mark.parametrize("account_id", ["x.internal#", "user@host"])
def test_platform_storage_requires_a_plain_r2_account_id(account_id, session_factory):
    from fastapi import HTTPException

    db = session_factory()
    with pytest.raises(HTTPException) as caught:
        _platform_create(db, R2_PAYLOAD, accountId=account_id)
    assert caught.value.status_code == 422
    db.close()


@pytest.mark.parametrize("account_id", ["abc", "23f8c4ed", "abc-123", "ABC-def-9"])
def test_saving_an_r2_connection_with_a_plain_account_id(account_id, client, session_factory, net):
    res = client.post(
        "/integrations/connections",
        json=_payload(R2_PAYLOAD, accountId=account_id),
        headers=_admin(client),
    )
    assert res.status_code == 201, res.text


# ═══════════════════════════════════════════════════════════════════════════
# encodings and per-reader size limits
# ═══════════════════════════════════════════════════════════════════════════

ALL_READERS = [*READERS, "media_read"]


def run_any(name, db, conn) -> Outcome:
    if name == "media_read":
        return read_media(db, conn)[0]
    return READERS[name](db, conn)


def test_read_url_asks_for_the_identity_encoding(net):
    listener = net.start(tls=True)
    assert read_url("https://cdn.storage.test/obj.bin", timeout=5) == CANARY_BYTES
    assert any("accept-encoding: identity" in h for h in listener.request_headers), (
        listener.request_headers
    )


@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
def test_read_url_refuses_an_encoded_response(encoding, net):
    listener = net.start(tls=True, mode="compressed")
    listener.encoding = encoding
    with pytest.raises(StorageReadError):
        read_url("https://cdn.storage.test/obj.bin", timeout=5)
    assert any("accept-encoding: identity" in h for h in listener.request_headers)


@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
@pytest.mark.parametrize("reader", ALL_READERS)
def test_every_storage_read_refuses_an_encoded_response(reader, encoding, net, bucket, session_factory):
    db = session_factory()
    listener = net.start(tls=True, mode="compressed")
    listener.encoding = encoding
    _mirror_into_listener(bucket, listener)
    out = run_any(reader, db, _connect(db, "https://cdn.storage.test"))
    assert not out.ok
    assert out.data == b""
    assert any("accept-encoding: identity" in h for h in listener.request_headers)
    db.close()


def test_a_response_labelled_identity_is_read(net):
    listener = net.start(tls=True)
    listener.extra_headers = b"Content-Encoding: identity\r\n"
    assert read_url("https://cdn.storage.test/obj.bin", timeout=5) == CANARY_BYTES


DECLARED_OVER_LIMIT = {
    "document_blob": 201 * MIB,  # READ_CAP_BYTES is 200 MiB
    "media_read": 101 * MIB,  # the largest META_CEILINGS entry is 100 MiB
    "connection_probe": 16 * MIB,  # the probe object is tiny
}


@pytest.mark.parametrize("reader", list(DECLARED_OVER_LIMIT))
def test_a_declared_length_over_the_reader_limit_is_refused_at_once(reader, net, bucket, session_factory):
    import time

    db = session_factory()
    listener = net.start(tls=True, mode="framed", big_bytes=DECLARED_OVER_LIMIT[reader])
    listener.framing = "stall"
    conn = _connect(db, "https://cdn.storage.test")
    started = time.monotonic()
    out = run_any(reader, db, conn)
    assert not out.ok
    assert time.monotonic() - started < 5
    db.close()


def test_the_probe_stops_reading_a_body_without_a_declared_length(net, bucket, session_factory):
    db = session_factory()
    listener = net.start(tls=True, mode="framed", big_bytes=16 * MIB)
    listener.framing = "none"
    out = read_probe(db, _connect(db, "https://cdn.storage.test"))
    assert not out.ok
    assert listener.bytes_sent < 12 * MIB, f"server sent {listener.bytes_sent} bytes"
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# URL forms that parsers read differently
# ═══════════════════════════════════════════════════════════════════════════

AMBIGUOUS_URLS = [
    "https://127.0.0.1:9000\\@cdn.storage.test/",
    "https://cdn.storage.test\\@127.0.0.1/",
    "https://user@cdn.storage.test/",
    "https://cdn.storage.test\\x/",
    "https://[bad",
    "https://[::1",
]


def _call(fn, label):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"unhandled {type(exc).__name__} from {label}")


@pytest.mark.parametrize("field", ["cdnBaseUrl", "endpointUrl"])
@pytest.mark.parametrize("value", AMBIGUOUS_URLS)
def test_saving_a_storage_connection_refuses_an_ambiguous_url(field, value, client, session_factory, net):
    res = _call(
        lambda: client.post(
            "/integrations/connections",
            json=_payload(S3_PAYLOAD, **{field: value}),
            headers=_admin(client),
        ),
        "the save route",
    )
    assert res.status_code == 422, res.text
    assert _storage_rows(session_factory) == []


@pytest.mark.parametrize("field", ["cdnBaseUrl", "endpointUrl"])
@pytest.mark.parametrize("value", AMBIGUOUS_URLS)
def test_updating_a_storage_connection_refuses_an_ambiguous_url(field, value, client, session_factory, net):
    headers = _admin(client)
    created = client.post(
        "/integrations/connections",
        json=_payload(S3_PAYLOAD, cdnBaseUrl="https://cdn.storage.test"),
        headers=headers,
    )
    assert created.status_code == 201, created.text
    res = _call(
        lambda: client.patch(
            f"/integrations/connections/{created.json()['id']}",
            json={"config": {field: value}},
            headers=headers,
        ),
        "the update route",
    )
    assert res.status_code == 422, res.text
    rows = _storage_rows(session_factory)
    assert rows[0].config_json.get(field, "") in ("", "https://cdn.storage.test")


@pytest.mark.parametrize("field", ["cdnBaseUrl", "endpointUrl"])
@pytest.mark.parametrize("value", AMBIGUOUS_URLS)
def test_the_test_button_refuses_an_ambiguous_url(
    field, value, client, session_factory, bucket, client_builds, net
):
    net.start(tls=True)
    db = session_factory()
    conn = _connect(db, "https://cdn.storage.test")
    conn.config_json = {**conn.config_json, field: value}
    db.commit()
    storage_module.clear_adapter_cache()
    res = _call(
        lambda: client.post(
            f"/integrations/connections/{conn.id}/test", json={}, headers=_admin(client)
        ),
        "the test route",
    )
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is False
    assert res.json()["message"] == TEST_REFUSAL
    assert client_builds == []
    assert net.attempts == []
    db.close()


@pytest.mark.parametrize("value", AMBIGUOUS_URLS)
def test_an_ambiguous_endpoint_is_not_usable(value):
    from app.services.storage import endpoint_is_usable

    assert endpoint_is_usable("s3", {"endpointUrl": value}) is False


@pytest.mark.parametrize("account_id", ["x.internal#", "user@host", "acct\\host", "x.internal/", "a b"])
def test_an_r2_account_id_with_other_characters_is_not_usable(account_id):
    from app.services.storage import endpoint_is_usable

    assert endpoint_is_usable("r2", {"accountId": account_id}) is False


@pytest.mark.parametrize("value", AMBIGUOUS_URLS)
def test_a_stored_ambiguous_endpoint_is_not_used(value, session_factory, bucket, client_builds, net):
    net.start(tls=True)
    db = session_factory()
    conn = _with_endpoint(db, _connect(db, "https://cdn.storage.test"), value)
    assert not read_blob(db, conn).ok
    assert client_builds == []
    assert net.attempts == []
    db.close()


@pytest.mark.parametrize("value", AMBIGUOUS_URLS)
def test_a_stored_ambiguous_cdn_url_is_not_read(value, session_factory, bucket, net):
    net.start(tls=True)
    db = session_factory()
    out = read_blob(db, _connect(db, value))
    assert not out.ok
    assert net.attempts == []
    db.close()


@pytest.mark.parametrize("account_id", ["x.internal#", "user@host", "acct\\host"])
def test_a_stored_r2_account_id_with_other_characters_is_not_used(
    account_id, session_factory, bucket, client_builds, net
):
    net.start(tls=True)
    db = session_factory()
    conn = _storage_connection(db, DEFAULT_TENANT_ID, cdn="https://cdn.storage.test", provider="r2")
    conn.config_json = {**conn.config_json, "accountId": account_id}
    conn.updated_at = datetime.now(timezone.utc) + timedelta(seconds=5)
    db.commit()
    storage_module.clear_adapter_cache()
    assert not read_blob(db, conn).ok
    assert client_builds == []
    assert net.attempts == []
    db.close()


@pytest.mark.parametrize("field", ["cdnBaseUrl", "endpointUrl"])
@pytest.mark.parametrize("value", ["https://[bad", "https://[::1"])
def test_platform_storage_refuses_an_unparseable_url(field, value, session_factory):
    from fastapi import HTTPException

    db = session_factory()
    with pytest.raises(HTTPException) as caught:
        _platform_create(db, S3_PAYLOAD, **{field: value})
    assert caught.value.status_code == 422
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# the storage migration wizard
# ═══════════════════════════════════════════════════════════════════════════

MIGRATION_BAD_VALUES = [
    ("endpointUrl", "http://cdn.storage.test"),
    ("endpointUrl", "https://10.0.0.5"),
    ("endpointUrl", "https://user@cdn.storage.test/"),
    ("endpointUrl", "https://[bad"),
    ("cdnBaseUrl", "http://127.0.0.1:9000"),
    ("cdnBaseUrl", "file:///tmp/objects"),
    ("cdnBaseUrl", "https://meta.storage.test"),
    ("cdnBaseUrl", "https://cdn.storage.test\\@127.0.0.1/"),
]


def _migration_body(**config) -> dict:
    from tests.test_storage_migration import _NEW_BUCKET

    return {**_NEW_BUCKET, "config": {**_NEW_BUCKET["config"], **config}}


def _platform_headers(client):
    from tests.conftest import PLATFORM_EMAIL, PLATFORM_PASSWORD

    res = client.post(
        "/auth/login",
        json={"email": PLATFORM_EMAIL, "password": PLATFORM_PASSWORD, "tenantSlug": "platform"},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _refused(res) -> bool:
    return 400 <= res.status_code < 500 or (res.status_code == 200 and res.json().get("ok") is False)


@pytest.mark.parametrize("field,value", MIGRATION_BAD_VALUES)
def test_the_migration_test_step_refuses_a_bad_url(
    field, value, client, session_factory, bucket, client_builds, net
):
    net.start(tls=True)
    res = _call(
        lambda: client.post(
            "/storage/migrations/test", json=_migration_body(**{field: value}), headers=_admin(client)
        ),
        "the migration test route",
    )
    assert _refused(res), res.text
    assert client_builds == []
    assert net.attempts == []


@pytest.mark.parametrize("field,value", MIGRATION_BAD_VALUES)
def test_starting_a_migration_with_a_bad_url_stores_nothing_and_keeps_the_connection(
    field, value, client, session_factory, bucket, client_builds, net
):
    from app.models.background_job import BackgroundJob

    net.start(tls=True)
    db = session_factory()
    current = _connect(db, "https://cdn.storage.test")
    current_id = current.id
    res = _call(
        lambda: client.post(
            "/storage/migrations", json=_migration_body(**{field: value}), headers=_admin(client)
        ),
        "the migration start route",
    )
    assert 400 <= res.status_code < 500, res.text
    db.expire_all()
    rows = _storage_rows(session_factory)
    assert [r.id for r in rows] == [current_id]
    assert rows[0].is_active
    check = session_factory()
    assert check.query(BackgroundJob).filter(BackgroundJob.tenant_id == DEFAULT_TENANT_ID).count() == 0
    check.close()
    assert client_builds == []
    assert net.attempts == []
    db.close()


def test_the_migration_test_step_accepts_a_public_https_bucket(
    client, session_factory, bucket, client_builds, net
):
    listener = net.start(tls=True)
    _mirror_into_listener(bucket, listener)
    res = client.post(
        "/storage/migrations/test",
        json=_migration_body(cdnBaseUrl="https://cdn.storage.test"),
        headers=_admin(client),
    )
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True


def test_the_platform_migration_test_step_accepts_a_private_cdn_and_an_http_endpoint(
    client, session_factory, bucket, client_builds, net
):
    listener = net.start(tls=True)
    _mirror_into_listener(bucket, listener)
    res = client.post(
        "/storage/migrations/test",
        json=_migration_body(
            cdnBaseUrl="https://internal.storage.test", endpointUrl="http://127.0.0.1:9000"
        ),
        headers=_platform_headers(client),
    )
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True, res.text
    assert client_builds == ["http://127.0.0.1:9000"]


def test_the_platform_migration_stores_a_private_cdn_and_an_http_endpoint(
    client, session_factory, bucket, client_builds, net, monkeypatch
):
    listener = net.start(tls=True)
    _mirror_into_listener(bucket, listener)
    db = session_factory()
    _seed_platform_storage(db, monkeypatch, "https://cdn.storage.test")
    res = client.post(
        "/storage/migrations",
        json=_migration_body(
            cdnBaseUrl="https://internal.storage.test", endpointUrl="http://127.0.0.1:9000"
        ),
        headers=_platform_headers(client),
    )
    assert res.status_code == 201, res.text
    stored = [
        r for r in _storage_rows_for(session_factory, PLATFORM_TENANT_ID) if r.is_active
    ]
    assert [r.config_json.get("endpointUrl") for r in stored] == ["http://127.0.0.1:9000"]
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# meetings: where the bot container writes
# ═══════════════════════════════════════════════════════════════════════════


def _meeting():
    from types import SimpleNamespace

    return SimpleNamespace(tenant_id=DEFAULT_TENANT_ID, id="meeting-1")


MEETING_BAD_ENDPOINTS = [*BAD_ENDPOINTS, "https://user@cdn.storage.test/", "https://cdn.storage.test\\@127.0.0.1/"]


@pytest.mark.parametrize("endpoint", MEETING_BAD_ENDPOINTS)
def test_a_meeting_does_not_use_a_connection_with_a_bad_endpoint_and_writes_locally(
    endpoint, session_factory, bucket, local_media, net
):
    from modules.meetings.services.bot_runner import build_output

    db = session_factory()
    _with_endpoint(db, _connect(db, "https://cdn.storage.test"), endpoint)
    env, volumes, _artifacts = build_output(db, _meeting())
    assert env == {"BOT_OUT": "/out"}
    assert len(volumes) == 1
    assert endpoint not in repr(env)
    db.close()


@pytest.mark.parametrize("endpoint", MEETING_BAD_ENDPOINTS)
def test_a_meeting_falls_back_to_platform_storage_when_the_endpoint_is_bad(
    endpoint, session_factory, bucket, local_media, monkeypatch, net
):
    from modules.meetings.services.bot_runner import build_output

    db = session_factory()
    _seed_platform_storage(db, monkeypatch, "https://cdn.storage.test")
    _with_endpoint(db, _connect(db, "https://cdn.storage.test"), endpoint)
    env, volumes, _artifacts = build_output(db, _meeting())
    assert env["BOT_OUT"].startswith("s3://platform-assets/")
    assert env["BOT_S3_ENDPOINT"] == "https://acct1.r2.cloudflarestorage.com"
    assert endpoint not in repr(env)
    assert volumes == {}
    db.close()


def test_a_meeting_uses_a_tenant_connection_with_a_public_endpoint(session_factory, bucket, local_media):
    from modules.meetings.services.bot_runner import build_output

    db = session_factory()
    _with_endpoint(db, _connect(db, "https://cdn.storage.test"), "https://s3.storage.test")
    env, volumes, _artifacts = build_output(db, _meeting())
    assert env["BOT_OUT"].startswith("s3://assets/")
    assert env["BOT_S3_ENDPOINT"] == "https://s3.storage.test"
    assert volumes == {}
    db.close()


def test_a_meeting_uses_the_platform_connection_with_a_private_endpoint(session_factory, bucket, local_media):
    from modules.meetings.services.bot_runner import build_output

    db = session_factory()
    _with_endpoint(
        db, _connect(db, "https://cdn.storage.test", PLATFORM_TENANT_ID), "http://10.0.0.5:9000"
    )
    env, _volumes, _artifacts = build_output(db, _meeting())
    assert env["BOT_S3_ENDPOINT"] == "http://10.0.0.5:9000"
    db.close()


def test_a_meeting_without_storage_writes_locally(session_factory, local_media):
    from modules.meetings.services.bot_runner import build_output

    db = session_factory()
    env, volumes, _artifacts = build_output(db, _meeting())
    assert env == {"BOT_OUT": "/out"}
    assert len(volumes) == 1
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# the host of a storage URL is plain
# ═══════════════════════════════════════════════════════════════════════════

HOST_FORMS = {
    "percent_digits": "https://%31%32%37.0.0.1:9000",
    "percent_dots": "https://127%2e0%2e0%2e1:9000",
    "percent_localhost": "https://%6c%6f%63%61%6c%68%6f%73%74",
    "only_a_dot": "https://.",
    "empty_label": "https://a..b",
    "long_label": "https://" + "a" * 70 + ".storage.test",
    "delete_character": "https://cdn\x7f.storage.test",
    "fullwidth_digits": "https://１２７.0.0.1",
    "non_ascii_name": "https://cdn.storagé.test",
    "bracketed_version_form": "https://[v1.127.0.0.1]:9000",
    "open_bracket": "https://[::1",
    "octal_first_label": "https://0177.0.0.1",
    "single_number": "https://2130706433",
    "hex_first_label": "https://0x7f.0.0.1",
    "short_dotted": "https://127.1",
}
GOOD_HOSTS = {
    "name": "https://cdn.storage.test",
    "name_with_port": "https://other.storage.test:8443",
    "public_ipv4": "https://93.184.216.34",
    "public_ipv6": "https://[2606:2800:220:1:248:1893:25c8:1946]",
}


@pytest.mark.parametrize("field", ["cdnBaseUrl", "endpointUrl"])
@pytest.mark.parametrize("form", list(HOST_FORMS))
def test_saving_a_storage_connection_refuses_a_host_that_is_not_plain(
    field, form, client, session_factory, net
):
    res = _call(
        lambda: client.post(
            "/integrations/connections",
            json=_payload(S3_PAYLOAD, **{field: HOST_FORMS[form]}),
            headers=_admin(client),
        ),
        "the save route",
    )
    assert res.status_code == 422, res.text
    assert _storage_rows(session_factory) == []


@pytest.mark.parametrize("field", ["cdnBaseUrl", "endpointUrl"])
@pytest.mark.parametrize("form", list(HOST_FORMS))
def test_updating_a_storage_connection_refuses_a_host_that_is_not_plain(
    field, form, client, session_factory, net
):
    headers = _admin(client)
    created = client.post(
        "/integrations/connections",
        json=_payload(S3_PAYLOAD, cdnBaseUrl="https://cdn.storage.test"),
        headers=headers,
    )
    assert created.status_code == 201, created.text
    res = _call(
        lambda: client.patch(
            f"/integrations/connections/{created.json()['id']}",
            json={"config": {field: HOST_FORMS[form]}},
            headers=headers,
        ),
        "the update route",
    )
    assert res.status_code == 422, res.text


@pytest.mark.parametrize("field", ["cdnBaseUrl", "endpointUrl"])
@pytest.mark.parametrize("form", list(HOST_FORMS))
def test_the_test_button_refuses_a_host_that_is_not_plain(
    field, form, client, session_factory, bucket, client_builds, net
):
    net.start(tls=True)
    db = session_factory()
    conn = _connect(db, "https://cdn.storage.test")
    conn.config_json = {**conn.config_json, field: HOST_FORMS[form]}
    db.commit()
    storage_module.clear_adapter_cache()
    res = _call(
        lambda: client.post(
            f"/integrations/connections/{conn.id}/test", json={}, headers=_admin(client)
        ),
        "the test route",
    )
    assert res.json()["ok"] is False
    assert res.json()["message"] == TEST_REFUSAL
    assert client_builds == []
    assert net.attempts == []
    db.close()


@pytest.mark.parametrize("form", list(HOST_FORMS))
def test_a_host_that_is_not_plain_is_not_a_usable_endpoint(form):
    from app.services.storage import endpoint_is_usable

    assert endpoint_is_usable("s3", {"endpointUrl": HOST_FORMS[form]}) is False


@pytest.mark.parametrize("form", list(HOST_FORMS))
def test_a_stored_endpoint_with_a_host_that_is_not_plain_is_not_used(
    form, session_factory, bucket, client_builds, net
):
    net.start(tls=True)
    db = session_factory()
    conn = _with_endpoint(db, _connect(db, "https://cdn.storage.test"), HOST_FORMS[form])
    assert not read_blob(db, conn).ok
    assert client_builds == []
    assert net.attempts == []
    db.close()


@pytest.mark.parametrize("form", list(HOST_FORMS))
def test_a_stored_cdn_with_a_host_that_is_not_plain_is_not_read(form, session_factory, bucket, net):
    net.start(tls=True)
    db = session_factory()
    assert not read_blob(db, _connect(db, HOST_FORMS[form])).ok
    assert net.attempts == []
    db.close()


@pytest.mark.parametrize("form", list(HOST_FORMS))
def test_read_url_refuses_a_host_that_is_not_plain(form, net):
    net.start(tls=True)
    with pytest.raises(StorageReadError):
        read_url(HOST_FORMS[form] + "/obj.bin", timeout=5)
    assert net.attempts == []


@pytest.mark.parametrize("form", list(HOST_FORMS))
def test_a_meeting_does_not_receive_an_endpoint_with_a_host_that_is_not_plain(
    form, session_factory, bucket, local_media, net
):
    from modules.meetings.services.bot_runner import build_output

    db = session_factory()
    _with_endpoint(db, _connect(db, "https://cdn.storage.test"), HOST_FORMS[form])
    env, _volumes, _artifacts = build_output(db, _meeting())
    assert "BOT_S3_ENDPOINT" not in env
    db.close()


@pytest.mark.parametrize("field", ["cdnBaseUrl", "endpointUrl"])
@pytest.mark.parametrize("form", list(GOOD_HOSTS))
def test_a_plain_public_host_is_saved(field, form, client, session_factory, net):
    res = client.post(
        "/integrations/connections",
        json=_payload(S3_PAYLOAD, **{field: GOOD_HOSTS[form]}),
        headers=_admin(client),
    )
    assert res.status_code == 201, res.text


@pytest.mark.parametrize("form", list(GOOD_HOSTS))
def test_a_plain_public_host_is_a_usable_endpoint(form):
    from app.services.storage import endpoint_is_usable

    assert endpoint_is_usable("s3", {"endpointUrl": GOOD_HOSTS[form]}) is True


def test_a_cdn_base_with_a_percent_sign_in_its_path_is_saved(client, session_factory, net):
    res = client.post(
        "/integrations/connections",
        json=_payload(S3_PAYLOAD, cdnBaseUrl="https://cdn.storage.test/base%20dir"),
        headers=_admin(client),
    )
    assert res.status_code == 201, res.text


# ═══════════════════════════════════════════════════════════════════════════
# a client library that rejects a stored endpoint
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def rejecting_client(monkeypatch):
    def build(self):
        raise ValueError("Invalid endpoint: rejected by the client library")

    monkeypatch.setattr(S3CompatibleAdapter, "_build_client", build)
    storage_module.clear_adapter_cache()


def _presigned_connection(db):
    conn = _connect(db, "")
    return _with_endpoint(db, conn, "https://s3.storage.test")


def test_import_preview_fails_cleanly_when_the_client_library_rejects_the_endpoint(
    client, session_factory, rejecting_client, net
):
    db = session_factory()
    conn = _presigned_connection(db)
    job = _new_job(db, file_storage_key=f"conn:{conn.id}:preview.csv")
    res = _call(
        lambda: client.get(f"/imports/{job.id}/preview", headers=_admin(client)), "the preview route"
    )
    assert 400 <= res.status_code < 500 or res.status_code == 502, res.text
    db.close()


def test_import_error_file_fails_cleanly_when_the_client_library_rejects_the_endpoint(
    client, session_factory, rejecting_client, net
):
    db = session_factory()
    conn = _presigned_connection(db)
    job = _new_job(db, error_report_key=f"conn:{conn.id}:errors.csv")
    res = _call(
        lambda: client.get(f"/imports/{job.id}/errors-file", headers=_admin(client)),
        "the error file route",
    )
    assert 400 <= res.status_code < 500 or res.status_code == 502, res.text
    db.close()


def test_an_upload_does_not_fail_when_the_client_library_rejects_the_endpoint(
    session_factory, rejecting_client, net, local_media
):
    db = session_factory()
    _presigned_connection(db)
    key = _call(
        lambda: storage_for_tenant(db, DEFAULT_TENANT_ID).save("avatars/u1", b"BYTES", "image/png"),
        "the upload",
    )
    assert isinstance(key, str) and key
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# migrating away from a connection that holds a bad URL
# ═══════════════════════════════════════════════════════════════════════════

STORED_BAD_ON_CURRENT = ["https://10.0.0.5", "http://127.0.0.1:9000", "https://%31%32%37.0.0.1:9000"]


@pytest.mark.parametrize("endpoint", STORED_BAD_ON_CURRENT)
def test_a_migration_from_a_connection_with_a_bad_url_is_refused_and_keeps_it(
    endpoint, client, session_factory, bucket, client_builds, net
):
    from app.models.background_job import BackgroundJob

    listener = net.start(tls=True)
    _mirror_into_listener(bucket, listener)
    db = session_factory()
    current = _with_endpoint(db, _connect(db, "https://cdn.storage.test"), endpoint)
    current_id = current.id
    res = _call(
        lambda: client.post(
            "/storage/migrations",
            json=_migration_body(cdnBaseUrl="https://cdn.storage.test"),
            headers=_admin(client),
        ),
        "the migration start route",
    )
    assert 400 <= res.status_code < 500, res.text
    assert current_id not in res.text
    assert isinstance(res.json().get("detail"), str) and res.json()["detail"]
    rows = _storage_rows(session_factory)
    assert [r.id for r in rows] == [current_id]
    assert rows[0].is_active
    check = session_factory()
    assert check.query(BackgroundJob).filter(BackgroundJob.tenant_id == DEFAULT_TENANT_ID).count() == 0
    check.close()
    db.close()


def test_a_migration_job_that_fails_on_a_bad_connection_records_text_without_an_id(
    session_factory, bucket, client_builds, net
):
    from app.jobs.service import run_job
    from app.models.background_job import JOB_FAILED, BackgroundJob
    from app.storage_migration.service import STORAGE_MIGRATION

    db = session_factory()
    old = _with_endpoint(db, _connect(db, "https://cdn.storage.test"), "https://10.0.0.5")
    old.is_active = False
    new = _storage_connection(db, PLATFORM_TENANT_ID, cdn="https://cdn.storage.test")
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID,
        type=STORAGE_MIGRATION,
        status="pending",
        payload_json={"fromConnectionId": old.id, "toConnectionId": new.id},
    )
    db.add(job)
    db.commit()
    finished = run_job(db, job.id)
    assert finished.status == JOB_FAILED
    assert finished.error
    assert old.id not in finished.error
    assert new.id not in finished.error
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# a label that storage clients write
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("reader", [*CONTENT_READERS, "media_read"])
def test_a_stored_object_labelled_aws_chunked_is_read(reader, net, bucket, session_factory):
    db = session_factory()
    listener = net.start(tls=True)
    listener.extra_headers = b"Content-Encoding: aws-chunked\r\n"
    out = run_any(reader, db, _connect(db, "https://cdn.storage.test"))
    assert out.ok
    assert out.data == CANARY_BYTES
    db.close()


def test_the_probe_round_trips_an_object_labelled_aws_chunked(net, bucket, session_factory):
    db = session_factory()
    listener = net.start(tls=True)
    listener.extra_headers = b"Content-Encoding: aws-chunked\r\n"
    _mirror_into_listener(bucket, listener)
    assert read_probe(db, _connect(db, "https://cdn.storage.test")).ok
    db.close()


def test_read_url_reads_an_object_labelled_aws_chunked(net):
    listener = net.start(tls=True)
    listener.extra_headers = b"Content-Encoding: aws-chunked\r\n"
    assert read_url("https://cdn.storage.test/obj.bin", timeout=5) == CANARY_BYTES


@pytest.mark.parametrize("label", ["aws-chunked, gzip", "gzip, aws-chunked", "br", "compress"])
def test_a_stored_object_with_another_encoding_label_is_still_refused(label, net):
    listener = net.start(tls=True)
    listener.extra_headers = b"Content-Encoding: " + label.encode() + b"\r\n"
    with pytest.raises(StorageReadError):
        read_url("https://cdn.storage.test/obj.bin", timeout=5)
