import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const source = readFileSync(
  path.join(process.cwd(), "components/dashboard/LegacyDashboard.tsx"),
  "utf8",
);

describe("legacy dashboard quick actions", () => {
  it("labels the agent-studio link as read-only inspection, not task creation", () => {
    expect(source).toContain('viewAgents: "View Agent Candidates"');
    expect(source).toContain('viewAgents: "查看智能体候选"');
    expect(source).toContain("{text.viewAgents}");
    expect(source).toContain('localizePath("/agent-studio", locale)');
    expect(source).not.toContain("New Agent Task");
    expect(source).not.toContain("新建智能体任务");
  });
});

describe("legacy dashboard run timestamps", () => {
  it("formats run timestamps in the active locale instead of hardcoded en-US", () => {
    expect(source).toContain(
      'locale === "zh" ? "zh-CN" : "en-US"',
    );
    expect(source).toContain("formatRunTimestamp(run.created_at, locale)");
  });
});
