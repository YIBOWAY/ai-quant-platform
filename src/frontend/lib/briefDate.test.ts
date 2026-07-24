import { describe, expect, it } from "vitest";
import { briefDateKey } from "./briefDate";

describe("briefDateKey", () => {
  it("uses the Asia/Shanghai civil date across the UTC day boundary", () => {
    expect(briefDateKey(new Date("2026-07-13T15:59:59Z"))).toBe("2026-07-13");
    expect(briefDateKey(new Date("2026-07-13T16:00:00Z"))).toBe("2026-07-14");
    expect(briefDateKey(new Date("2026-07-14T00:30:00+08:00"))).toBe("2026-07-14");
  });
});
