// Creates the localhost certificate for local HTTPS development. It is signed by
// the mkcert development CA when one is installed, so browsers trust it;
// otherwise it is self-signed and browsers show a warning.
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";

const keyFile = "certs/localhost-key.pem";
const certFile = "certs/localhost.pem";
const force = process.argv.includes("--force");

// Same lookup order as `mkcert -CAROOT`
function mkcertCaRoot() {
  if (process.env.CAROOT) return process.env.CAROOT;
  if (process.platform === "win32") return path.join(process.env.LOCALAPPDATA ?? "", "mkcert");
  if (process.platform === "darwin") return path.join(os.homedir(), "Library/Application Support/mkcert");
  return path.join(process.env.XDG_DATA_HOME ?? path.join(os.homedir(), ".local/share"), "mkcert");
}

if (!force && existsSync(keyFile) && existsSync(certFile)) {
  console.log(`Certificate already exists: ${certFile} (use --force to replace it)`);
  process.exit(0);
}

const caRoot = mkcertCaRoot();
const caCert = path.join(caRoot, "rootCA.pem");
const caKey = path.join(caRoot, "rootCA-key.pem");
const signWithCa = existsSync(caCert) && existsSync(caKey);

const tempDir = mkdtempSync(path.join(os.tmpdir(), "dev-cert-"));
const configFile = path.join(tempDir, "openssl.cnf");
writeFileSync(configFile, `[req]
prompt = no
distinguished_name = dn
x509_extensions = leaf

[dn]
CN = localhost

[leaf]
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature
extendedKeyUsage = serverAuth
subjectAltName = DNS:localhost, IP:127.0.0.1, IP:::1
`);

mkdirSync("certs", { recursive: true });
try {
  execFileSync("openssl", [
    "req", "-x509", "-nodes", "-days", "365",
    "-config", configFile,
    "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
    "-keyout", keyFile,
    "-out", certFile,
    ...(signWithCa ? ["-CA", caCert, "-CAkey", caKey] : []),
  ], { stdio: "inherit" });
} finally {
  rmSync(tempDir, { recursive: true, force: true });
}

if (signWithCa) {
  console.log(`Created ${certFile}, signed by the mkcert development CA in ${caRoot}`);
} else {
  console.log(`Created a self-signed ${certFile}; browsers will warn about it.`);
  console.log(`For a trusted certificate, run "mkcert -install" once, then "npm run cert:dev -- --force".`);
}
