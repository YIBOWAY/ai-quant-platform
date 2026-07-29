import fs from "node:fs";
import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

import { buildE2ERunIdentity } from "./tests/support/hermes-e2e-run-root.mjs";

const HERMES_WORKBENCH_FIXTURES = new Set([
  "normal",
  "degraded",
  "offline",
  "empty",
  "long-content",
]);

const runE2E = process.env.PW_E2E === "1";
const repoRoot = findRepoRoot(process.cwd());
const frontendRoot = path.join(repoRoot, "src", "frontend");
const e2eDataRootBase = path.join(frontendRoot, ".tmp", "e2e-data");
const hermesArtifactFixture = path.join(
  frontendRoot,
  "tests",
  "fixtures",
  "hermes-artifacts.v1.json",
);
const reuseExistingServer = process.env.PW_REUSE_SERVER === "1";
const hermesWorkbenchFixture = readHermesWorkbenchFixture(
  process.env.PW_HERMES_WORKBENCH_FIXTURE,
);
const lifecycleFixtureMode = readOptionalFlag(
  "PW_HERMES_LIFECYCLE_FIXTURE",
);
if (lifecycleFixtureMode && hermesWorkbenchFixture !== null) {
  throw new Error(
    "PW_HERMES_LIFECYCLE_FIXTURE cannot be combined with PW_HERMES_WORKBENCH_FIXTURE",
  );
}
const fixtureMode =
  lifecycleFixtureMode || hermesWorkbenchFixture !== null;
const fixtureIdentity = lifecycleFixtureMode
  ? "lifecycle"
  : hermesWorkbenchFixture;
if (
  fixtureMode &&
  (process.env.QUANT_API_COMMAND || process.env.PW_REUSE_SERVER === "1")
) {
  // Fail before any process or socket is opened.
  throw new Error("fixture mode cannot reuse or override the backend");
}
const backendPort = readPort("PW_BACKEND_PORT", 8765);
const frontendPort = readPort("PW_FRONTEND_PORT", 3001);
const e2eRunIdentity = buildE2ERunIdentity({
  baseRoot: e2eDataRootBase,
  rawRunId: process.env.PW_E2E_RUN_ID,
  backendPort,
  frontendPort,
  processId: process.pid,
});
const e2eDataRoot = e2eRunIdentity.dataRoot;
const rollbackE2E = process.env.PW_HERMES_ROLLBACK_E2E === "1";
const rollbackPort = rollbackE2E
  ? readRequiredPort("PW_HERMES_ROLLBACK_PORT")
  : null;
if (rollbackPort !== null && rollbackPort === frontendPort) {
  throw new Error(
    "PW_HERMES_ROLLBACK_PORT must differ from PW_FRONTEND_PORT",
  );
}
if (rollbackPort !== null && rollbackPort === backendPort) {
  throw new Error(
    "PW_HERMES_ROLLBACK_PORT must differ from PW_BACKEND_PORT",
  );
}
const backendUrl = `http://127.0.0.1:${backendPort}`;
const frontendUrl = `http://127.0.0.1:${frontendPort}`;
const forbiddenProviderProbe = Object.freeze({
  url: `${backendUrl}/api/health`,
  allowedForReadiness: false,
});
const providerFreeBackendReadinessUrl = requireProviderFreeReadinessUrl(
  lifecycleFixtureMode ||
    (hermesWorkbenchFixture !== null &&
      hermesWorkbenchFixture !== "normal")
    ? `${backendUrl}/api/hermes/fixture-ready`
    : `${backendUrl}/api/hermes/gateway`,
);
const rollbackFrontendUrl =
  rollbackPort !== null ? `http://127.0.0.1:${rollbackPort}` : null;
const e2eCorsOrigins = Array.from(
  new Set([
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "http://localhost:3000",
    "http://localhost:3001",
    frontendUrl,
    ...(rollbackFrontendUrl ? [rollbackFrontendUrl] : []),
  ]),
);
const frontendCommand = buildFrontendCommand(frontendPort);
const rollbackFrontendCommand =
  rollbackPort !== null ? buildFrontendCommand(rollbackPort) : null;
const backendPython = resolveBackendPython();
const backendCommand = buildSupervisedBackendCommand();
const backendReuse = fixtureMode ? false : reuseExistingServer;
const frontendReuse = fixtureMode || rollbackE2E ? false : reuseExistingServer;

function requireProviderFreeReadinessUrl(candidate: string): string {
  if (
    !forbiddenProviderProbe.allowedForReadiness &&
    candidate === forbiddenProviderProbe.url
  ) {
    throw new Error("Playwright backend readiness must not use /api/health");
  }
  return candidate;
}

function buildFrontendCommand(port: number): string {
  const frontendDevCommand =
    port === 3001
      ? "npm run dev"
      : `npx next dev --hostname 127.0.0.1 --port ${port}`;
  return [
    `node scripts/prepare-e2e-workspace.mjs ${port}`,
    `cd ".tmp/e2e-frontend-${port}"`,
    frontendDevCommand,
  ].join(" && ");
}

function buildBackendLaunch(): { command: string; args: string[] } {
  if (fixtureMode) {
    return {
      command: process.execPath,
      args: [
        path.join(
          frontendRoot,
          "tests",
          "support",
          "hermes-fixture-api.mjs",
        ),
        String(backendPort),
        lifecycleFixtureMode ? "normal" : hermesWorkbenchFixture!,
        ...(lifecycleFixtureMode ? ["lifecycle"] : []),
      ],
    };
  }

  const customCommand = process.env.QUANT_API_COMMAND;
  if (customCommand) {
    if (process.platform === "win32") {
      return {
        command: process.env.ComSpec ?? "cmd.exe",
        args: ["/d", "/s", "/c", customCommand],
      };
    }
    return {
      command: process.env.SHELL ?? "/bin/sh",
      args: ["-lc", customCommand],
    };
  }

  return {
    command: backendPython,
    args: [
      "-m",
      "uvicorn",
      "quant_system.api.server:create_app",
      "--factory",
      "--host",
      "127.0.0.1",
      "--port",
      String(backendPort),
    ],
  };
}

function buildSupervisedBackendCommand(): string {
  const launch = buildBackendLaunch();
  const payload = Buffer.from(
    JSON.stringify({
      ...launch,
      backendPort,
      baseRoot: e2eRunIdentity.baseRoot,
      fixture: fixtureIdentity,
      frontendPort,
      runId: e2eRunIdentity.runId,
    }),
    "utf8",
  ).toString("base64url");
  const runner = path.join(
    frontendRoot,
    "tests",
    "support",
    "hermes-e2e-backend-runner.mjs",
  );
  return `${JSON.stringify(process.execPath)} ${JSON.stringify(runner)} ${JSON.stringify(payload)}`;
}

function resolveBackendPython(): string {
  const candidates = [
    process.env.PW_PYTHON,
    path.join(repoRoot, "ai-quant", "bin", "python"),
    path.join(repoRoot, ".venv", "bin", "python"),
  ];
  for (const candidate of candidates) {
    if (candidate && fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return "python";
}

function readHermesWorkbenchFixture(
  raw: string | undefined,
): string | null {
  if (raw === undefined || raw === "") {
    return null;
  }
  if (!HERMES_WORKBENCH_FIXTURES.has(raw)) {
    throw new Error(
      `PW_HERMES_WORKBENCH_FIXTURE must be one of: ${[...HERMES_WORKBENCH_FIXTURES].join(", ")}`,
    );
  }
  return raw;
}

function readOptionalFlag(name: string): boolean {
  const raw = process.env[name];
  if (raw === undefined || raw === "" || raw === "0") {
    return false;
  }
  if (raw === "1") {
    return true;
  }
  throw new Error(`${name} must be 0 or 1`);
}

function readPort(name: string, fallback: number) {
  const raw = process.env[name];
  if (!raw) {
    return fallback;
  }
  const port = Number(raw);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error(`${name} must be an integer TCP port between 1 and 65535.`);
  }
  return port;
}

function readRequiredPort(name: string) {
  const raw = process.env[name];
  if (!raw) {
    throw new Error(`${name} is required when PW_HERMES_ROLLBACK_E2E=1`);
  }
  const port = Number(raw);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error(`${name} must be an integer TCP port between 1 and 65535.`);
  }
  return port;
}

function findRepoRoot(start: string) {
  let current = path.resolve(start);
  while (true) {
    if (
      fs.existsSync(path.join(current, "pyproject.toml")) &&
      fs.existsSync(path.join(current, "src", "frontend", "package.json"))
    ) {
      return current;
    }
    const parent = path.dirname(current);
    if (parent === current) {
      throw new Error(`Unable to locate repository root from ${start}`);
    }
    current = parent;
  }
}

type WebServerConfig = {
  command: string;
  cwd: string;
  url: string;
  reuseExistingServer: boolean;
  timeout: number;
  gracefulShutdown?: {
    signal: "SIGINT" | "SIGTERM";
    timeout: number;
  };
  env?: { [key: string]: string };
};

function buildWebServers(): WebServerConfig[] | undefined {
  if (!runE2E) {
    return undefined;
  }

  const servers: WebServerConfig[] = [
    {
      command: backendCommand,
      cwd: repoRoot,
      url: providerFreeBackendReadinessUrl,
      reuseExistingServer: backendReuse,
      timeout: 60_000,
      // Playwright defaults to SIGKILL. A bounded TERM window is required so
      // the backend supervisor can verify provenance and remove only its root.
      gracefulShutdown: { signal: "SIGTERM", timeout: 10_000 },
      // Fixture server is pure Node and ignores QS_* settings.
      // Only real-smoke mode injects hermetic platform env. Never forward
      // the fixture name into this process environment.
      ...(fixtureMode
        ? {}
        : {
            env: {
              QS_ENVIRONMENT: "test",
              QS_DATABASE_ENABLED: "false",
              QS_DATABASE_AUTO_MIGRATE: "false",
              QS_API_BIND_ADDRESS: "127.0.0.1",
              QS_HERMES_GATEWAY_ENABLED: "false",
              QS_AIHOT_ENABLED: "false",
              QS_HERMES_ARTIFACT_FEED_PATH: hermesArtifactFixture,
              QS_HERMES_ARTIFACT_FRESHNESS_BUDGET_SECONDS: "315360000",
              QS_API_CORS_ORIGINS: JSON.stringify(e2eCorsOrigins),
              QS_DATA_DIR: e2eDataRoot,
              QS_AGENT_OUTPUT_DIR: path.join(e2eDataRoot, "agent-output"),
              QS_PARQUET_DIR: path.join(e2eDataRoot, "parquet"),
              QS_DUCKDB_PATH: path.join(e2eDataRoot, "quant_system.duckdb"),
              QS_OPTIONS_RADAR_OUTPUT_DIR: path.join(
                e2eDataRoot,
                "options_scans",
              ),
              QS_OPTIONS_RADAR_UNIVERSE_PATH: path.join(
                e2eDataRoot,
                "options_universe",
                "universe.csv",
              ),
              QS_OPTIONS_RADAR_EARNINGS_CALENDAR_PATH: path.join(
                e2eDataRoot,
                "options_universe",
                "earnings_calendar.csv",
              ),
              QS_OPTIONS_RADAR_VIX_HISTORY_PATH: path.join(
                e2eDataRoot,
                "options_universe",
                "vix_history.csv",
              ),
            },
          }),
    },
    {
      command: frontendCommand,
      cwd: frontendRoot,
      url: frontendUrl,
      reuseExistingServer: frontendReuse,
      timeout: 120_000,
      env: {
        // Pin the API base for hermetic E2E runs: shell env beats .env.local
        // in Next.js, so this overrides any local override (e.g. 8800/8700).
        // Pin the same-origin /api rewrite to the same isolated backend port so
        // owner-cookie + CSRF lifecycle requests never drift to :8765.
        // Never inject PW_HERMES_WORKBENCH_FIXTURE or fixture name here.
        // Never expose shell flag as NEXT_PUBLIC_*.
        NEXT_PUBLIC_QUANT_API_BASE_URL: backendUrl,
        QUANT_API_REWRITE_ORIGIN: backendUrl,
        NEXT_FONT_GOOGLE_MOCKED_RESPONSES: path.join(
          frontendRoot,
          "tests",
          "support",
          "next-font-mock.cjs",
        ),
        QS_HERMES_SHELL_ENABLED: "true",
        ...(lifecycleFixtureMode
          ? { QS_HERMES_CHAT_ENABLED: "true" }
          : {}),
      },
    },
  ];

  if (rollbackPort !== null && rollbackFrontendCommand && rollbackFrontendUrl) {
    servers.push({
      command: rollbackFrontendCommand,
      cwd: frontendRoot,
      url: rollbackFrontendUrl,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        NEXT_PUBLIC_QUANT_API_BASE_URL: backendUrl,
        QUANT_API_REWRITE_ORIGIN: backendUrl,
        NEXT_FONT_GOOGLE_MOCKED_RESPONSES: path.join(
          frontendRoot,
          "tests",
          "support",
          "next-font-mock.cjs",
        ),
        QS_HERMES_SHELL_ENABLED: "false",
      },
    });
  }

  return servers;
}

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  use: {
    baseURL: frontendUrl,
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  // Safe per-run facts stay in Playwright process/config metadata so evidence
  // collectors can bind the actual ports, fixture, and owned data root.
  metadata: runE2E
    ? {
        e2eRun: {
          backendPort,
          dataRoot: e2eDataRoot,
          fixture: fixtureIdentity,
          frontendPort,
          runId: e2eRunIdentity.runId,
        },
        ...(hermesWorkbenchFixture
          ? { hermesWorkbenchFixture }
          : {}),
        ...(lifecycleFixtureMode
          ? { hermesLifecycleFixture: true }
          : {}),
      }
    : undefined,
  webServer: buildWebServers(),
});
