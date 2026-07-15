import fs from "node:fs";
import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

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
const e2eDataRoot = path.join(frontendRoot, ".tmp", "e2e-data");
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
const fixtureMode = hermesWorkbenchFixture !== null;
if (
  fixtureMode &&
  (process.env.QUANT_API_COMMAND || process.env.PW_REUSE_SERVER === "1")
) {
  // Fail before any process or socket is opened.
  throw new Error("fixture mode cannot reuse or override the backend");
}
const backendPort = readPort("PW_BACKEND_PORT", 8765);
const frontendPort = readPort("PW_FRONTEND_PORT", 3001);
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
const backendCommand = fixtureMode
  ? `node src/frontend/tests/support/hermes-fixture-api.mjs ${backendPort} ${hermesWorkbenchFixture}`
  : (process.env.QUANT_API_COMMAND ??
    `${JSON.stringify(backendPython)} -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port ${backendPort}`);
const backendReuse = fixtureMode ? false : reuseExistingServer;
const frontendReuse = fixtureMode || rollbackE2E ? false : reuseExistingServer;

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
      url: `${backendUrl}/api/health`,
      reuseExistingServer: backendReuse,
      timeout: 60_000,
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
        // Never inject PW_HERMES_WORKBENCH_FIXTURE or fixture name here.
        // Never expose shell flag as NEXT_PUBLIC_*.
        NEXT_PUBLIC_QUANT_API_BASE_URL: backendUrl,
        QS_HERMES_SHELL_ENABLED: "true",
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
  // Fixture name stays in Playwright process/config metadata only.
  metadata: fixtureMode
    ? { hermesWorkbenchFixture }
    : undefined,
  webServer: buildWebServers(),
});
