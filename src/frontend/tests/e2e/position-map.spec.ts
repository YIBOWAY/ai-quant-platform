import { expect, test } from "@playwright/test";

test.describe("position map", () => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");

  test("renders the live paper account exposure after a manual order", async ({ page, request }) => {
    test.setTimeout(90_000);

    // Start from a clean funded account, then place a manual buy. The account
    // is the source of truth for the redesigned Position Map.
    const reset = await request.post("http://127.0.0.1:8765/api/paper/account/reset", {
      data: { initial_cash: 1000000 },
    });
    expect(reset.status()).toBe(200);

    const order = await request.post("http://127.0.0.1:8765/api/paper/account/orders", {
      data: { symbol: "SPY", side: "buy", notional: 100000 },
    });
    expect(order.status()).toBe(200);

    await page.goto("/position-map", { waitUntil: "domcontentloaded" });

    await expect(page.getByRole("heading", { name: "Position Map" })).toBeVisible();
    await expect(page.getByText("Account Value")).toBeVisible();
    await expect(page.getByText("Account Exposure by Symbol")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Account Positions" })).toBeVisible();
    await expect(page.getByText("SPY").first()).toBeVisible();

    // Clean up so repeated local runs start fresh.
    await request.post("http://127.0.0.1:8765/api/paper/account/reset", {
      data: { initial_cash: 1000000 },
    });
  });

  test("paper account reports partial fills clearly in the UI", async ({ page, request }) => {
    test.setTimeout(90_000);
    await request.post("http://127.0.0.1:8765/api/paper/account/reset", {
      data: { initial_cash: 1000000 },
    });
    await request.post("http://127.0.0.1:8765/api/paper/account/orders", {
      data: { symbol: "AAPL", side: "buy", quantity: 1 },
    });

    await page.goto("/paper-trading", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("button", { name: "Submit Order" })).toBeEnabled();
    await page.getByRole("combobox", { name: "Side" }).selectOption("sell");
    await page.getByRole("spinbutton", { name: "Quantity" }).fill("2");
    await page.getByRole("button", { name: "Submit Order" }).click();

    await expect(page.getByText(/Order partially filled/)).toBeVisible();

    await request.post("http://127.0.0.1:8765/api/paper/account/reset", {
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
    await expect(page.getByText("策略再平衡", { exact: true })).toBeVisible();
    await expect(page.getByText("历史回放（研究）", { exact: true })).toHaveCount(0);

    const replayTab = page.getByRole("tab", { name: "历史回放" });
    await expect(async () => {
      await replayTab.click();
      await expect(replayTab).toHaveAttribute("aria-selected", "true", { timeout: 1_000 });
    }).toPass({ timeout: 30_000 });
    await expect(page.getByText("历史回放（研究）", { exact: true })).toBeVisible();
  });
});
