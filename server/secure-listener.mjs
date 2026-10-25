import { createWriteStream, mkdirSync } from "node:fs";
import { createServer as createHttpServer } from "node:http";
import { createServer as createNetServer } from "node:net";
import path from "node:path";
import { createServer as createTlsServer } from "node:tls";

// The only cipher suites TLS 1.3 negotiates by default (RFC 8446 section 9.1)
const ALLOWED_CIPHERS = new Set([
  "TLS_AES_256_GCM_SHA384",
  "TLS_CHACHA20_POLY1305_SHA256",
  "TLS_AES_128_GCM_SHA256",
]);
// Every TLS connection opens with a handshake record (content type 22)
const TLS_HANDSHAKE_RECORD = 0x16;
const CLIENT_HELLO_TIMEOUT_MS = 10_000;

function createSecurityLog(logFile) {
  mkdirSync(path.dirname(logFile), { recursive: true });
  const stream = createWriteStream(logFile, { flags: "a" });
  stream.on("error", (error) => console.error("[tls] Unable to write security log:", error.message));
  return (reason, details) => {
    const entry = { time: new Date().toISOString(), event: "tls.connectionRejected", reason, ...details };
    console.warn(`[tls] Rejected connection from ${details.remoteAddress}: ${reason}`);
    stream.write(`${JSON.stringify(entry)}\n`);
  };
}

/**
 * Accepts TCP connections and passes them to `httpServer` only once a TLS 1.3
 * session with an allowed cipher has been negotiated. Plaintext connections,
 * failed handshakes and older protocol versions are logged and closed before
 * any request data is read.
 */
export function createSecureListener({ key, cert, logFile }) {
  const logRejection = createSecurityLog(logFile);
  const httpServer = createHttpServer();

  // TLS 1.2 is left negotiable so the check below can inspect and log it;
  // OpenSSL itself refuses anything older, which surfaces as a handshake failure
  const tlsServer = createTlsServer({
    key,
    cert,
    minVersion: "TLSv1.2",
    ALPNProtocols: ["http/1.1"],
    handshakeTimeout: CLIENT_HELLO_TIMEOUT_MS,
  });

  tlsServer.on("secureConnection", (tlsSocket) => {
    const protocol = tlsSocket.getProtocol();
    const cipher = tlsSocket.getCipher()?.standardName;
    let reason = null;
    if (protocol !== "TLSv1.3") reason = "protocolBelowTls13";
    else if (!ALLOWED_CIPHERS.has(cipher)) reason = "cipherNotAllowed";
    if (reason) {
      logRejection(reason, {
        remoteAddress: tlsSocket.remoteAddress,
        remotePort: tlsSocket.remotePort,
        protocol,
        cipher,
      });
      tlsSocket.destroy();
      return;
    }
    httpServer.emit("connection", tlsSocket);
  });

  tlsServer.on("tlsClientError", (error, tlsSocket) => {
    logRejection("handshakeFailed", {
      remoteAddress: tlsSocket.remoteAddress,
      remotePort: tlsSocket.remotePort,
      error: error.code ?? error.message,
    });
    tlsSocket.destroy();
  });

  const listener = createNetServer((socket) => {
    const peer = { remoteAddress: socket.remoteAddress, remotePort: socket.remotePort };
    // Resets before the first byte would otherwise crash the process
    socket.on("error", () => {});
    socket.setTimeout(CLIENT_HELLO_TIMEOUT_MS, () => {
      logRejection("noClientHello", peer);
      socket.destroy();
    });
    socket.once("data", (chunk) => {
      socket.setTimeout(0);
      socket.pause();
      if (chunk[0] !== TLS_HANDSHAKE_RECORD) {
        logRejection("notTls", { ...peer, firstByte: `0x${chunk[0].toString(16).padStart(2, "0")}` });
        socket.destroy();
        return;
      }
      // Return the ClientHello to the stream so the TLS server reads it from the start
      socket.unshift(chunk);
      tlsServer.emit("connection", socket);
    });
  });

  return { listener, httpServer };
}
