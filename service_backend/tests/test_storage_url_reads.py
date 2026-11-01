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
import io
import socket
import ssl
import threading
import zipfile
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
from app.services.storage import storage_for_tenant
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
        self.body = CANARY_BYTES
        self.objects: Dict[str, bytes] = {}
        self.requests: List[str] = []
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
            if self.mode == "redirect" and bare != "/landing":
                conn.sendall(
                    b"HTTP/1.1 302 Found\r\nLocation: https://other.storage.test/landing\r\n"
                    b"Content-Length: 0\r\nConnection: close\r\n\r\n"
                )
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
                b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body)
                + body
            )
        except Exception:  # noqa: BLE001 - a client that hangs up mid-send is expected
            pass
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

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


@pytest.mark.parametrize("reader", ["import_content", "import_error_report"])
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

