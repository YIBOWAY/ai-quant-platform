import { expect, test, type Page, type Request } from "@playwright/test";

type Diagnostics = {
  automaticRscRequests: string[];
  consoleErrors: string[];
  failedRequests: string[];
  httpErrors: string[];
  pageErrors: string[];
};

function installDiagnostics(page: Page): Diagnostics & {
  beginDeliberateNavigation: () => void;
} {
  const diagnostics: Diagnostics = {
    automaticRscRequests: [],
    consoleErrors: [],
    failedRequests: [],
    httpErrors: [],
    pageErrors: [],
  };
  let deliberateNavigation = false;

  page.on("console", (message) => {
    if (message.type() === "error") {
      diagnostics.consoleErrors.push(message.text());
    }
  });
  page.on("pageerror", (error) => diagnostics.pageErrors.push(error.message));
  page.on("request", (request: Request) => {
    if (!deliberateNavigation && request.url().includes("_rsc=")) {
      diagnostics.automaticRscRequests.push(request.url());
    }
  });
  page.on("requestfailed", (request: Request) => {
    diagnostics.failedRequests.push(
      `${request.method()} ${request.url()} ${request.failure()?.errorText ?? "unknown"}`,
    );
  });
  page.on("response", (response) => {
    if (response.status() >= 400) {
      diagnostics.httpErrors.push(
        `${response.status()} ${response.request().method()} ${response.url()}`,
      );
    }
  });

  return {
    ...diagnostics,
    beginDeliberateNavigation: () => {
      deliberateNavigation = true;
    },
  };
}

test("production Hermes navigation has no background RSC prefetch or aborted request", async ({
  page,
}) => {
  const diagnostics = installDiagnostics(page);

  await page.goto("/zh/hermes", { waitUntil: "networkidle" });
  await expect(page.locator("#hermes-today-title")).toBeVisible();
  await expect(page.getByTestId("global-safety-strip")).toHaveAttribute(
    "aria-label",
    /仅模拟.*实盘交易已禁用.*熔断开关 开.*接口 available/,
  );
  await page.waitForTimeout(1_000);
  expect(diagnostics.automaticRscRequests).toEqual([]);

  diagnostics.beginDeliberateNavigation();
  await page
    .getByRole("navigation", { name: /Hermes 工作台|Hermes workbench/ })
    .getByRole("link", { name: /任务|Tasks/ })
    .click();
  await expect(page).toHaveURL(/\/zh\/hermes\/tasks$/);
  await page.waitForLoadState("networkidle");

  expect(diagnostics.consoleErrors).toEqual([]);
  expect(diagnostics.pageErrors).toEqual([]);
  expect(diagnostics.failedRequests).toEqual([]);
  expect(diagnostics.httpErrors).toEqual([]);
});
