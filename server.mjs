import { readFileSync } from "node:fs";

import { createSecureListener, loadTlsPolicy } from "./server/secure-listener.mjs";

const dev = !process.argv.includes("--production");
process.env.NODE_ENV = dev ? "development" : "production";

const hostname = process.env.HOST;
const port = Number.parseInt(process.env.PORT ?? "3000", 10);
const certFile = process.env.TLS_CERT_FILE ?? "certs/localhost.pem";
const keyFile = process.env.TLS_KEY_FILE ?? "certs/localhost-key.pem";
const logFile = process.env.TLS_LOG_FILE ?? "logs/tls-security.log";
const policyFile = process.env.TLS_POLICY_FILE ?? "tls-policy.json";

// Shared with the API listener (backend/tls_server.py)
let policy;
try {
  policy = loadTlsPolicy(policyFile);
} catch (error) {
  console.error(`TLS policy could not be loaded from ${policyFile}: ${error.message}`);
  process.exit(1);
}

let key;
let cert;
try {
  key = readFileSync(keyFile);
  cert = readFileSync(certFile);
} catch {
  console.error(`TLS certificate not found (${certFile}, ${keyFile}). Run "npm run cert:dev" first.`);
  process.exit(1);
}

const { listener, httpServer } = createSecureListener({ key, cert, logFile, policy });

// Imported after NODE_ENV is set, which Next.js reads when it loads
const { default: next } = await import("next");
const app = next({ dev, hostname: hostname ?? "localhost", port, httpServer });
const handle = app.getRequestHandler();
await app.prepare();

httpServer.on("request", (req, res) => handle(req, res));
listener.listen(port, hostname, () => {
  console.log(`> Ready on https://${hostname ?? "localhost"}:${port} (TLS 1.3 only, ${process.env.NODE_ENV})`);
});
