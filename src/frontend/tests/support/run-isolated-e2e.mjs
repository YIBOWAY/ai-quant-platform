import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { E2E_MODES, selectE2EArguments } from "./e2e-selection.mjs";

// No formal-service reuse: the entire subprocess tree can reach only this run's
// loopback ports. Test doubles remain confined to their declared fixture mode.
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const root = path.resolve(frontend, "../..");
const args = process.argv.slice(2);
const mode = args.shift();
if (!E2E_MODES.includes(mode)) {
  throw new Error("First argument must be an isolated E2E mode");
}
if (!process.env.HOME) throw new Error("Original HOME is required");
const backendPort = 19051;
const frontendPort = 14051;
const rollbackPort = 14052;
const sentinelPort = 19891;
const ports = [backendPort, frontendPort, sentinelPort, ...(mode === "rollback" ? [rollbackPort] : [])];
for (const port of ports) {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", resolve);
  });
  await new Promise(resolve => server.close(resolve));
}
const runId = `repair-20260915-${mode}-${process.pid}`;
const destination = path.join(root, "artifacts/full-e2e-2026-09-15", runId);
fs.mkdirSync(destination, { recursive: true });
const env = {
  HOME: process.env.HOME,
  PATH: `${path.dirname(process.execPath)}:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin`,
  LANG: "en_US.UTF-8", TZ: "Asia/Shanghai", NEXT_TELEMETRY_DISABLED: "1",
  PW_E2E: "1", PW_REUSE_SERVER: "0", PW_CHROMIUM_CHANNEL: "chrome",
  PW_BACKEND_PORT: String(backendPort), PW_FRONTEND_PORT: String(frontendPort),
  PW_FUTU_SENTINEL_PORT: String(sentinelPort), PW_E2E_RUN_ID: runId,
  PW_PYTHON: path.join(root, ".venv/bin/python"), PYTHONPATH: `${path.join(root, "src")}:${root}`,
  PYTHONDONTWRITEBYTECODE: "1", PYTHONNOUSERSITE: "1",
  QS_DATABASE_ENABLED: "false", QS_DATABASE_AUTO_MIGRATE: "false",
  QS_LIVE_TRADING_ENABLED: "false", QS_LLM_PROVIDER: "stub", QS_LLM_API_KEY: "",
  QS_LLM_BASE_URL: "", QS_HERMES_GATEWAY_ENABLED: "false", QS_PAPER_ACCOUNT_DB_MODE: "file",
  PLAYWRIGHT_JSON_OUTPUT_FILE: path.join(destination, "results.json"),
  PLAYWRIGHT_HTML_OUTPUT_DIR: path.join(destination, "html"), PLAYWRIGHT_HTML_OPEN: "never",
  PW_RSC_CANCEL_DIAGNOSTIC: process.env.PW_RSC_CANCEL_DIAGNOSTIC || "0",
  PW_RSC_NO_ROUTE: process.env.PW_RSC_NO_ROUTE || "0",
  ...(process.env.PW_RSC_NO_ROUTE === "1" ? { QUANT_API_COMMAND: `${path.join(root, ".venv/bin/python")} -m uvicorn tests.support.prefetch_backend:create_app --factory --host 127.0.0.1 --port ${backendPort}` } : {}),
  ...(!["real", "brief", "prefetch", "lifecycle"].includes(mode) ? { PW_HERMES_WORKBENCH_FIXTURE: mode === "rollback" ? "normal" : mode } : {}),
  ...(mode === "prefetch" ? { PW_PRODUCTION_FRONTEND: "1" } : {}),
  ...(mode === "lifecycle" ? { PW_HERMES_LIFECYCLE_FIXTURE: "1" } : {}),
  ...(mode === "rollback" ? { PW_HERMES_ROLLBACK_E2E: "1", PW_HERMES_ROLLBACK_PORT: String(rollbackPort) } : {}),
};
const profile = [
  "(version 1) (allow default) (deny network*)",
  '(allow network-inbound (local ip "localhost:*"))',
  '(allow network-bind (local ip "localhost:*"))',
  "(allow network-outbound (remote unix-socket))", "(allow network-inbound (local unix-socket))",
  ...ports.map(port => `(allow network-outbound (remote ip "localhost:${port}"))`),
].join("\n");
if (args.some(arg => /^--(?:update-snapshots|retries|workers|config|project|output|reporter)(?:=|$)/.test(arg))) {
  throw new Error("Runner owns execution settings; do not override evidence or retries");
}
const selected = selectE2EArguments(mode, args);
const commandArgs = ["-p", profile, process.execPath, path.join(frontend, "node_modules/@playwright/test/cli.js"),
  "test", "--config=playwright.config.ts", "--project=chromium", "--workers=1", "--forbid-only",
  "--update-snapshots=none", "--reporter=line,json,html", `--output=${path.join(destination, "test-results")}`, ...selected];
fs.writeFileSync(path.join(destination, "command.json"), JSON.stringify({ command: "/usr/bin/sandbox-exec", args: commandArgs, cwd: frontend, env }, null, 2));
const probe = spawnSync("/usr/bin/sandbox-exec", ["-p", profile, "/usr/bin/true"]);
if (probe.status !== 0) throw new Error("OS network isolation unavailable");
console.log(`START ${runId} ${destination}`);
const stdout = fs.openSync(path.join(destination, "stdout.log"), "wx");
const stderr = fs.openSync(path.join(destination, "stderr.log"), "wx");
const child = spawn("/usr/bin/sandbox-exec", commandArgs, { cwd: frontend, env, stdio: ["ignore", stdout, stderr] });
const exitCode = await new Promise((resolve, reject) => {
  child.once("error", reject);
  child.once("exit", code => resolve(code ?? 1));
});
fs.closeSync(stdout); fs.closeSync(stderr);
const result = fs.existsSync(env.PLAYWRIGHT_JSON_OUTPUT_FILE) ? JSON.parse(fs.readFileSync(env.PLAYWRIGHT_JSON_OUTPUT_FILE, "utf8")) : null;
const fingerprintPath = path.join(frontend, `.tmp/e2e-frontend-${frontendPort}`, ".source-fingerprint");
const summary = { runId, destination, exitCode, stats: result?.stats, errors: result?.errors,
  frontendFingerprint: fs.existsSync(fingerprintPath) ? fs.readFileSync(fingerprintPath, "utf8").trim() : null };
fs.writeFileSync(path.join(destination, "run-summary.json"), JSON.stringify(summary, null, 2));
console.log(JSON.stringify(summary));
process.exitCode = exitCode;
