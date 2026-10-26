import { createWriteStream, mkdirSync, readFileSync } from "node:fs";
import { createServer as createHttpServer } from "node:http";
import { createServer as createNetServer } from "node:net";
import path from "node:path";
import { createServer as createTlsServer } from "node:tls";

// Oldest first, so a negotiated version can be compared with the policy minimum
const TLS_VERSIONS = ["TLSv1", "TLSv1.1", "TLSv1.2", "TLSv1.3"];
// Every TLS connection opens with a handshake record (content type 22)
const TLS_HANDSHAKE_RECORD = 0x16;
const CLIENT_HELLO_TIMEOUT_MS = 10_000;

/**
 * Reads the TLS policy shared with the API listener (tls-policy.json) and
 * checks it. Throws if it is missing or unusable, so the server does not start.
 */
export function loadTlsPolicy(file) {
  const policy = JSON.parse(readFileSync(file, "utf8"));
  if (!TLS_VERSIONS.includes(policy.minimumVersion)) {
    throw new Error(`minimumVersion must be one of ${TLS_VERSIONS.join(", ")}`);
  }
  const ciphers = policy.allowedCiphers;
  if (!Array.isArray(ciphers) || ciphers.length === 0 || !ciphers.every((c) => typeof c === "string")) {
    throw new Error("allowedCiphers must be a non-empty list of cipher names");
  }
  return { minimumVersion: policy.minimumVersion, allowedCiphers: new Set(ciphers) };
}

// Why a negotiated session breaks the policy, or null if it is allowed
function policyViolation(policy, protocol, cipher) {
  if (TLS_VERSIONS.indexOf(protocol) < TLS_VERSIONS.indexOf(policy.minimumVersion)) {
    return "protocolBelowTls13";
  }
  if (!policy.allowedCiphers.has(cipher)) return "cipherNotAllowed";
  return null;
}

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
 * Accepts TCP connections and passes them to `httpServer` only once a session
 * meeting the TLS policy (by default TLS 1.3 with an allowed cipher) has been
 * negotiated. Plaintext connections, failed handshakes and older protocol
 * versions are logged and closed before any request data is read.
 */
export function createSecureListener({ key, cert, logFile, policy }) {
  const logRejection = createSecurityLog(logFile);
  const httpServer = createHttpServer();

  // Versions down to TLS 1.2 are left negotiable so the policy check below can
  // inspect and log them; OpenSSL itself refuses anything older, which surfaces
  // as a handshake failure
  const negotiableFloor =
    TLS_VERSIONS.indexOf(policy.minimumVersion) < TLS_VERSIONS.indexOf("TLSv1.2") ? policy.minimumVersion : "TLSv1.2";
  const tlsServer = createTlsServer({
    key,
    cert,
    minVersion: negotiableFloor,
    ALPNProtocols: ["http/1.1"],
    handshakeTimeout: CLIENT_HELLO_TIMEOUT_MS,
  });

  tlsServer.on("secureConnection", (tlsSocket) => {
    const protocol = tlsSocket.getProtocol();
    const cipher = tlsSocket.getCipher()?.standardName;
    const reason = policyViolation(policy, protocol, cipher);
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
