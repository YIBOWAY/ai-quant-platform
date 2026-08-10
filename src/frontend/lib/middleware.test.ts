import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { middleware } from "../middleware";

describe("locale middleware", () => {
  it("injects the explicit locale without emitting an absolute rewrite", () => {
    const request = new NextRequest("http://localhost:3001/zh/brief", {
      headers: { host: "127.0.0.1:3001" },
    });

    const response = middleware(request);

    expect(response.headers.get("x-middleware-next")).toBe("1");
    expect(response.headers.get("x-middleware-rewrite")).toBeNull();
    expect(response.headers.get("x-middleware-request-x-qs-locale")).toBe("zh");
  });
});
