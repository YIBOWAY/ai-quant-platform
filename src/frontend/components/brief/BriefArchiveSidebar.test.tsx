import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { BriefArchiveSidebarView } from "./BriefArchiveSidebar";
import type { BriefArchiveGroup } from "@/lib/briefArchive";

const dailyGroups: BriefArchiveGroup[] = [
  {
    key: "2026-08",
    entries: [
      {
        public_id: "brf_20260811_alpha",
        issue_date: "2026-08-11",
        title: "每日晨报",
        snippet: "今晨，模拟盘权益报 $101,234.50",
        kind: "daily",
        iso_week: null,
        month: null,
      },
      {
        public_id: "brf_20260804_beta",
        issue_date: "2026-08-04",
        title: "每日晨报",
        snippet: "8 月 4 日导语。",
        kind: "daily",
        iso_week: null,
        month: null,
      },
    ],
  },
  {
    key: "2026-07",
    entries: [
      {
        public_id: "brf_20260730_gamma",
        issue_date: "2026-07-30",
        title: "七月收官晨报",
        snippet: "7 月 30 日导语。",
        kind: "daily",
        iso_week: null,
        month: null,
      },
    ],
  },
];

const weeklyGroups: BriefArchiveGroup[] = [
  {
    key: "2026-08",
    entries: [
      {
        public_id: "brf_20260811_alpha",
        issue_date: "2026-08-11",
        title: "每日晨报",
        snippet: "今晨导语。",
        kind: "weekly",
        iso_week: "2026-W33",
        month: null,
      },
      {
        public_id: "brf_20260808_delta",
        issue_date: "2026-08-08",
        title: "每日晨报",
        snippet: "周六导语。",
        kind: "weekly",
        iso_week: "2026-W32",
        month: null,
      },
    ],
  },
];

const monthlyGroups: BriefArchiveGroup[] = [
  {
    key: "2026",
    entries: [
      {
        public_id: "brf_20260811_alpha",
        issue_date: "2026-08-11",
        title: "每日晨报",
        snippet: "八月末刊。",
        kind: "monthly",
        iso_week: null,
        month: "2026-08",
      },
      {
        public_id: "brf_20260730_gamma",
        issue_date: "2026-07-30",
        title: "七月收官晨报",
        snippet: "七月末刊。",
        kind: "monthly",
        iso_week: null,
        month: "2026-07",
      },
    ],
  },
];

function render(props: Partial<Parameters<typeof BriefArchiveSidebarView>[0]>) {
  return renderToStaticMarkup(
    <BriefArchiveSidebarView
      activeKind="daily"
      groups={dailyGroups}
      locale="zh"
      status="ready"
      {...props}
    />,
  );
}

describe("BriefArchiveSidebarView", () => {
  it("renders the three bilingual tabs", () => {
    const zh = render({});
    expect(zh).toContain("日报");
    expect(zh).toContain("周报");
    expect(zh).toContain("月报");
    expect(zh).toContain('role="tablist"');

    const en = render({ locale: "en" });
    expect(en).toContain("Daily");
    expect(en).toContain("Weekly");
    expect(en).toContain("Monthly");
  });

  it("groups daily entries by month with day markers and lede snippets", () => {
    const html = render({});
    expect(html).toContain("2026 年 8 月");
    expect(html).toContain("今晨，模拟盘权益报 $101,234.50");
    expect(html).toContain("/zh/brief/brf_20260811_alpha");
    // Latest month is expanded by default, older month stays collapsed.
    expect(html).toContain("2026 年 7 月");
    expect(html).not.toContain("七月收官晨报");
    expect(html).not.toContain("/zh/brief/brf_20260730_gamma");
    // aria-expanded reflects the default expand/collapse split.
    expect(html).toContain('aria-expanded="true"');
    expect(html).toContain('aria-expanded="false"');
  });

  it("localizes month group labels in English", () => {
    const html = render({ locale: "en" });
    expect(html).toContain("August 2026");
    expect(html).toContain("July 2026");
    expect(html).toContain("/en/brief/brf_20260811_alpha");
  });

  it("marks the active issue row", () => {
    const html = render({ activePublicId: "brf_20260811_alpha" });
    const activeLink = html
      .split("<a")
      .find((chunk) => chunk.includes("brf_20260811_alpha"));
    expect(activeLink).toBeDefined();
    expect(activeLink).toContain("bg-paper-surface-muted");
  });

  it("renders ISO week markers on the weekly tab", () => {
    const html = render({ activeKind: "weekly", groups: weeklyGroups });
    expect(html).toContain("W33");
    expect(html).toContain("W32");
    expect(html).toContain("/zh/brief/brf_20260808_delta");
  });

  it("groups monthly entries by year with month markers", () => {
    const zh = render({ activeKind: "monthly", groups: monthlyGroups });
    expect(zh).toContain("2026 年");
    expect(zh).toContain("8 月");
    expect(zh).toContain("7 月");

    const en = render({
      activeKind: "monthly",
      groups: monthlyGroups,
      locale: "en",
    });
    expect(en).toContain("Aug");
    expect(en).toContain("Jul");
  });

  it("shows an honest empty state when there are no archived issues", () => {
    const zh = render({ groups: [] });
    expect(zh).toContain("暂无归档期号");
    expect(zh).not.toContain("/brief/brf_");

    const en = render({ groups: [], locale: "en" });
    expect(en).toContain("No archived issues yet.");
  });

  it("shows an alert instead of fabricating rows on error", () => {
    const html = render({
      error: "归档暂不可用（数据库未连接），当前晨报不受影响。",
      groups: [],
      status: "error",
    });
    expect(html).toContain('role="alert"');
    expect(html).toContain("数据库未连接");
    expect(html).not.toContain("/brief/brf_");
  });

  it("shows a loading state before the archive responds", () => {
    const html = render({ groups: [], status: "loading" });
    expect(html).toContain("归档加载中");
    expect(html).not.toContain("/brief/brf_");
  });
});
