import { expect, test } from "@playwright/test";
import {
  assertFullPageTargetsAndFocus,
  assertNoHorizontalOverflow,
  assertReducedMotion,
  assertTechnicalDetailDoesNotHijackScroll,
  installLoopbackOnlyGuard,
} from "./helpers/hermes-page-gates";

/**
 * Task 7 visual / a11y / locale / console matrix.
 * Fixture selection is process-only (PW_HERMES_WORKBENCH_FIXTURE + GET-only server).
 * Production pages never see the fixture name.
 */
const viewports = [
  { name: "wide", width: 1440, height: 900 },
  { name: "desktop", width: 1280, height: 800 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "mobile", width: 390, height: 844 },
] as const;

const fixture = process.env.PW_HERMES_WORKBENCH_FIXTURE ?? "normal";
const expectedState = fixture === "long-content" ? "degraded" : fixture;

test.beforeEach(() => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack visual checks.");
  test.skip(
    !process.env.PW_HERMES_WORKBENCH_FIXTURE,
    "Visual matrix requires PW_HERMES_WORKBENCH_FIXTURE (combined GET-only fixtures).",
  );
});

function installConsoleCollector(page: import("@playwright/test").Page): string[] {
  const consoleProblems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleProblems.push(message.text());
    }
  });
  return consoleProblems;
}

async function resetScroll(page: import("@playwright/test").Page) {
  await page.evaluate(() => {
    window.scrollTo(0, 0);
    document
      .querySelectorAll<HTMLElement>("[data-page-scroll-region]")
      .forEach((node) => {
        node.scrollTop = 0;
      });
  });
}

for (const viewport of viewports) {
  test(`@combined-fixture Hermes ${fixture} zh ${viewport.name}`, async ({ page }) => {
    const externalRequests = await installLoopbackOnlyGuard(page);
    const consoleProblems = installConsoleCollector(page);
    await page.setViewportSize(viewport);
    await page.goto("/zh/hermes", { waitUntil: "networkidle" });
    await expect(page.getByTestId("hermes-today-state")).toHaveAttribute(
      "data-state",
      expectedState,
    );
    await assertNoHorizontalOverflow(page, viewport.width);
    await assertFullPageTargetsAndFocus(page);
    await assertReducedMotion(page);
    if (fixture === "normal" || fixture === "long-content") {
      await assertTechnicalDetailDoesNotHijackScroll(page);
    }
    expect(externalRequests).toEqual([]);
    expect(consoleProblems).toEqual([]);
    await resetScroll(page);
    await expect(page).toHaveScreenshot(`hermes-${fixture}-zh-${viewport.name}.png`, {
      animations: "disabled",
      maxDiffPixelRatio: 0.02,
    });
  });

  if (fixture === "normal") {
    test(`@combined-fixture Hermes normal en ${viewport.name}`, async ({ page }) => {
      const externalRequests = await installLoopbackOnlyGuard(page);
      const consoleProblems = installConsoleCollector(page);
      await page.setViewportSize(viewport);
      await page.goto("/en/hermes", { waitUntil: "networkidle" });
      await expect(page.getByTestId("hermes-today-state")).toHaveAttribute(
        "data-state",
        "normal",
      );
      await assertNoHorizontalOverflow(page, viewport.width);
      await assertFullPageTargetsAndFocus(page);
      await assertReducedMotion(page);
      await assertTechnicalDetailDoesNotHijackScroll(page);
      expect(externalRequests).toEqual([]);
      expect(consoleProblems).toEqual([]);
      await resetScroll(page);
      await expect(page).toHaveScreenshot(`hermes-normal-en-${viewport.name}.png`, {
        animations: "disabled",
        maxDiffPixelRatio: 0.02,
      });
    });
  }
}
