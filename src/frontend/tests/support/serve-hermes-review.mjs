import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn, spawnSync } from "node:child_process";
import net from "node:net";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const apiPort = 19061, uiPort = 14061;
if (process.argv[2] !== "--isolated-child") {
  const profile = `(version 1) (allow default) (deny network*)
    (allow network-inbound (local ip "localhost:*")) (allow network-bind (local ip "localhost:*"))
    (allow network-outbound (remote unix-socket)) (allow network-inbound (local unix-socket))
    (allow network-outbound (remote ip "localhost:${apiPort}"))
    (allow network-outbound (remote ip "localhost:${uiPort}"))`;
  const child = spawn("/usr/bin/sandbox-exec", ["-p", profile, process.execPath, fileURLToPath(import.meta.url), "--isolated-child"], {
    stdio: "inherit", env: { HOME: process.env.HOME, PATH: process.env.PATH, LANG: "en_US.UTF-8", TZ: "Asia/Shanghai", NEXT_TELEMETRY_DISABLED: "1" },
  });
  for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
  child.once("exit", code => { process.exitCode = code ?? 1; });
} else {
  for (const port of [apiPort, uiPort]) {
    const server = net.createServer();
    await new Promise((resolve, reject) => { server.once("error", reject); server.listen(port, "127.0.0.1", resolve); });
    await new Promise(resolve => server.close(resolve));
  }
  const prepared = spawnSync(process.execPath, ["scripts/prepare-e2e-workspace.mjs", String(uiPort)], { cwd: frontend, stdio: "inherit" });
  if (prepared.status !== 0) throw new Error("Could not prepare isolated review source");
  const children = [
    spawn(process.execPath, ["tests/support/hermes-fixture-api.mjs", String(apiPort), "normal"], { cwd: frontend, stdio: "inherit", detached: true }),
    spawn(process.execPath, [path.join(frontend, "node_modules/next/dist/bin/next"), "dev", "--hostname", "127.0.0.1", "--port", String(uiPort)], {
      cwd: path.join(frontend, `.tmp/e2e-frontend-${uiPort}`), stdio: "inherit", detached: true,
      env: { ...process.env, QS_HERMES_SHELL_ENABLED: "true", NEXT_PUBLIC_QUANT_API_BASE_URL: `http://127.0.0.1:${apiPort}`, QUANT_API_REWRITE_ORIGIN: `http://127.0.0.1:${apiPort}`, NEXT_FONT_GOOGLE_MOCKED_RESPONSES: path.join(frontend, "tests/support/next-font-mock.cjs") },
    }),
  ];
  let stopping = false;
  const stop = () => {
    if (stopping) return; stopping = true;
    for (const child of children) if (child.exitCode === null) { try { process.kill(-child.pid, "SIGTERM"); } catch { /* Already exited. */ } }
    clearTimeout(deadline);
  };
  const deadline = setTimeout(stop, 600_000);
  for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, stop);
  for (const child of children) child.once("exit", stop);
  console.log(`REVIEW_ONLY http://127.0.0.1:${uiPort}/zh/hermes · pure fixture, max 10 minutes, not an E2E pass`);
  await Promise.all(children.map(child => new Promise(resolve => child.once("exit", resolve))));
}
