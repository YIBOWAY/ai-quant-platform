import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const source = readFileSync(
  path.join(process.cwd(), "components/hermes/desk/HermesDeskChatRail.tsx"),
  "utf8",
);

describe("HermesDeskChatRail", () => {
  it("is one free-text Hermes composer, not a gated intake form", () => {
    expect(source).toContain("ComposerSubmitController");
    expect(source).toContain("networkSubmit");
    expect(source).toContain("第一条消息会自动开对话");
    expect(source).toContain("粘贴论文链接，描述策略，或问一个市场问题");
    expect(source).not.toContain("可证伪公式");
    expect(source).not.toContain("材料闸");
    expect(source).not.toContain("至少 8");
    expect(source).not.toContain("/api/assistant/remote/intake");
    expect(source).not.toContain("/api/assistant/remote/dispatch");
    expect(source).not.toMatch(
      /<ComposerSubmitController[\s\S]*?allowSubmit=\{false\}/,
    );
  });

  it("welcomes natural research requests without exposing internal intake contracts", () => {
    expect(source).not.toContain(
      "派研究或挂仓写在同一条输入里，不必先填公式或股票池",
    );
    expect(source).not.toContain(
      "Research or hang goes in this same box. No formula or universe first.",
    );
    expect(source).toContain("把论文链接、策略描述或市场问题发给本机 Hermes");
    expect(source).toContain("规则不完整时会追问");
    expect(source).toContain("我的模拟策略最近表现怎么样");
    expect(source).not.toContain("已挂策略和效果");
    expect(source).not.toContain("启用模拟运行仍须去候选库用来源指纹确认");
    expect(source).not.toContain("进入模拟盘仍须去候选库另下 digest 绑定命令");
    expect(source).toContain("Send your local Hermes");
    expect(source).toContain("Research and simulation updates stay in this conversation");
    expect(source).toContain("/hermes?hermes_session_id=");
  });

  it("projects Platform research status beside, never into, the Hermes transcript", () => {
    expect(source).toContain("selectPlatformResearchResult");
    expect(source).toContain("PlatformResearchResultCard");
    expect(source).toContain('apiRequestOnce<RemoteBook>("/api/assistant/remote/book")');
    expect(source).toContain("retry: false");
    expect(source).toContain("session?.hermesSessionId");
    expect(source).not.toContain("apiPost");
    expect(source.indexOf("WorkbenchTranscriptPanel")).toBeLessThan(
      source.indexOf("PlatformResearchResultCard"),
    );
  });

  it("keeps the recent-session disclosure and links at the shared 44px target", () => {
    expect(source).toMatch(/<summary className="app-touch-target/);
    expect(source).toMatch(/<a[\s\S]*?className="app-touch-target/);
    expect(source).not.toContain('from "next/link"');
  });

  it("shows user-facing run and connection activity without raw tool detail", () => {
    expect(source).toContain("useWorkspaceFollow");
    expect(source).toContain("selectChatCommand");
    expect(source).toContain("/activity");
    expect(source).toContain("data-hermes-run-activity");
    expect(source.indexOf("data-hermes-run-activity")).toBeGreaterThan(
      source.indexOf("WorkbenchTranscriptPanel"),
    );
    expect(source).toContain('role="progressbar"');
    expect(source).toContain("Sparkles");
    expect(source).not.toContain("Loader2");
    expect(source).toContain('role="status"');
    expect(source).toContain('aria-live="polite"');
    expect(source).toContain('aria-atomic="true"');
    expect(source).toContain("activityActive &&");
    expect(source).toContain("(!isMobile || chatRailOpen)");
    expect(source).toContain("queryFn: ({ signal })");
    expect(source).toContain("signal,");
    expect(source).toContain("activity.tool_state !== \"active\"");
    expect(source).not.toContain("tool.args");
    expect(source).not.toContain("tool.output");
    expect(source).not.toContain("reasoning.text");
  });

  it("supports a keyboard-accessible desktop rail resizer and hides raw empty-session ids", () => {
    expect(source).toContain('role="separator"');
    expect(source).toContain('aria-orientation="vertical"');
    expect(source).toContain("setPointerCapture");
    expect(source).toContain('style.setProperty("--dp-rail-chat"');
    expect(source).toContain("setRailWidth(pendingRailWidthRef.current)");
    expect(source).toContain('event.key === "ArrowLeft"');
    expect(source).toContain('event.key === "ArrowRight"');
    expect(source).toContain("Math.min(MAX_RAIL_WIDTH");
    expect(source).toContain("未命名新对话");
    expect(source).not.toContain("session.title || session.preview || session.id");
  });
});
