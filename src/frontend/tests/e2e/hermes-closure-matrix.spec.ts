import { expect, test } from "@playwright/test";

import { installLoopbackOnlyGuard } from "./helpers/hermes-page-gates";

const modeMatches =
  process.env.PW_E2E === "1" &&
  process.env.PW_HERMES_WORKBENCH_FIXTURE === "normal" &&
  process.env.PW_HERMES_LIFECYCLE_FIXTURE !== "1";

if (modeMatches) {
  test("@combined-fixture proves legacyRedirects=false through the complete direct-route inventory", async ({
    page,
  }) => {
    const externalRequests = await installLoopbackOnlyGuard(page);
    const consoleProblems: string[] = [];
    const pageErrors: string[] = [];
    const httpProblems: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error" || message.type() === "warning") {
        consoleProblems.push(`${message.type()}: ${message.text()}`);
      }
    });
    page.on("pageerror", (error) => {
      pageErrors.push(error.message);
    });
    page.on("response", (response) => {
      if (response.status() >= 400) {
        httpProblems.push(
          `${response.status()} ${response.request().method()} ${response.url()}`,
        );
      }
    });
    const legacyRoutes = [
      "/factor-lab",
      "/agent-studio",
      "/backtest",
      "/experiments",
    ] as const;

    for (const locale of ["en", "zh"] as const) {
      for (const route of legacyRoutes) {
        const target = `/${locale}${route}?legacy_check=1#retained`;
        await page.goto(target, { waitUntil: "domcontentloaded" });
        await expect(page).toHaveURL(
          new RegExp(
            `/${locale}${route.replace("/", "\\/")}\\?legacy_check=1#retained$`,
          ),
        );
        await expect(page.getByTestId("hermes-parity-banner")).toBeVisible();
      }
    }
    expect(externalRequests).toEqual([]);
    expect(consoleProblems).toEqual([]);
    expect(pageErrors).toEqual([]);
    expect(httpProblems).toEqual([]);
  });
}
