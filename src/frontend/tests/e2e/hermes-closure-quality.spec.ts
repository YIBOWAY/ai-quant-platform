import { expect, test, type Page } from "@playwright/test";

import {
  assertWholeHermesShellControlsUnclipped,
  assertWholeHermesShellSemanticStatus,
  assertWholeHermesShellWcagAaContrast,
} from "./helpers/hermes-closure-gates";
import { installLoopbackOnlyGuard } from "./helpers/hermes-page-gates";

const viewports = [
  { name: "wide", width: 1440, height: 900 },
  { name: "desktop", width: 1280, height: 800 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "mobile", width: 390, height: 844 },
] as const;

const closureFixtures = new Set([
  "normal",
  "degraded",
  "offline",
  "empty",
  "long-content",
]);
const fixture = process.env.PW_HERMES_WORKBENCH_FIXTURE;
const modeMatches =
  process.env.PW_E2E === "1" &&
  fixture !== undefined &&
  closureFixtures.has(fixture) &&
  process.env.PW_HERMES_LIFECYCLE_FIXTURE !== "1";

function collectBrowserProblems(page: Page) {
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
  return { consoleProblems, httpProblems, pageErrors };
}

async function openFixturePage(
  page: Page,
  viewport: (typeof viewports)[number],
  expectedState: string,
) {
  const externalRequests = await installLoopbackOnlyGuard(page);
  const problems = collectBrowserProblems(page);
  await page.setViewportSize(viewport);
  await page.goto("/zh/hermes", { waitUntil: "networkidle" });
  await expect(page.getByTestId("hermes-today-state")).toHaveAttribute(
    "data-state",
    expectedState,
  );
  return { externalRequests, problems };
}

function expectCleanBrowser(
  externalRequests: string[],
  problems: ReturnType<typeof collectBrowserProblems>,
) {
  expect(externalRequests).toEqual([]);
  expect(problems.consoleProblems).toEqual([]);
  expect(problems.pageErrors).toEqual([]);
  expect(problems.httpProblems).toEqual([]);
}

if (modeMatches) {
  const fixtureName = fixture as string;
  const expectedState =
    fixtureName === "long-content" ? "degraded" : fixtureName;

  test("@combined-fixture contrast gate rejects visible muted-opacity text", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 400, height: 300 });
    await page.setContent(`
      <div data-hermes-workbench-a11y style="background: rgb(255, 255, 255); padding: 20px">
        <p style="color: rgb(120, 120, 120); opacity: 0.6">Visible muted text</p>
      </div>
    `);

    await expect(
      assertWholeHermesShellWcagAaContrast(page),
    ).rejects.toThrow(/WCAG AA text contrast failures/);
  });

  test("@combined-fixture control gate rejects four-edge clipping and corner-only coverage", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 400, height: 300 });
    await page.setContent(`
      <div data-hermes-workbench-a11y>
        <div style="position: relative; width: 120px; height: 100px; overflow: hidden">
          <button style="position: absolute; width: 180px; height: 140px">Clipped control</button>
        </div>
      </div>
    `);
    await expect(
      assertWholeHermesShellControlsUnclipped(page),
    ).rejects.toThrow(/clipping/);

    await page.setContent(`
      <div data-hermes-workbench-a11y style="position: relative; width: 400px; height: 300px">
        <button style="position: absolute; left: 40px; top: 40px; width: 160px; height: 80px">
          Partially covered control
        </button>
        <div style="position: absolute; z-index: 10; left: 40px; top: 40px; width: 16px; height: 8px; background: black">
        </div>
      </div>
    `);
    await expect(
      assertWholeHermesShellControlsUnclipped(page),
    ).rejects.toThrow(/covered/);
  });

  for (const viewport of viewports) {
    test(`@combined-fixture Hermes ${fixtureName} semantic status ${viewport.name}`, async ({
      page,
    }) => {
      const { externalRequests, problems } = await openFixturePage(
        page,
        viewport,
        expectedState,
      );
      await assertWholeHermesShellSemanticStatus(page);
      expectCleanBrowser(externalRequests, problems);
    });

    test(`@combined-fixture Hermes ${fixtureName} control boundaries ${viewport.name}`, async ({
      page,
    }) => {
      const { externalRequests, problems } = await openFixturePage(
        page,
        viewport,
        expectedState,
      );
      await assertWholeHermesShellControlsUnclipped(page);
      expectCleanBrowser(externalRequests, problems);
    });

    test(`@combined-fixture Hermes ${fixtureName} WCAG contrast ${viewport.name}`, async ({
      page,
    }) => {
      const { externalRequests, problems } = await openFixturePage(
        page,
        viewport,
        expectedState,
      );
      await assertWholeHermesShellWcagAaContrast(page);
      expectCleanBrowser(externalRequests, problems);
    });
  }
}
