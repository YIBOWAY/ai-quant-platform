import fs from "node:fs";
import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

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
const backendPort = readPort("PW_BACKEND_PORT", 8765);
const frontendPort = readPort("PW_FRONTEND_PORT", 3001);
const backendUrl = `http://127.0.0.1:${backendPort}`;
const frontendUrl = `http://127.0.0.1:${frontendPort}`;
const e2eCorsOrigins = Array.from(
  new Set([
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "http://localhost:3000",
    "http://localhost:3001",
    frontendUrl,
  ]),
);
const frontendDevCommand =
  frontendPort === 3001
    ? "npm run dev"
    : `npx next dev --hostname 127.0.0.1 --port ${frontendPort}`;
const frontendCommand = [
  `node scripts/prepare-e2e-workspace.mjs ${frontendPort}`,
  `cd ".tmp/e2e-frontend-${frontendPort}"`,
  frontendDevCommand,
].join(" && ");

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
  webServer: runE2E
    ? [
        {
          command:
            process.env.QUANT_API_COMMAND ??
            `python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port ${backendPort}`,
          cwd: repoRoot,
          url: `${backendUrl}/api/health`,
          reuseExistingServer,
          timeout: 60_000,
          env: {
            QS_ENVIRONMENT: "test",
            QS_DATABASE_ENABLED: "false",
            QS_DATABASE_AUTO_MIGRATE: "false",
            QS_AIHOT_ENABLED: "false",
            QS_HERMES_ARTIFACT_FEED_PATH: hermesArtifactFixture,
            QS_HERMES_ARTIFACT_FRESHNESS_BUDGET_SECONDS: "315360000",
            QS_API_CORS_ORIGINS: JSON.stringify(e2eCorsOrigins),
            QS_DATA_DIR: e2eDataRoot,
            QS_PARQUET_DIR: path.join(e2eDataRoot, "parquet"),
            QS_DUCKDB_PATH: path.join(e2eDataRoot, "quant_system.duckdb"),
            QS_OPTIONS_RADAR_OUTPUT_DIR: path.join(e2eDataRoot, "options_scans"),
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
        },
        {
          command: frontendCommand,
          cwd: frontendRoot,
          url: frontendUrl,
          reuseExistingServer,
          timeout: 120_000,
          env: {
            // Pin the API base for hermetic E2E runs: shell env beats .env.local
            // in Next.js, so this overrides any local override (e.g. 8800/8700).
            NEXT_PUBLIC_QUANT_API_BASE_URL: backendUrl,
          },
        },
      ]
    : undefined,
});
