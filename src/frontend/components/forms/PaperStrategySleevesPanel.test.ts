import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const source = readFileSync(
  path.join(process.cwd(), "components/forms/PaperStrategySleevesPanel.tsx"),
  "utf8",
);

describe("PaperStrategySleevesPanel product wording", () => {
  it("keeps internal hang identity out of visible copy", () => {
    expect(source).toContain("正式模拟策略");
    expect(source).toContain("待恢复启用");
    expect(source).toContain("Official simulated strategies");
    expect(source).toContain("Pending activation recovery");
    expect(source).not.toContain("已挂上的");
    expect(source).not.toContain("正式已挂策略");
    expect(source).not.toContain("待完成挂仓");
    expect(source).not.toContain("Official hung strategies");
    expect(source).not.toContain("Pending hang recovery");
  });

  it("localizes legacy config names before displaying options", () => {
    expect(source).toContain("strategyConfigDisplayName(config.name, locale)");
  });
});
