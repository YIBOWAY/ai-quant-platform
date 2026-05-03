import fs from "node:fs";
import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

const runE2E = process.env.PW_E2E === "1";
const repoRoot = findRepoRoot(process.cwd());
const frontendRoot = path.join(repoRoot, "src", "frontend");
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
        },
        {
          command: "npm run dev -- --hostname 127.0.0.1 --port 3001",
          cwd: frontendRoot,
          url: "http://127.0.0.1:3001",
          reuseExistingServer,
          timeout: 120_000,
          env: {
            DISABLE_HMR: "true",
          },
        },
      ]
    : undefined,
});
