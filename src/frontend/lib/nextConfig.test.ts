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
});
