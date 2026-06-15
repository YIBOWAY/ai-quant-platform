import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

const repoRoot = findRepoRoot(process.cwd());
const e2eDataRoot = path.join(repoRoot, "src", "frontend", ".tmp", "e2e-data");
const experimentId = "experiment-e2e-page";
const experimentDir = path.join(e2eDataRoot, "experiments", experimentId);

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

function writeParquetFrames() {
  fs.mkdirSync(experimentDir, { recursive: true });
  const scriptPath = path.join(experimentDir, "_write_parquet_fixture.py");
  const script = `
from pathlib import Path
import pandas as pd

root = Path(r"""${experimentDir}""")
root.mkdir(parents=True, exist_ok=True)
pd.DataFrame([
    {"run_id": "run-lb3-top1", "lookback": 3, "top_n": 1, "sharpe": 0.85, "total_return": 0.031, "max_drawdown": -0.021, "turnover": 1.4},
    {"run_id": "run-lb5-top1", "lookback": 5, "top_n": 1, "sharpe": 1.42, "total_return": 0.052, "max_drawdown": -0.015, "turnover": 1.1},
    {"run_id": "run-lb5-top2", "lookback": 5, "top_n": 2, "sharpe": 1.05, "total_return": 0.041, "max_drawdown": -0.019, "turnover": 1.7},
]).to_parquet(root / "experiment_runs.parquet", index=False)
pd.DataFrame([
    {"run_id": "run-lb5-top1", "fold_id": "fold-1", "train_start": "2024-01-02", "train_end": "2024-01-19", "validation_start": "2024-01-22", "validation_end": "2024-01-26", "sharpe": 1.22, "total_return": 0.021},
    {"run_id": "run-lb5-top1", "fold_id": "fold-2", "train_start": "2024-01-09", "train_end": "2024-01-26", "validation_start": "2024-01-29", "validation_end": "2024-02-02", "sharpe": 1.61, "total_return": 0.024},
]).to_parquet(root / "walk_forward_folds.parquet", index=False)
`;
  fs.writeFileSync(scriptPath, script);
  execFileSync(
    "conda",
    ["run", "-n", "ai-quant", "--no-capture-output", "python", scriptPath],
    { stdio: "inherit" },
  );
  fs.rmSync(scriptPath, { force: true });
}

test.describe("experiments workbench", () => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");

  test.beforeAll(() => {
    fs.rmSync(experimentDir, { force: true, recursive: true });
    writeJson(path.join(experimentDir, "experiment_config.json"), {
      experiment_name: "experiment-e2e",
      symbols: ["SPY", "QQQ"],
      start: "2024-01-02",
      end: "2024-02-15",
      initial_cash: 100000,
      commission_bps: 1,
      slippage_bps: 5,
      factor_blend: {
        rebalance_every_n_bars: 1,
        factors: [
          { factor_id: "momentum", weight: 1, direction: "higher_is_better" },
          { factor_id: "volatility", weight: 0.5, direction: "lower_is_better" },
          { factor_id: "liquidity", weight: 0.5, direction: "higher_is_better" },
        ],
      },
      sweep: { lookback: [3, 5], top_n: [1, 2] },
      walk_forward: { enabled: true, train_bars: 12, validation_bars: 5, step_bars: 5 },
    });
    writeJson(path.join(experimentDir, "agent_summary.json"), {
      experiment_id: experimentId,
      experiment_name: "experiment-e2e",
      best_run_id: "run-lb5-top1",
      notes: ["No automatic deployment.", "Research-only comparison."],
      safety: { live_trading: false, paper_trading: false, auto_promotion: false },
      data: {
        source: "tiingo",
        symbols: ["SPY", "QQQ"],
        start: "2024-01-02",
        end: "2024-02-15",
      },
    });
    writeParquetFrames();
  });

  test.afterAll(() => {
    fs.rmSync(experimentDir, { force: true, recursive: true });
  });

  test("renders experiment charts and can send best run parameters to backtest", async ({ page }) => {
    await page.goto("/experiments", { waitUntil: "domcontentloaded" });

    await expect(page.getByRole("heading", { name: "Experiment Results" })).toBeVisible();
    await expect(page.getByText(experimentId).first()).toBeVisible();
    await expect(page.getByRole("complementary").getByText("best: run-lb5-top1")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Sweep Heatmap" })).toBeVisible();
    await expect(page.getByText("Data source: tiingo")).toBeVisible();
    await expect(page.getByText("Strategy under test")).toBeVisible();
    await expect(page.getByText("momentum")).toBeVisible();
    await expect(page.getByText("0.50x").first()).toBeVisible();
    await expect(page.getByText("lower is better")).toBeVisible();
    await expect(page.getByText("lookback=5 / top_n=1")).toBeVisible();
    await expect(page.locator('[data-experiment-tabs-ready="true"]')).toBeVisible();

    await page.getByRole("tab", { name: "Walk-forward folds" }).click();
    await expect(page.getByRole("heading", { name: "Walk-forward Folds" })).toBeVisible();
    await expect(page.getByText("fold-1")).toBeVisible();

    await page.getByRole("tab", { name: "Run comparison" }).click();
    await expect(page.getByRole("heading", { name: "Run Comparison" })).toBeVisible();
    await expect(page.getByText("run-lb5-top1", { exact: true }).first()).toBeVisible();

    await page.getByRole("tab", { name: "Agent summary" }).click();
    await expect(page.getByRole("heading", { name: "Agent Summary" })).toBeVisible();
    await expect(
      page.getByRole("listitem").filter({ hasText: "No automatic deployment." }),
    ).toBeVisible();

    await page.getByRole("link", { name: "Send to Backtest" }).click();
    await expect(page).toHaveURL(/\/backtest/);
    await expect(page.getByLabel("Symbols")).toHaveValue("SPY,QQQ");
    await expect(page.getByRole("combobox", { name: /Data Source/ })).toHaveValue("tiingo");
    await expect(page.getByLabel("Lookback")).toHaveValue("5");
    await expect(page.getByLabel("Top N")).toHaveValue("1");
  });
});
