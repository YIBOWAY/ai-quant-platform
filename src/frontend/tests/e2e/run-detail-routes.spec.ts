import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

const repoRoot = findRepoRoot(process.cwd());
const e2eDataRoot = path.join(repoRoot, "src", "frontend", ".tmp", "e2e-data");
const apiRunsDir = path.join(e2eDataRoot, "api_runs");

const backtestRunId = "backtest-e2e-detail";
const factorRunId = "factor-e2e-detail";
const paperRunId = "paper-e2e-detail";

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

function writeJson(filePath: string, payload: unknown) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2));
}

function removeRun(kind: "backtests" | "factors" | "paper", runId: string) {
  fs.rmSync(path.join(apiRunsDir, kind, runId), { force: true, recursive: true });
}

test.describe("single run detail routes", () => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");

  test.beforeAll(() => {
    writeJson(path.join(apiRunsDir, "backtests", backtestRunId, "metadata.json"), {
      run_id: backtestRunId,
      source: "sample",
      request: {
        symbols: ["SPY"],
        start: "2024-01-02",
        end: "2024-01-12",
        provider: "sample",
      },
      metrics: {
        total_return: 0.0123,
        sharpe: 1.2,
        max_drawdown: -0.02,
      },
      paths: {},
    });
    writeJson(path.join(apiRunsDir, "backtests", backtestRunId, "backtests", "metrics.json"), {
      total_return: 0.0123,
      sharpe: 1.2,
      max_drawdown: -0.02,
    });

    writeJson(path.join(apiRunsDir, "factors", factorRunId, "metadata.json"), {
      run_id: factorRunId,
      source: "sample",
      row_count: 12,
      signal_count: 4,
      request: {
        symbols: ["SPY"],
        start: "2024-01-02",
        end: "2024-01-12",
        provider: "sample",
      },
      paths: {},
    });

    writeJson(path.join(apiRunsDir, "paper", paperRunId, "metadata.json"), {
      run_id: paperRunId,
      source: "sample",
      signal_count: 4,
      order_count: 2,
      trade_count: 1,
      risk_breach_count: 0,
      final_equity: 100250,
      request: {
        symbols: ["SPY"],
        start: "2024-01-02",
        end: "2024-01-12",
        provider: "sample",
      },
      paths: {},
    });
  });

  test.afterAll(() => {
    removeRun("backtests", backtestRunId);
    removeRun("factors", factorRunId);
    removeRun("paper", paperRunId);
  });

  test("list pages link to the latest run details", async ({ page }) => {
    await page.goto("/backtest?include_sample=1", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("link", { name: `Open ${backtestRunId}` })).toBeVisible();

    await page.goto("/factor-lab?include_sample=1", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("link", { name: `Open ${factorRunId}` })).toBeVisible();

    await page.goto("/paper-trading?include_sample=1", { waitUntil: "domcontentloaded" });
    // Replay run links live behind the "Historical Replay" tab; retry until hydrated.
    const replayTab = page.getByRole("tab", { name: "Historical Replay" });
    await expect(async () => {
      await replayTab.click();
      await expect(replayTab).toHaveAttribute("aria-selected", "true", { timeout: 1_000 });
    }).toPass({ timeout: 30_000 });
    await expect(page.getByRole("link", { name: `Open ${paperRunId}` })).toBeVisible();
  });

  test("dedicated run detail pages render the saved run", async ({ page }) => {
    await page.goto(`/backtest/${backtestRunId}`, { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Backtest Run Detail" })).toBeVisible();
    await expect(page.getByText(backtestRunId).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Metrics" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Trade Blotter" })).toBeVisible();

    await page.goto(`/factor-lab/${factorRunId}`, { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Factor Run Detail" })).toBeVisible();
    await expect(page.getByText(factorRunId).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Factor Values" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Signal Scores" })).toBeVisible();

    await page.goto(`/paper-trading/${paperRunId}`, { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Paper Run Detail" })).toBeVisible();
    await expect(page.getByText(paperRunId).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Order Lifecycle" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Risk Breaches" })).toBeVisible();
  });
});
