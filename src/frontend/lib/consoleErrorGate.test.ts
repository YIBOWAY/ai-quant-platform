import type { Page } from "@playwright/test";
import { describe, expect, it } from "vitest";

import {
  browserErrorMessages,
  collectBrowserErrors,
} from "../tests/e2e/helpers/console-error-gate";

type Listener = (value: never) => void;

class FakePage {
  private readonly listeners = new Map<string, Listener[]>();

  on(event: string, listener: Listener) {
    const listeners = this.listeners.get(event) ?? [];
    listeners.push(listener);
    this.listeners.set(event, listeners);
    return this;
  }

  emit(event: string, value: unknown) {
    for (const listener of this.listeners.get(event) ?? []) {
      listener(value as never);
    }
  }
}

function request(url: string, method = "GET", failureText?: string) {
  return {
    failure: () => (failureText ? { errorText: failureText } : null),
    method: () => method,
    url: () => `http://127.0.0.1:3001${url}`,
  };
}

describe("browser error gate", () => {
  it("reports React console errors, page errors, unregistered 5xx, and request failures", () => {
    const fake = new FakePage();
    const gate = collectBrowserErrors(fake as unknown as Page);

    fake.emit("console", {
      location: () => ({ url: "http://127.0.0.1:3001/en/hermes" }),
      text: () => "Warning: React duplicate key",
      type: () => "error",
    });
    fake.emit("pageerror", new Error("render exploded"));
    const failedResponseRequest = request("/api/unexpected", "GET");
    fake.emit("response", {
      request: () => failedResponseRequest,
      status: () => 500,
      url: () => failedResponseRequest.url(),
    });
    fake.emit(
      "requestfailed",
      request("/api/unexpected-abort", "POST", "net::ERR_CONNECTION_RESET"),
    );

    expect(browserErrorMessages(gate)).toEqual([
      "console: Warning: React duplicate key",
      "pageerror: render exploded",
      "response: 500 GET /api/unexpected",
      "requestfailed: POST /api/unexpected-abort net::ERR_CONNECTION_RESET",
    ]);
  });

  it("consumes resource-console noise only after the exact allowed failure is observed", () => {
    const fake = new FakePage();
    const gate = collectBrowserErrors(fake as unknown as Page, [
      { method: "GET", status: 503, url: "/api/expected" },
    ]);
    fake.emit("console", {
      location: () => ({ url: "" }),
      text: () => "Failed to load resource: the server responded with a status of 503",
      type: () => "error",
    });
    expect(browserErrorMessages(gate)).toHaveLength(1);

    const expectedRequest = request("/api/expected", "GET");
    fake.emit("response", {
      request: () => expectedRequest,
      status: () => 503,
      url: () => expectedRequest.url(),
    });
    expect(browserErrorMessages(gate)).toEqual([]);

    fake.emit("console", {
      location: () => ({ url: "http://127.0.0.1:3001/api/unexpected" }),
      text: () => "Failed to load resource: the server responded with a status of 500",
      type: () => "error",
    });
    expect(browserErrorMessages(gate)).toEqual([
      "console: Failed to load resource: the server responded with a status of 500 @ /api/unexpected",
    ]);
  });

  it("allows an aborted RSC body only after an exact one-key RSC URL returned 200", () => {
    const fake = new FakePage();
    const gate = collectBrowserErrors(fake as unknown as Page, [
      {
        failureText: "net::ERR_ABORTED",
        method: "GET",
        responseStatus: 200,
        rscPathname: "/en/hermes/sessions/session-1",
      },
    ]);
    const rscRequest = request(
      "/en/hermes/sessions/session-1?_rsc=opaque",
      "GET",
      "net::ERR_ABORTED",
    );
    fake.emit("response", {
      request: () => rscRequest,
      status: () => 200,
      url: () => rscRequest.url(),
    });
    fake.emit("requestfailed", rscRequest);
    expect(browserErrorMessages(gate)).toEqual([]);

    const unexpectedFake = new FakePage();
    const unexpectedGate = collectBrowserErrors(unexpectedFake as unknown as Page, [
      {
        failureText: "net::ERR_ABORTED",
        method: "GET",
        responseStatus: 200,
        rscPathname: "/en/hermes/sessions/session-1",
      },
    ]);
    const extraQueryRequest = request(
      "/en/hermes/sessions/session-1?_rsc=opaque&extra=1",
      "GET",
      "net::ERR_ABORTED",
    );
    unexpectedFake.emit("response", {
      request: () => extraQueryRequest,
      status: () => 200,
      url: () => extraQueryRequest.url(),
    });
    unexpectedFake.emit("requestfailed", extraQueryRequest);
    expect(browserErrorMessages(unexpectedGate)).toEqual([
      "requestfailed: GET /en/hermes/sessions/session-1?_rsc=opaque&extra=1 net::ERR_ABORTED",
    ]);
  });

  it("still reports an aborted RSC when no 200 was observed on that request first", () => {
    const fake = new FakePage();
    const gate = collectBrowserErrors(fake as unknown as Page, [
      {
        failureText: "net::ERR_ABORTED",
        method: "GET",
        responseStatus: 200,
        rscPathname: "/zh/hermes/results",
      },
    ]);
    fake.emit(
      "requestfailed",
      request("/zh/hermes/results?_rsc=opaque", "GET", "net::ERR_ABORTED"),
    );
    expect(browserErrorMessages(gate)).toEqual([
      "requestfailed: GET /zh/hermes/results?_rsc=opaque net::ERR_ABORTED",
    ]);
  });

  it("allows the production Hermes navigation RSC to abort after its 200 headers", () => {
    const fake = new FakePage();
    const gate = collectBrowserErrors(fake as unknown as Page, [
      {
        failureText: "net::ERR_ABORTED",
        method: "GET",
        responseStatus: 200,
        rscPathname: "/zh/hermes/results",
      },
    ]);
    const rscRequest = request(
      "/zh/hermes/results?_rsc=epnqq",
      "GET",
      "net::ERR_ABORTED",
    );
    fake.emit("response", {
      request: () => rscRequest,
      status: () => 200,
      url: () => rscRequest.url(),
    });
    fake.emit("requestfailed", rscRequest);
    expect(browserErrorMessages(gate)).toEqual([]);
  });
});
