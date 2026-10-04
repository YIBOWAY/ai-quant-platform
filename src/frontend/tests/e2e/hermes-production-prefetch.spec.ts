import { readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { expect, test, type Page, type Request } from "@playwright/test";
import {
  collectBrowserErrors,
  expectNoBrowserErrors,
} from "./helpers/console-error-gate";
import { installRscCancellationDiagnostic } from "./helpers/rsc-cancellation-diagnostic";

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

test("@production-prefetch production Hermes navigation has no background RSC prefetch or aborted request", async ({
  page,
}, testInfo) => {
  expect(process.env.PW_PRODUCTION_FRONTEND, "This contract must use Next build/start, not development HMR").toBe("1");
  const finishDiagnostic = await installRscCancellationDiagnostic(page);
  const diagnostics = installDiagnostics(page);
  // Chromium reports a Next.js RSC navigation whose response headers arrived
  // (200) but whose body stream was cancelled as `requestfailed
  // net::ERR_ABORTED`. That is the whitelisted benign-cancellation shape the
  // shared console-error gate already models: a 200 on the exact one-key RSC
  // URL permits the later abort of the same request. Anything else — an abort
  // with no preceding 200, extra query keys, a different pathname — still
  // fails through the gate.
  const cancelledRscFailureText = "net::ERR_ABORTED";
  const browserErrors = collectBrowserErrors(page, [
    {
      failureText: cancelledRscFailureText,
      method: "GET",
      responseStatus: 200,
      rscPathname: "/zh/hermes/results",
    },
  ]);
  const targetRsc = (request: Request) => {
    const url = new URL(request.url());
    return url.pathname === "/zh/hermes/results" && url.searchParams.has("_rsc") && [...url.searchParams.keys()].every(key => key === "_rsc");
  };
  let terminal: string | null = null;
  page.on("requestfinished", request => { if (targetRsc(request)) terminal = "finished"; });
  page.on("requestfailed", request => {
    if (!targetRsc(request)) return;
    const errorText = request.failure()?.errorText ?? "failed";
    terminal =
      errorText === cancelledRscFailureText &&
      browserErrors.successfulRscRequests.has(request)
        ? "completed-200-aborted"
        : errorText;
  });

  // Navigation is the subject here, not a live market connection. The OS
  // sandbox rejects OpenD; keep that separate unavailable-source test intact
  // and supply no prices on this read seam. Never render it as Futu data.
  if (process.env.PW_RSC_NO_ROUTE !== "1") await page.route("**/api/market-data/history?*", route => {
    const ticker = new URL(route.request().url()).searchParams.get("ticker");
    return route.fulfill({ json: { symbol: ticker, ticker, source: "e2e-unavailable", frequency: "1d", row_count: 0, rows: [],
      metadata: { provider: "e2e-unavailable", requested_provider: "futu", fetched_at: null } } });
  });

  await page.goto("/zh/hermes", { waitUntil: "networkidle" });
  await expect(page.locator("#hermes-ledger-panel")).toBeVisible();
  const buildRoot = path.join(process.cwd(), ".tmp", `e2e-frontend-${process.env.PW_FRONTEND_PORT}`);
  const buildIdPath = path.join(buildRoot, ".next", "BUILD_ID");
  const html = await page.content();
  const viewAllClass = await page.locator('a[href="/zh/hermes/results"]').getAttribute("class");
  const tableMinWidth = await page.locator('.dp-blotter[data-ledger="duty"] table').evaluate(node => getComputedStyle(node).minWidth);
  expect(viewAllClass).not.toContain("-my-[13px]"); expect(tableMinWidth).toBe("0px");
  await testInfo.attach("production-build-identity.json", { body: JSON.stringify({
    build_id: readFileSync(buildIdPath, "utf8"), build_modified_at: statSync(buildIdPath).mtime.toISOString(),
    source_fingerprint: readFileSync(path.join(buildRoot, ".source-fingerprint"), "utf8"),
    html_sha256: createHash("sha256").update(html).digest("hex"), view_all_class: viewAllClass, duty_table_min_width: tableMinWidth,
  }, null, 2), contentType: "application/json" });
  await testInfo.attach("production-document.html", { body: html, contentType: "text/html" });
  await expect(page.getByTestId("global-safety-strip")).toHaveAttribute(
    "aria-label",
    /仅模拟.*实盘交易已禁用.*熔断开关 开.*接口 可用/,
  );
  const prefetchObservationStartedAt = Date.now();
  await expect
    .poll(
      () =>
        diagnostics.automaticRscRequests.length === 0 &&
        Date.now() - prefetchObservationStartedAt >= 1_000,
      {
        message:
          "Hermes must remain free of automatic RSC requests throughout the bounded observation window",
        timeout: 10_000,
        intervals: [100, 250, 500],
      },
    )
    .toBe(true);
  expect(diagnostics.automaticRscRequests).toEqual([]);

  diagnostics.beginDeliberateNavigation();
  await page.locator('a[href="/zh/hermes/results"]').click();
  await expect(page).toHaveURL(/\/zh\/hermes\/results$/);
  await expect(page.locator("[data-hermes-results-index]")).toBeVisible();
  await expect(page.getByRole("heading", { name: "统一结果", exact: true })).toBeVisible();
  const catalogResponse = await page.request.get("/api/hermes/results");
  expect(catalogResponse.status()).toBe(200);
  const catalog = await catalogResponse.json();
  await expect(page.locator("[data-hermes-result-key]")).toHaveCount(catalog.items.length);
  await expect.poll(() => terminal, { message: "Wait for the actual navigation RSC terminal event" }).not.toBeNull();
  await finishDiagnostic(testInfo);
  expect(
    ["finished", "completed-200-aborted"],
    "the navigation RSC must reach a whitelisted terminal state",
  ).toContain(terminal);

  const diagnosticPayload = JSON.stringify(
    {
      automatic_rsc_request_count: diagnostics.automaticRscRequests.length,
      console_error_count: diagnostics.consoleErrors.length,
      failed_request_count: diagnostics.failedRequests.length,
      http_error_count: diagnostics.httpErrors.length,
      page_error_count: diagnostics.pageErrors.length,
      rsc_err_aborted_count: diagnostics.failedRequests.filter(
        (value) => value.includes("_rsc=") && value.includes("ERR_ABORTED"),
      ).length,
    },
    null,
    2,
  );
  await testInfo.attach("attempt5-browser-diagnostics.json", {
    body: Buffer.from(diagnosticPayload),
    contentType: "application/json",
  });
  const diagnosticPath = process.env.PW_ATTEMPT5_DIAGNOSTICS_PATH;
  if (diagnosticPath) {
    writeFileSync(diagnosticPath, `${diagnosticPayload}\n`, {
      encoding: "utf8",
      flag: "wx",
      mode: 0o600,
    });
  }

  expectNoBrowserErrors(browserErrors);
});
