"""Runs the API over TLS 1.3 only.

Every connection is checked before FastAPI reads any request data:
plaintext connections, failed handshakes and sessions that negotiate
anything other than TLS 1.3 with an allowed cipher are logged and closed.

    python -m backend.tls_server [--reload] [--env-file backend/.env] [--host 127.0.0.1] [--port 8000]
"""

import argparse
import asyncio
import json
import logging
import socket
import ssl
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from uvicorn._subprocess import get_subprocess
from uvicorn.supervisors import ChangeReload

logger = logging.getLogger("backend.tls")

# The only cipher suites TLS 1.3 negotiates by default (RFC 8446 section 9.1)
ALLOWED_CIPHERS = frozenset({
    "TLS_AES_256_GCM_SHA384",
    "TLS_CHACHA20_POLY1305_SHA256",
    "TLS_AES_128_GCM_SHA256",
})
# Every TLS connection opens with a handshake record (content type 22)
TLS_HANDSHAKE_RECORD = 0x16
CLIENT_HELLO_TIMEOUT_SECONDS = 10
# How long closing a connection waits for the client to confirm; asyncio's
# default of 30 seconds holds up every shutdown and --reload restart
TLS_SHUTDOWN_TIMEOUT_SECONDS = 5


class SecurityLog:
    def __init__(self, log_file: str):
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path

    def rejected(self, reason: str, peer, **details) -> None:
        host, port = (peer[0], peer[1]) if peer else (None, None)
        entry = {
            "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "event": "tls.connectionRejected",
            "reason": reason,
            "remoteAddress": host,
            "remotePort": port,
            **details,
        }
        logger.warning("[tls] Rejected connection from %s: %s", host, reason)
        try:
            with self._path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(entry) + "\n")
        except OSError:
            logger.exception("Unable to write TLS security log")


def create_ssl_context(cert_file: str, key_file: str) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    # TLS 1.2 is left negotiable so the protocol check can inspect and log it;
    # OpenSSL itself refuses anything older, which surfaces as a handshake failure
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert_file, key_file)
    context.set_alpn_protocols(["http/1.1"])
    return context


def tls_checked(protocol_class: type[asyncio.Protocol], security_log: SecurityLog) -> type[asyncio.Protocol]:
    """Wraps uvicorn's HTTP protocol so it only starts on an allowed TLS 1.3 session."""

    class TlsCheckedProtocol(protocol_class):
        _tls_rejected = False

        def connection_made(self, transport):
            ssl_object = transport.get_extra_info("ssl_object")
            protocol = ssl_object.version() if ssl_object else None
            cipher = ssl_object.cipher()[0] if ssl_object else None
            reason = None
            if protocol != "TLSv1.3":
                reason = "protocolBelowTls13"
            elif cipher not in ALLOWED_CIPHERS:
                reason = "cipherNotAllowed"
            if reason:
                self._tls_rejected = True
                security_log.rejected(reason, transport.get_extra_info("peername"), protocol=protocol, cipher=cipher)
                transport.abort()
                return
            super().connection_made(transport)

        def data_received(self, data):
            if not self._tls_rejected:
                super().data_received(data)

        def eof_received(self):
            if not self._tls_rejected:
                return super().eof_received()
            return None

        def connection_lost(self, exc):
            if not self._tls_rejected:
                super().connection_lost(exc)

    return TlsCheckedProtocol


class TlsListener:
    """Accepts connections and admits only TLS ones to the protocol factory."""

    def __init__(self, sock: socket.socket, ssl_context: ssl.SSLContext, protocol_factory, security_log: SecurityLog):
        self._sock = sock
        self._ssl_context = ssl_context
        self._protocol_factory = protocol_factory
        self._security_log = security_log
        # Waiting for a first byte blocks a thread, so idle clients get their own pool
        self._peek_pool = ThreadPoolExecutor(max_workers=64, thread_name_prefix="tls-peek")
        self._handlers: set[asyncio.Task] = set()
        self._accept_task: asyncio.Task | None = None

    def start(self, backlog: int) -> None:
        # Sockets bound by uvicorn for --reload are not listening yet
        self._sock.listen(backlog)
        self._sock.setblocking(False)
        self._accept_task = asyncio.create_task(self._accept_loop())

    def close(self) -> None:
        if self._accept_task:
            self._accept_task.cancel()
        for task in self._handlers:
            task.cancel()
        self._sock.close()
        self._peek_pool.shutdown(wait=False, cancel_futures=True)

    async def wait_closed(self) -> None:
        tasks = [task for task in (self._accept_task, *self._handlers) if task]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _accept_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            conn, peer = await loop.sock_accept(self._sock)
            task = asyncio.create_task(self._admit(conn, peer))
            self._handlers.add(task)
            task.add_done_callback(self._handlers.discard)

    async def _admit(self, conn: socket.socket, peer) -> None:
        loop = asyncio.get_running_loop()
        try:
            first_byte = await loop.run_in_executor(self._peek_pool, _peek_first_byte, conn)
        except TimeoutError:
            self._security_log.rejected("noClientHello", peer)
            conn.close()
            return
        except OSError:
            conn.close()
            return
        if not first_byte:
            conn.close()
            return
        if first_byte[0] != TLS_HANDSHAKE_RECORD:
            self._security_log.rejected("notTls", peer, firstByte=f"0x{first_byte[0]:02x}")
            conn.close()
            return

        conn.setblocking(False)
        try:
            await loop.connect_accepted_socket(
                self._protocol_factory,
                sock=conn,
                ssl=self._ssl_context,
                ssl_handshake_timeout=CLIENT_HELLO_TIMEOUT_SECONDS,
                ssl_shutdown_timeout=TLS_SHUTDOWN_TIMEOUT_SECONDS,
            )
        except asyncio.CancelledError:
            conn.close()
            raise
        except (OSError, TimeoutError) as exc:
            error = getattr(exc, "reason", None) or type(exc).__name__
            self._security_log.rejected("handshakeFailed", peer, error=error)
            conn.close()


def _peek_first_byte(conn: socket.socket) -> bytes:
    # MSG_PEEK leaves the byte in the socket for the TLS handshake to read
    conn.settimeout(CLIENT_HELLO_TIMEOUT_SECONDS)
    return conn.recv(1, socket.MSG_PEEK)


class TlsServer(uvicorn.Server):
    """uvicorn server whose listener is a TlsListener instead of asyncio's."""

    def __init__(self, config: uvicorn.Config, *, cert_file: str, key_file: str, log_file: str):
        super().__init__(config)
        # Kept as paths so the server can be pickled into a --reload worker process
        self._cert_file = cert_file
        self._key_file = key_file
        self._log_file = log_file

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await self.lifespan.startup()
        if self.lifespan.should_exit:
            sys.exit(3)

        config = self.config
        security_log = SecurityLog(self._log_file)
        protocol_class = tls_checked(config.http_protocol_class, security_log)

        def create_protocol():
            return protocol_class(config=config, server_state=self.server_state, app_state=self.lifespan.state)

        if sockets:
            sock = sockets[0]
        else:
            try:
                sock = socket.create_server((config.host, config.port), backlog=config.backlog)
            except OSError as exc:
                logger.error(exc)
                await self.lifespan.shutdown()
                sys.exit(3)
            logger.info("Uvicorn running on https://%s:%d (TLS 1.3 only, press CTRL+C to quit)", config.host, config.port)

        listener = TlsListener(sock, create_ssl_context(self._cert_file, self._key_file), create_protocol, security_log)
        listener.start(config.backlog)
        self.servers = [listener]
        self.started = True


class TerminatingReload(ChangeReload):
    """--reload that restarts the worker reliably on Windows.

    uvicorn restarts a Windows worker by sending it Ctrl+C and waiting for it to
    exit. With Python 3.14 that worker never exits, so the API stops answering
    after the first code change, git pull or checkout. Terminate it instead, as
    uvicorn already does on other platforms. Stopping with Ctrl+C is unchanged.
    """

    def restart(self) -> None:
        if sys.platform != "win32":
            super().restart()
            return
        self.process.terminate()
        self.process.join()
        self.process = get_subprocess(config=self.config, target=self.target, sockets=self.sockets)
        self.process.start()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the API over TLS 1.3 only.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--env-file")
    args = parser.parse_args()

    # Loaded before backend.config reads its settings; --reload workers inherit the environment
    if args.env_file:
        load_dotenv(args.env_file)
    from backend.config import TLS_CERT_FILE, TLS_KEY_FILE, TLS_LOG_FILE

    for path in (TLS_CERT_FILE, TLS_KEY_FILE):
        if not Path(path).is_file():
            sys.exit(f'TLS certificate not found ({path}). Run "npm run cert:dev" first.')

    config = uvicorn.Config(
        "backend.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=["backend"] if args.reload else None,
        # Only so uvicorn reports https:// URLs; the TlsListener does the TLS work
        ssl_certfile=TLS_CERT_FILE,
        ssl_keyfile=TLS_KEY_FILE,
    )
    server = TlsServer(config, cert_file=TLS_CERT_FILE, key_file=TLS_KEY_FILE, log_file=TLS_LOG_FILE)
    if config.should_reload:
        TerminatingReload(config, target=server.run, sockets=[config.bind_socket()]).run()
    else:
        server.run()


if __name__ == "__main__":
    main()
