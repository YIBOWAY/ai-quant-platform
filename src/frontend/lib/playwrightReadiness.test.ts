import { afterEach, describe, expect, it, vi } from "vitest";

const ENVIRONMENT_NAMES = [
  "PW_E2E",
  "PW_HERMES_WORKBENCH_FIXTURE",
  "PW_BACKEND_PORT",
  "PW_FRONTEND_PORT",
  "PW_REUSE_SERVER",
  "PW_HERMES_ROLLBACK_E2E",
  "PW_HERMES_ROLLBACK_PORT",
  "QUANT_API_COMMAND",
] as const;

const originalEnvironment = new Map(
  ENVIRONMENT_NAMES.map((name) => [name, process.env[name]]),
);

afterEach(() => {
  for (const name of ENVIRONMENT_NAMES) {
    const original = originalEnvironment.get(name);
    if (original === undefined) {
      delete process.env[name];
    } else {
      process.env[name] = original;
    }
  }
  vi.resetModules();
});

describe("Playwright backend readiness", () => {
  it("binds the active normal-fixture webServer URL to a provider-free route", async () => {
    process.env.PW_E2E = "1";
    process.env.PW_HERMES_WORKBENCH_FIXTURE = "normal";
    process.env.PW_BACKEND_PORT = "18766";
    process.env.PW_FRONTEND_PORT = "13002";
    delete process.env.PW_REUSE_SERVER;
    delete process.env.PW_HERMES_ROLLBACK_E2E;
    delete process.env.PW_HERMES_ROLLBACK_PORT;
    delete process.env.QUANT_API_COMMAND;
    vi.resetModules();

    const { default: config } = await import("../playwright.config");
    const webServers = Array.isArray(config.webServer)
      ? config.webServer
      : config.webServer
        ? [config.webServer]
        : [];
    const activeUrls = webServers.map((server) => server.url);

    expect(activeUrls[0]).toBe(
      "http://127.0.0.1:18766/api/hermes/gateway",
    );
    expect(activeUrls).not.toContain(
      "http://127.0.0.1:18766/api/health",
    );
    expect(
      activeUrls.map((url) => new URL(url!).pathname),
    ).not.toContain("/api/health");
  });
});
