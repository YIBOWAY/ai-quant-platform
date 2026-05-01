import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

const runE2E = process.env.PW_E2E === "1";
const repoRoot = path.resolve(process.cwd(), "../..");

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
          reuseExistingServer: true,
          timeout: 60_000,
        },
        {
          command: "npm run build && npm run start -- -H 127.0.0.1 -p 3001",
          cwd: process.cwd(),
          url: "http://127.0.0.1:3001",
          reuseExistingServer: true,
          timeout: 120_000,
        },
      ]
    : undefined,
});
