import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const root = process.cwd();
const source = (relative: string) =>
  readFileSync(path.join(root, relative), "utf8");

describe("OP4 consolidated surfaces", () => {
  it("merges Position Map into paper account and preserves its inner tab query", () => {
    const paper = source("app/paper-trading/page.tsx");
    const workspace = source("components/position-map/PositionMapWorkspace.tsx");
    expect(paper).toContain('view === "map"');
    expect(paper).toContain("PositionMapPageContent");
    expect(workspace).toContain('params.set("view", "map")');
    expect(workspace).toContain('params.set("tab", next)');
    expect(workspace).not.toContain("`?tab=${next}`");
  });

  it("puts recent sessions in chat while retaining only session detail as a deep route", () => {
    const chat = source("components/hermes/desk/HermesDeskChatRail.tsx");
    expect(chat).toContain("/api/hermes/sessions?limit=");
    expect(chat).toContain("/hermes?hermes_session_id=${encodeURIComponent(session.id)}");
    expect(existsSync(path.join(root, "app/hermes/sessions/page.tsx"))).toBe(false);
    expect(existsSync(path.join(root, "app/hermes/sessions/[sessionId]/page.tsx"))).toBe(true);
  });

  it("removes dead desks, aliases, tasks and preview sources without breaking desk CSS", () => {
    for (const relative of [
      "components/desk/OfficialDesk.tsx",
      "components/hermes/shell/HermesInternalNav.tsx",
      "components/hermes/today/HermesTodayView.tsx",
      "app/desk/page.tsx",
      "app/desk-preview/page.tsx",
      "app/data-explorer/page.tsx",
      "app/market-cross-section/page.tsx",
      "app/asia-radar/page.tsx",
      "app/position-map/page.tsx",
      "app/hermes/tasks/page.tsx",
    ]) {
      expect(existsSync(path.join(root, relative)), relative).toBe(false);
    }
    const deskCss = source("components/hermes/desk/hermes-desk.css");
    expect(deskCss).not.toContain("app/desk-preview");
    expect(deskCss).toContain("desk-foundation.css");
  });

  it("uses the owner-approved current labels", () => {
    const sidebar = source("components/Sidebar.tsx");
    const topbar = source("components/TopBar.tsx");
    const today = source("components/hermes/desk/HermesDeskToday.tsx");
    expect(sidebar).toContain('hermes: "Hermes 助手"');
    expect(topbar).toContain('openHermes: "打开 Hermes 助手"');
    for (const label of [
      "市场研判",
      "日报",
      "模拟账户",
      "期权筛选",
      "期权推荐",
      "买方期权",
      "设置",
    ]) {
      expect(sidebar).toContain(`"${label}"`);
      expect(topbar).toContain(`"${label}"`);
    }
    expect(`${sidebar}\n${topbar}\n${today}`).not.toContain("Hermes 工作台");
    expect(`${sidebar}\n${topbar}\n${today}`).not.toContain("值班盯盘");
  });
});
