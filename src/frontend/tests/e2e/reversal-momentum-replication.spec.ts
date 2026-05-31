import { expect, test } from "@playwright/test";

test.describe("paper replication workbench", () => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");

  test("runs the reversal and momentum paper replication from the UI", async ({ page }) => {
    test.setTimeout(90_000);

    await page.goto("/replications", { waitUntil: "domcontentloaded" });

    await expect(
      page.getByRole("heading", {
        name: "Short-Term Reversals and Longer-Term Momentum",
      }),
    ).toBeVisible();

    await expect(page.getByRole("button", { name: "Run paper replication" })).toBeEnabled();
    await page.getByLabel("Data Source").selectOption("sample");
    const responsePromise = page.waitForResponse(
      (response) =>
        response.url().includes("/api/replications/reversal-momentum/run") &&
        response.request().method() === "POST",
      { timeout: 45_000 },
    );
    await page.getByRole("button", { name: "Run paper replication" }).click();

    const response = await responsePromise;
    expect(response.status()).toBe(200);
    await expect(page.getByTestId("replication-equity-chart")).toBeVisible();
    await expect(page.getByText("Monthly Strategy Returns")).toBeVisible();
    await expect(page.getByText("Composite Positions")).toBeVisible();

    await page.getByRole("link", { name: "Open docs" }).click();
    await expect(page).toHaveURL(/\/docs\/reversal-momentum/);
    await expect(page.getByText("docs/replications/reversal_momentum_replication.md")).toBeVisible();
  });
});
