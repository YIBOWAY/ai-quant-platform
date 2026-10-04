import { expect, test } from "@playwright/test";
import {
  assertFullPageTargetsAndFocus,
  assertNoHorizontalOverflow,
  assertReducedMotion,
  assertTechnicalDetailDoesNotHijackScroll,
  installLoopbackOnlyGuard,
} from "./helpers/hermes-page-gates";
import { assertCurrentHermesDesk } from "./helpers/current-hermes-desk";
import { collectBrowserErrors, expectNoBrowserErrors } from "./helpers/console-error-gate";

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

test.beforeEach(() => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack visual checks.");
  test.skip(
    !process.env.PW_HERMES_WORKBENCH_FIXTURE,
    "Visual matrix requires PW_HERMES_WORKBENCH_FIXTURE (combined GET-only fixtures).",
  );
});

function installConsoleCollector(page: import("@playwright/test").Page) {
  const consoleProblems = collectBrowserErrors(page, fixture === "offline" ? [{ method: "GET", status: 503, url: "/api/assistant/remote/book" }] : []);
  page.on("console", (message) => {
    if (message.type() === "warning") {
      consoleProblems.problems.push(message.text());
    }
  });
  return consoleProblems;
}

async function resetScroll(page: import("@playwright/test").Page) {
  await page.evaluate(() => {
    window.scrollTo(0, 0);
    document
      .querySelectorAll<HTMLElement>("[data-page-scroll-region], [data-hermes-desk] .dp-scroll")
      .forEach((node) => {
        node.scrollTop = 0;
      });
  });
}

for (const viewport of viewports) {
  test(`@combined-fixture Hermes ${fixture} zh ${viewport.name}`, async ({ page }, testInfo) => {
    const externalRequests = await installLoopbackOnlyGuard(page);
    const consoleProblems = installConsoleCollector(page);
    await page.setViewportSize(viewport);
    await page.goto("/zh/hermes", { waitUntil: "networkidle" });
    await assertCurrentHermesDesk(page);
    await assertNoHorizontalOverflow(page, viewport.width);
    await assertFullPageTargetsAndFocus(page);
    await assertReducedMotion(page);
    if (fixture === "normal" || fixture === "long-content") {
      await assertTechnicalDetailDoesNotHijackScroll(page);
    }
    expect(externalRequests).toEqual([]);
    expectNoBrowserErrors(consoleProblems);
    await resetScroll(page);
    await page.screenshot({ path: testInfo.outputPath(`hermes-${fixture}-zh-${viewport.name}-candidate.png`), animations: "disabled" });
    await expect(page).toHaveScreenshot(`hermes-${fixture}-zh-${viewport.name}.png`, {
      animations: "disabled",
      maxDiffPixelRatio: 0.02,
    });
  });

  if (fixture === "normal") {
    test(`@combined-fixture Hermes normal en ${viewport.name}`, async ({ page }, testInfo) => {
      const externalRequests = await installLoopbackOnlyGuard(page);
      const consoleProblems = installConsoleCollector(page);
      await page.setViewportSize(viewport);
      await page.goto("/en/hermes", { waitUntil: "networkidle" });
      await assertCurrentHermesDesk(page);
      await assertNoHorizontalOverflow(page, viewport.width);
      await assertFullPageTargetsAndFocus(page);
      await assertReducedMotion(page);
      await assertTechnicalDetailDoesNotHijackScroll(page);
      expect(externalRequests).toEqual([]);
      expectNoBrowserErrors(consoleProblems);
      await resetScroll(page);
      await page.screenshot({ path: testInfo.outputPath(`hermes-normal-en-${viewport.name}-candidate.png`), animations: "disabled" });
      await expect(page).toHaveScreenshot(`hermes-normal-en-${viewport.name}.png`, {
        animations: "disabled",
        maxDiffPixelRatio: 0.02,
      });
    });
  }
}
