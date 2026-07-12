import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rawPort = process.argv[2];
const port = Number(rawPort);
if (!rawPort || !/^\d+$/.test(rawPort) || !Number.isInteger(port) || port < 1 || port > 65_535) {
  throw new Error("frontend port must be an integer between 1 and 65535");
}

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const workspaceParent = path.join(frontendRoot, ".tmp");
const targetRoot = path.join(workspaceParent, `e2e-frontend-${port}`);
if (
  path.dirname(targetRoot) !== workspaceParent ||
  path.basename(targetRoot) !== `e2e-frontend-${port}`
) {
  throw new Error("refusing to prepare an E2E workspace outside frontend/.tmp");
}

const entries = [
  "app",
  "components",
  "data",
  "hooks",
  "lib",
  "middleware.ts",
  "next-env.d.ts",
  "next.config.ts",
  "package.json",
  "postcss.config.mjs",
  "tsconfig.json",
];

const sourceFingerprint = createHash("sha256");
function addToFingerprint(entryPath) {
  const stat = fs.lstatSync(entryPath);
  sourceFingerprint.update(path.relative(frontendRoot, entryPath));
  if (stat.isDirectory()) {
    for (const child of fs.readdirSync(entryPath).sort()) {
      addToFingerprint(path.join(entryPath, child));
    }
    return;
  }
  sourceFingerprint.update(fs.readFileSync(entryPath));
}

for (const entry of entries) {
  const source = path.join(frontendRoot, entry);
  if (fs.existsSync(source)) {
    addToFingerprint(source);
  }
}

const fingerprint = sourceFingerprint.digest("hex");
const marker = path.join(targetRoot, ".source-fingerprint");
if (
  fs.existsSync(marker) &&
  fs.readFileSync(marker, "utf-8") === fingerprint &&
  fs.existsSync(path.join(targetRoot, "node_modules"))
) {
  process.stdout.write(`${targetRoot}\n`);
  process.exit(0);
}

fs.rmSync(targetRoot, { recursive: true, force: true });
fs.mkdirSync(targetRoot, { recursive: true });
for (const entry of entries) {
  const source = path.join(frontendRoot, entry);
  if (fs.existsSync(source)) {
    fs.cpSync(source, path.join(targetRoot, entry), { recursive: true });
  }
}
fs.symlinkSync(
  path.join(frontendRoot, "node_modules"),
  path.join(targetRoot, "node_modules"),
  process.platform === "win32" ? "junction" : "dir",
);
fs.writeFileSync(marker, fingerprint, "utf-8");
process.stdout.write(`${targetRoot}\n`);
