import { expect, type Page } from "@playwright/test";

export type AllowedBrowserFailure =
  | {
      method: string;
      status: number;
      url: string;
    }
  | {
      failureText: string;
      method: string;
      url: string;
    }
  | {
      failureText: string;
      method: string;
      responseStatus: number;
      rscPathname: string;
    };

type ObservedAllowedFailure = {
  url: string;
};

type ResourceConsoleError = {
  locationUrl: string;
  text: string;
};

export type BrowserErrorGate = {
  allowedFailures: ObservedAllowedFailure[];
  problems: string[];
  resourceConsoleErrors: ResourceConsoleError[];
  successfulRscRequests: WeakSet<object>;
};

function relativeUrl(rawUrl: string): string {
  try {
    const parsed = new URL(rawUrl);
    return `${parsed.pathname}${parsed.search}`;
  } catch {
    return rawUrl;
  }
}

function normalizedMethod(method: string): string {
  return method.toUpperCase();
}

function isExactRscUrl(rawUrl: string, pathname: string): boolean {
  try {
    const parsed = new URL(rawUrl);
    const queryKeys = [...parsed.searchParams.keys()];
    return (
      parsed.pathname === pathname &&
      queryKeys.length === 1 &&
      queryKeys[0] === "_rsc" &&
      Boolean(parsed.searchParams.get("_rsc"))
    );
  } catch {
    return false;
  }
}

/**
 * Installs a browser-error gate before navigation. A mocked network failure is
 * allowed only when the spec names its exact relative URL, method, and status
 * (or Chromium failure text). Everything else remains a test failure.
 */
export function collectBrowserErrors(
  page: Page,
  allowed: readonly AllowedBrowserFailure[] = [],
): BrowserErrorGate {
  const gate: BrowserErrorGate = {
    allowedFailures: [],
    problems: [],
    resourceConsoleErrors: [],
    successfulRscRequests: new WeakSet<object>(),
  };

  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const text = message.text();
    if (text.startsWith("Failed to load resource:")) {
      gate.resourceConsoleErrors.push({
        locationUrl: relativeUrl(message.location().url),
        text,
      });
      return;
    }
    gate.problems.push(`console: ${text}`);
  });
  page.on("pageerror", (error) => {
    gate.problems.push(`pageerror: ${error.message}`);
  });
  page.on("response", (response) => {
    const status = response.status();
    const request = response.request();
    const rawUrl = response.url();
    const url = relativeUrl(rawUrl);
    const method = normalizedMethod(request.method());
    const permittedRscResponse = allowed.some(
      (item) =>
        "rscPathname" in item &&
        normalizedMethod(item.method) === method &&
        item.responseStatus === status &&
        isExactRscUrl(rawUrl, item.rscPathname),
    );
    if (permittedRscResponse) {
      gate.successfulRscRequests.add(request);
    }
    if (status < 400) return;
    const permitted = allowed.some(
      (item) =>
        "status" in item &&
        item.url === url &&
        normalizedMethod(item.method) === method &&
        item.status === status,
    );
    if (permitted) {
      gate.allowedFailures.push({ url });
      return;
    }
    gate.problems.push(`response: ${status} ${method} ${url}`);
  });
  page.on("requestfailed", (request) => {
    const url = relativeUrl(request.url());
    const method = normalizedMethod(request.method());
    const failureText = request.failure()?.errorText ?? "unknown";
    const permittedExactFailure = allowed.some(
      (item) =>
        "failureText" in item &&
        "url" in item &&
        item.url === url &&
        normalizedMethod(item.method) === method &&
        item.failureText === failureText,
    );
    const permittedCompletedRsc = allowed.some(
      (item) =>
        "rscPathname" in item &&
        gate.successfulRscRequests.has(request) &&
        normalizedMethod(item.method) === method &&
        item.failureText === failureText &&
        isExactRscUrl(request.url(), item.rscPathname),
    );
    if (permittedExactFailure || permittedCompletedRsc) {
      gate.allowedFailures.push({ url });
      return;
    }
    gate.problems.push(`requestfailed: ${method} ${url} ${failureText}`);
  });

  return gate;
}

export function browserErrorMessages(gate: BrowserErrorGate): string[] {
  const unconsumedAllowed = [...gate.allowedFailures];
  const resourceProblems: string[] = [];
  for (const error of gate.resourceConsoleErrors) {
    const exactIndex = unconsumedAllowed.findIndex(
      (failure) => failure.url === error.locationUrl,
    );
    const fallbackIndex = exactIndex >= 0 ? exactIndex : error.locationUrl ? -1 : 0;
    if (unconsumedAllowed.length === 0 || fallbackIndex < 0) {
      resourceProblems.push(
        `console: ${error.text}${error.locationUrl ? ` @ ${error.locationUrl}` : ""}`,
      );
      continue;
    }
    unconsumedAllowed.splice(fallbackIndex, 1);
  }
  return [...gate.problems, ...resourceProblems];
}

export function expectNoBrowserErrors(gate: BrowserErrorGate): void {
  const problems = browserErrorMessages(gate);
  expect(
    problems,
    `unexpected browser errors: ${problems.join(" | ")}`,
  ).toEqual([]);
}
