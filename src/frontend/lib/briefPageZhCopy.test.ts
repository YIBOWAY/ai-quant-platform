import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

function readBriefPage() {
  return readFileSync(path.join(process.cwd(), "app/brief/page.tsx"), "utf8");
}

describe("/brief zh copy honesty", () => {
  it("translates the safety line and live-trading footer without weakening them", () => {
    const source = readBriefPage();

    expect(source).toContain(
      'safetyLine: "本页展示模拟账户与研究信息，未启用实盘交易"',
    );
    expect(source).toContain('liveTrading: "实盘交易"');
    expect(source).toContain('neverActive: "绝不暗示已启用"');
    expect(source).not.toContain(
      'safetyLine: "本刊为模拟盘刊物 · DRY-RUN 演练 · live trading never implied active"',
    );
  });

  it("localizes the settings availability status", () => {
    const source = readBriefPage();

    expect(source).toContain('available: "available"');
    expect(source).toContain('available: "可用"');
    expect(source).toContain("settingsSafety ? text.available : text.unavailable");
    expect(source).not.toContain('settingsSafety ? "available" : "unavailable"');
  });

  it("branches news timestamps by locale", () => {
    const source = readBriefPage();

    expect(source).toContain(
      'function formatTimestamp(value: string | null | undefined, locale: "en" | "zh")',
    );
    expect(source).toContain("formatTimestamp(item.published_at, locale)");
    expect(source).not.toContain("formatTimestamp(item.published_at)}");
  });

  it("marks the printed-brief log entry as informational instead of a warning", () => {
    const source = readBriefPage();

    expect(source).toContain('status: "ok" | "warn" | "info"');
    expect(source).toContain('status: "info"');
    expect(source).not.toContain('status: "warn",\n    text: locale === "zh" ? "晨报已排印');
  });
});
