import { expect, test } from "@playwright/test";

test.describe("strategy catalog", () => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");

  test("runs the reversal and momentum strategy from the catalog", async ({ page }) => {
    test.setTimeout(90_000);

    await page.goto("/replications", { waitUntil: "domcontentloaded" });

    await expect(page.getByRole("heading", { name: "Strategy Catalog" })).toBeVisible();
    await expect(page.getByLabel("Strategy")).toContainText("Cross-Sectional Top-N");
    await expect(page.getByRole("button", { name: "Run Strategy" })).toBeEnabled();

    await page.getByLabel("Strategy").selectOption("reversal_momentum");
    await expect(page.getByLabel("Strategy")).toHaveValue("reversal_momentum");
    await page.getByLabel("provider").selectOption("sample");

    const responsePromise = page.waitForResponse(
      (response) =>
        response.url().includes("/api/replications/reversal-momentum/run") &&
        response.request().method() === "POST",
      { timeout: 45_000 },
    );
    await page.getByRole("button", { name: "Run Strategy" }).click();

    const response = await responsePromise;
    expect(response.status()).toBe(200);
    await expect(page.getByTestId("replication-equity-chart")).toBeVisible();
    await expect(page.getByText("Monthly Strategy Returns")).toBeVisible();
    await expect(page.getByText("Composite Positions")).toBeVisible();
  });
});
