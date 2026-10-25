import datetime
import ipaddress
import json
import socket
import ssl
import threading
import time

import pytest
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from backend import tls_server


async def hello_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": b"hello"})


def write_certificate(directory):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_file = directory / "cert.pem"
    key_file = directory / "key.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ))
    return cert_file, key_file


@pytest.fixture
def running_server(tmp_path, monkeypatch):
    monkeypatch.setattr(tls_server, "CLIENT_HELLO_TIMEOUT_SECONDS", 0.5)
    cert_file, key_file = write_certificate(tmp_path)
    log_file = tmp_path / "tls.log"
    # Bound but not listening, like the socket uvicorn passes to --reload workers
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(hello_app, lifespan="off", log_level="warning")
    server = tls_server.TlsServer(config, cert_file=str(cert_file), key_file=str(key_file), log_file=str(log_file))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "server did not start"
        time.sleep(0.05)

    def log_entries(expected=1):
        # asyncio closes a failed handshake before the listener logs it
        deadline = time.monotonic() + 2
        entries = []
        while len(entries) < expected and time.monotonic() < deadline:
            time.sleep(0.02)
            if log_file.exists():
                entries = [json.loads(line) for line in log_file.read_text().splitlines()]
        return entries

    yield port, log_entries
    server.should_exit = True
    thread.join(timeout=10)


def client_context(**versions):
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    for attribute, version in versions.items():
        setattr(context, attribute, version)
    return context


def read_all(sock):
    chunks = []
    try:
        while chunk := sock.recv(4096):
            chunks.append(chunk)
    except (ConnectionResetError, ssl.SSLError):
        pass
    return b"".join(chunks)


REQUEST = b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"


def test_tls_1_3_connection_reaches_the_app(running_server):
    port, log_entries = running_server
    context = client_context(minimum_version=ssl.TLSVersion.TLSv1_3)

    with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
        with context.wrap_socket(raw) as tls:
            assert tls.version() == "TLSv1.3"
            tls.sendall(REQUEST)
            response = read_all(tls)

    assert response.startswith(b"HTTP/1.1 200")
    assert b"\r\nhello\r\n" in response
    assert log_entries(expected=0) == []


def test_tls_1_2_connection_is_closed_and_logged(running_server):
    port, log_entries = running_server
    context = client_context(maximum_version=ssl.TLSVersion.TLSv1_2)

    # The server closes as soon as its side of the handshake completes, so the
    # client sees either an EOF during its handshake or a connection with no response
    response = b""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
        try:
            with context.wrap_socket(raw) as tls:
                tls.sendall(REQUEST)
                response = read_all(tls)
        except OSError:
            pass

    assert response == b""
    [entry] = log_entries()
    assert entry["reason"] == "protocolBelowTls13"
    assert entry["protocol"] == "TLSv1.2"
    assert entry["remoteAddress"] == "127.0.0.1"


def test_plaintext_connection_is_closed_and_logged(running_server):
    port, log_entries = running_server

    with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
        raw.sendall(REQUEST)
        response = read_all(raw)

    assert response == b""
    [entry] = log_entries()
    assert entry["reason"] == "notTls"
    assert entry["firstByte"] == "0x47"


def test_idle_connection_is_closed_and_logged(running_server):
    port, log_entries = running_server

    with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
        response = read_all(raw)

    assert response == b""
    [entry] = log_entries()
    assert entry["reason"] == "noClientHello"


def test_failed_handshake_is_logged(running_server):
    port, log_entries = running_server
    # A TLS record header announcing a handshake, followed by garbage
    with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
        raw.sendall(b"\x16\x03\x01\x00\x05hello")
        read_all(raw)

    [entry] = log_entries()
    assert entry["reason"] == "handshakeFailed"
