import { expect, test } from "@playwright/test";

const rollbackEnabled = process.env.PW_HERMES_ROLLBACK_E2E === "1";
const rollbackPort = process.env.PW_HERMES_ROLLBACK_PORT;
const rollbackBaseURL =
  rollbackEnabled && rollbackPort
    ? `http://127.0.0.1:${rollbackPort}`
    : null;

test.beforeEach(() => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");
  test.skip(
    !rollbackEnabled || !rollbackBaseURL,
    "Set PW_HERMES_ROLLBACK_E2E=1 and PW_HERMES_ROLLBACK_PORT for second-process rollback.",
  );
});

test("@rollback rolled-back root renders Dashboard without redirect", async ({
  browser,
}) => {
  const context = await browser.newContext({ baseURL: rollbackBaseURL! });
  const page = await context.newPage();
  try {
    await page.goto("/zh?source=rollback", { waitUntil: "networkidle" });
    await expect(page).toHaveURL(/\/zh(\?source=rollback)?$/);
    await expect(
      page.getByRole("heading", { name: "仪表盘", exact: true }),
    ).toBeVisible();
    await expect(page).not.toHaveURL(/\/hermes/);
  } finally {
    await context.close();
  }
});

test("@rollback desktop and mobile home entries are Dashboard; Hermes stays separate and read-only", async ({
  browser,
}) => {
  const context = await browser.newContext({ baseURL: rollbackBaseURL! });
  const page = await context.newPage();
  try {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/zh?source=rollback", { waitUntil: "networkidle" });

    const desktopHome = page
      .getByTestId("desktop-sidebar")
      .getByRole("link", { name: "仪表盘", exact: true });
    await expect(desktopHome).toBeVisible();
    await expect(
      page
        .getByTestId("desktop-sidebar")
        .getByRole("link", { name: "Hermes 工作台", exact: true }),
    ).toBeVisible();

    await page
      .getByTestId("desktop-sidebar")
      .getByRole("link", { name: "Hermes 工作台", exact: true })
      .click();
    await expect(page).toHaveURL(/\/zh\/hermes$/);
    await expect(page.getByRole("textbox", { name: "和 Hermes 对话" })).toBeDisabled();
    await expect(page.getByText("Hermes 对话当前不可用")).toBeVisible();

    await page
      .getByTestId("desktop-sidebar")
      .getByRole("link", { name: "仪表盘", exact: true })
      .click();
    await expect(page).toHaveURL(/\/zh\/?$/);
    await expect(
      page.getByRole("heading", { name: "仪表盘", exact: true }),
    ).toBeVisible();

    // Back should settle once on Hermes; forward once on Dashboard.
    await page.goBack();
    await expect(page).toHaveURL(/\/zh\/hermes$/);
    await expect(page.getByRole("textbox", { name: "和 Hermes 对话" })).toBeDisabled();

    await page.goForward();
    await expect(page).toHaveURL(/\/zh\/?$/);
    await expect(
      page.getByRole("heading", { name: "仪表盘", exact: true }),
    ).toBeVisible();

    // Mobile nav home is Dashboard as well.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/zh", { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "打开导航" }).click();
    await expect(
      page.locator("#mobile-navigation").getByRole("link", { name: "仪表盘", exact: true }),
    ).toBeVisible();
    await expect(
      page
        .locator("#mobile-navigation")
        .getByRole("link", { name: "Hermes 工作台", exact: true }),
    ).toBeVisible();
  } finally {
    await context.close();
  }
});
