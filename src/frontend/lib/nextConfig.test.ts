import { describe, expect, it } from "vitest";

import nextConfig from "../next.config";

describe("Next locale rewrites", () => {
  it("strips explicit locale prefixes through relative internal rewrites", async () => {
    expect(nextConfig.rewrites).toBeTypeOf("function");
    const rewrites = await nextConfig.rewrites!();

    expect(rewrites).toEqual(
      expect.arrayContaining([
        { source: "/en/:path*", destination: "/:path*" },
        { source: "/zh/:path*", destination: "/:path*" },
      ]),
    );
  });

  it("proxies same-origin /api calls to the local backend", async () => {
    expect(nextConfig.rewrites).toBeTypeOf("function");
    const rewrites = await nextConfig.rewrites!();

    expect(rewrites).toContainEqual({
      source: "/api/:path*",
      destination: "http://127.0.0.1:8765/api/:path*",
    });
  });
});

describe("OP4 route consolidation redirects", () => {
  it("uses exact 301 redirects for watch aliases and merged product pages", async () => {
    expect(nextConfig.redirects).toBeTypeOf("function");
    const redirects = await nextConfig.redirects!();
    const expected = [
      ["/data-explorer", "/watch?pane=quotes"],
      ["/market-cross-section", "/watch?pane=cross"],
      ["/asia-radar", "/watch?pane=radar"],
      ["/position-map", "/paper-trading?view=map"],
      ["/hermes/sessions", "/hermes"],
    ] as const;

    for (const prefix of ["", "/en", "/zh"] as const) {
      for (const [source, destination] of expected) {
        expect(redirects).toContainEqual({
          source: `${prefix}${source}`,
          destination: `${prefix}${destination}`,
          statusCode: 301,
        });
      }
    }
  });
});
