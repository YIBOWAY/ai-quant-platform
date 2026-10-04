import { execFileSync, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

const repoRoot = findRepoRoot(process.cwd());
const apiBase = `http://127.0.0.1:${process.env.PW_BACKEND_PORT ?? "8765"}`;
let priceFixturePath: string | null = null;

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

function findPython() {
  const candidates = [
    process.env.PW_PYTHON,
    path.join(repoRoot, "ai-quant", "bin", "python"),
    path.join(repoRoot, "ai-quant", "Scripts", "python.exe"),
    path.join(repoRoot, ".venv", "bin", "python"),
    path.join(repoRoot, ".venv", "Scripts", "python.exe"),
    "python3",
    "python",
  ].filter((candidate): candidate is string => Boolean(candidate));
  for (const candidate of candidates) {
    const probe = spawnSync(candidate, ["--version"], { stdio: "ignore" });
    if (probe.status === 0) {
      return candidate;
    }
  }
  throw new Error("Unable to find a Python interpreter for paper price fixtures.");
}

function writePaperPriceFixture(parquetDir: string) {
  fs.mkdirSync(parquetDir, { recursive: true });
  const scriptPath = path.join(parquetDir, "_write_paper_price_fixture.py");
  const script = `
from pathlib import Path
import pandas as pd

root = Path(r"""${parquetDir}""")
root.mkdir(parents=True, exist_ok=True)
today = pd.Timestamp.now(tz="UTC").normalize()
prices = {"SPY": 500.0, "AAPL": 200.0}
rows = []
for symbol, close in prices.items():
    for offset in range(3):
        timestamp = today - pd.Timedelta(days=offset)
        rows.append({
            "symbol": symbol,
            "timestamp": timestamp,
            "open": close - 1.0,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": 1_000_000,
            "provider": "tiingo_fixture",
        })
pd.DataFrame(rows).to_parquet(root / "ohlcv.parquet", index=False)
`;
  fs.writeFileSync(scriptPath, script);
  execFileSync(findPython(), [scriptPath], { stdio: "inherit" });
  fs.rmSync(scriptPath, { force: true });
}

test.describe("position map", () => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");

  test.beforeAll(({}, workerInfo) => {
    const metadata = workerInfo.config.metadata as {
      e2eRun?: { dataRoot?: string };
    };
    const dataRoot = metadata.e2eRun?.dataRoot;
    if (!dataRoot) {
      throw new Error("Position Map E2E requires the isolated run data root.");
    }
    const parquetDir = path.join(dataRoot, "parquet");
    priceFixturePath = path.join(parquetDir, "ohlcv.parquet");
    writePaperPriceFixture(parquetDir);
  });

  test.afterAll(() => {
    if (priceFixturePath) {
      fs.rmSync(priceFixturePath, { force: true });
    }
  });

  test("renders the live paper account exposure after a manual order", async ({ page, request }) => {
    test.setTimeout(90_000);

    // Start from a clean funded account, then place a manual buy. The account
    // is the source of truth for the redesigned Position Map.
    const reset = await request.post(`${apiBase}/api/paper/account/reset`, {
      data: { initial_cash: 1000000 },
    });
    expect(reset.status()).toBe(200);

    const order = await request.post(`${apiBase}/api/paper/account/orders`, {
      data: { symbol: "SPY", side: "buy", notional: 100000 },
    });
    expect(order.status()).toBe(200);

    await page.goto("/paper-trading?view=map", { waitUntil: "domcontentloaded" });

    await expect(page.getByRole("heading", { name: "Position Map" })).toBeVisible();
    await expect(page.getByText("Net Value", { exact: true })).toBeVisible();
    await expect(page.getByText("Account Exposure by Symbol")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Account Positions" })).toBeVisible();
    await expect(page.getByText("SPY").first()).toBeVisible();
    const ordersTab = page.getByRole("tab", { name: /Orders/ });
    await ordersTab.click();
    const tabUrl = new URL(page.url());
    expect(tabUrl.searchParams.get("view")).toBe("map");
    expect(tabUrl.searchParams.get("tab")).toBe("orders");
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.getByRole("tab", { name: /Orders/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    // Clean up so repeated local runs start fresh.
    await request.post(`${apiBase}/api/paper/account/reset`, {
      data: { initial_cash: 1000000 },
    });
  });

  test("paper account reports partial fills clearly in the UI", async ({ page, request }) => {
    test.setTimeout(90_000);
    await request.post(`${apiBase}/api/paper/account/reset`, {
      data: { initial_cash: 1000000 },
    });
    await request.post(`${apiBase}/api/paper/account/orders`, {
      data: { symbol: "AAPL", side: "buy", quantity: 1 },
    });

    await page.goto("/paper-trading", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("button", { name: "Submit Order" })).toBeEnabled();
    await page.getByRole("combobox", { name: "Side" }).selectOption("sell");
    await page.getByRole("spinbutton", { name: "Quantity" }).fill("2");
    await page.getByRole("button", { name: "Submit Order" }).click();

    await expect(page.getByText(/Order partially filled/)).toBeVisible();

    await request.post(`${apiBase}/api/paper/account/reset`, {
      data: { initial_cash: 1000000 },
    });
  });

  test("Chinese paper account controls render and replay stays behind its tab", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/zh/paper-trading", { waitUntil: "domcontentloaded" });

    // Live-account tab is the default: manual controls come first on mobile,
    // replay research is not rendered until its tab is opened.
    await expect(page.getByText("手动下单", { exact: true })).toBeVisible();
    await expect(page.getByText("高级：全账户再平衡（非策略仓）", { exact: true })).toBeVisible();
    await expect(page.getByText("历史回放（研究）", { exact: true })).toHaveCount(0);

    const replayTab = page.getByRole("tab", { name: "历史回放" });
    await expect(async () => {
      await replayTab.click();
      await expect(replayTab).toHaveAttribute("aria-selected", "true", { timeout: 1_000 });
    }).toPass({ timeout: 30_000 });
    await expect(page.getByText("历史回放（研究）", { exact: true })).toBeVisible();
  });

  test("shared tabs and quick order preserve keyboard focus", async ({ page, request }) => {
    await request.post(`${apiBase}/api/paper/account/reset`, {
      data: { initial_cash: 1000000 },
    });

    await page.goto("/paper-trading", { waitUntil: "domcontentloaded" });
    const liveTab = page.getByRole("tab", { name: /Live Account/i });
    const replayTab = page.getByRole("tab", { name: /Historical Replay/i });

    await liveTab.focus();
    await page.keyboard.press("ArrowRight");
    await expect(replayTab).toBeFocused();
    await expect(replayTab).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("Home");
    await expect(liveTab).toBeFocused();
    await expect(liveTab).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("End");
    await expect(replayTab).toBeFocused();

    await page.goto("/position-map", { waitUntil: "domcontentloaded" });
    const trigger = page.getByRole("button", { name: "New paper order" });
    await trigger.focus();
    await trigger.click();

    const dialog = page.getByRole("dialog", { name: "Quick Order" });
    const closeButton = dialog.getByRole("button", { name: "Close" });
    const submitButton = dialog.getByRole("button", { name: "Submit paper order" });
    await expect(dialog).toBeVisible();
    await expect(dialog.locator("#qtd-symbol")).toBeFocused();

    await closeButton.focus();
    await page.keyboard.press("Shift+Tab");
    await expect(submitButton).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(closeButton).toBeFocused();
    await page.keyboard.press("Escape");

    await expect(page.getByRole("dialog", { name: "Quick Order" })).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });
});
