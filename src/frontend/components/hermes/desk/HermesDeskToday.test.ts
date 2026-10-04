import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const source = readFileSync(
  path.join(process.cwd(), "components/hermes/desk/HermesDeskToday.tsx"),
  "utf8",
);
const blotterCss = readFileSync(
  path.join(process.cwd(), "components/hermes/desk/desk-foundation.css"),
  "utf8",
);

describe("HermesDeskToday rail", () => {
  it("hosts one free-text conversation and no gated remote form", () => {
    expect(source).not.toContain("可证伪公式");
    expect(source).not.toContain("材料闸必填");
    expect(source).not.toContain("材料入账");
    expect(source).not.toContain("公开 composer 关");
    expect(source).not.toContain("/api/assistant/remote/intake");
    expect(source).not.toContain("/api/assistant/remote/dispatch");
    expect(source).toContain("HermesDeskChatRail");
    // Slim hero: no decorative kicker duplicating the ledger tabs and rail.
    expect(source).toContain("dp-hero-title");
    expect(source).not.toContain("对话在右边");
  });

  it("keeps hung-sleeve effect on the paper tab and off research", () => {
    expect(source).toContain("1 条模拟运行中 · 观察日 0 · 等第一个观察夜");
    expect(source).toContain('data-hung-effect');
    expect(source).toContain('enabled: ledger === "paper"');
    expect(source).toContain('ledger === "paper"');
    const researchOnly = source.includes("data-hung-effect") && source.includes('ledger === "research"');
    expect(researchOnly).toBe(true);
    const effectBlock = source.slice(source.indexOf("data-hung-effect"));
    expect(effectBlock).not.toContain("账户库存");
    expect(effectBlock).toContain("策略净值");
    expect(effectBlock).toContain("sleeve_equity_status");
    expect(effectBlock).toContain("spy_status");
    expect(effectBlock).toContain("不可用");
  });

  it("keeps fossil English objectives inside technical details on Chinese pages", () => {
    expect(source).toContain("历史测试仓，不计入策略效果。");
    expect(source).toContain("原始研究目标");
    expect(source).not.toContain("{item.objective ||\n                            (isZh");
  });

  it("shows yesterday absence on duty only and never on research", () => {
    expect(source).toContain('data-observation-yesterday="absent"');
    expect(source).toContain('昨日观察：缺席（未运行）');
    expect(source).toContain('calendarQuery.data?.yesterday.status === "absent"');
    expect(source).toContain('enabled: ledger === "duty"');
    const researchBlock = source.slice(source.indexOf('ledger === "research"'));
    expect(researchBlock).not.toContain("data-observation-yesterday");
  });

  it("surfaces a ran calendar whose signal data was unavailable", () => {
    expect(source).toContain('data-observation-yesterday="data_unavailable"');
    expect(source).toContain("已运行，但信号数据不可用");
    expect(source).toContain('calendarQuery.data?.yesterday.status === "data_unavailable"');
  });

  it("puts the duty tape between the hero and the blotter heading", () => {
    const hero = source.indexOf("dp-hero");
    const tape = source.indexOf("<DutyMarketTape");
    const sechead = source.indexOf("dp-sechead");
    expect(source).toContain('import { DutyMarketTape } from "./DutyMarketTape"');
    expect(hero).toBeGreaterThan(-1);
    expect(tape).toBeGreaterThan(hero);
    expect(sechead).toBeGreaterThan(tape);
    expect(source).toContain('ledger === "duty"');
    expect(source).not.toContain("@/app/desk-preview");
  });

  it("labels book-only requests as locally recorded and not queued", () => {
    expect(source).toContain("只入本地账、未入队");
    expect(source).not.toContain("派研究 · 不挂");
  });

  it("keeps the only hang action on the candidate library", () => {
    expect(source).toContain('localizePath("/library", locale)');
    expect(source).not.toContain("/api/assistant/remote/hang");
    expect(source).not.toContain("hangMutation");
    expect(source).not.toContain("确认挂上");
  });

  it("uses simulation language instead of internal hang terminology", () => {
    expect(source).toContain("已验证候选可查看准入结果");
    expect(source).toContain("模拟运行中");
    expect(source).toContain("尚未启用");
    expect(source).toContain("Simulated strategy performance");
    expect(source).not.toContain("挂不挂");
    expect(source).not.toContain("已挂上");
    expect(source).not.toContain("未挂上");
    expect(source).not.toContain('"Hung"');
    expect(source).not.toContain('"Not hung"');
    expect(source).not.toContain("Hung performance");
  });

  it("shows readable candidate copy while keeping exact identities in technical details", () => {
    expect(source).toContain("candidatePresentation(item, locale)");
    expect(source).toContain("presentation.name");
    expect(source).toContain("presentation.summary");
    expect(source).toContain("标的范围");
    expect(source).toContain("技术信息");
    expect(source).toContain("<details");
    expect(source).not.toContain("宇宙 / digest");
    expect(source).not.toContain("digestShort");
    expect(source).not.toContain("live_trading=false");
  });

  it("keeps historical research objectives in technical details on the Chinese desk", () => {
    expect(source).toContain("researchRequestSummary(item, isZh)");
    expect(source).toContain("researchRequestStatusLabel(item, isZh)");
    expect(source).toContain("研究请求已入队，完成后会回到本对话");
    expect(source).toContain("研究请求已记录，尚未入队");
  });

  it("does not describe outcome_unknown research as still queued", () => {
    expect(source).toContain("研究结果未能确认，不是仍在执行");
    expect(source).toContain("待确认");
    expect(source).toContain('item.status === "outcome_unknown"');
    const queuedBranch = source.slice(
      source.indexOf('? isZh'),
    );
    expect(queuedBranch).not.toMatch(
      /outcome_unknown[\s\S]{0,80}已入队研究/,
    );
  });

  it("keeps the blotter action column readable on a tablet width", () => {
    expect(blotterCss).toMatch(/\.dp-blotter\s*\{[\s\S]*?overflow-x:\s*auto/);
    expect(blotterCss).toMatch(
      /\.dp-blotter (?:thead th|td):last-child[\s\S]{0,180}sticky/,
    );
    expect(blotterCss).toMatch(
      /\.dp-blotter (?:thead th|td):last-child[\s\S]{0,120}min-width:\s*[5-9]/,
    );
    expect(blotterCss).toContain(".dp-row:not(:last-child) td");
  });
});
