import fs from "node:fs";
import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

const runE2E = process.env.PW_E2E === "1";
const repoRoot = findRepoRoot(process.cwd());
const frontendRoot = path.join(repoRoot, "src", "frontend");
const e2eDataRoot = path.join(frontendRoot, ".tmp", "e2e-data");
const reuseExistingServer = process.env.PW_REUSE_SERVER === "1";

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
    baseURL: "http://127.0.0.1:3001",
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
            "python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765",
          cwd: repoRoot,
          url: "http://127.0.0.1:8765/api/health",
          reuseExistingServer,
          timeout: 60_000,
          env: {
            QS_ENVIRONMENT: "test",
            QS_DATABASE_ENABLED: "false",
            QS_DATABASE_AUTO_MIGRATE: "false",
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
          command: "npm run dev",
          cwd: frontendRoot,
          url: "http://127.0.0.1:3001",
          reuseExistingServer,
          timeout: 120_000,
          env: {
            // Pin the API base for hermetic E2E runs: shell env beats .env.local
            // in Next.js, so this overrides any local override (e.g. 8800/8700).
            NEXT_PUBLIC_QUANT_API_BASE_URL: "http://127.0.0.1:8765",
          },
        },
      ]
    : undefined,
});
