import { readFileSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BriefArchiveSidebarView } from "./BriefArchiveSidebar";
import type { BriefArchiveGroup } from "@/lib/briefArchive";
import {
  buildBriefRollupSidebarGroups,
  listBriefRollups,
  type BriefRollupListResponse,
} from "@/lib/briefRollup";

const sidebarPath = path.join(process.cwd(), "components/brief/BriefArchiveSidebar.tsx");

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
        public_id: "brw_20260810_x1y2z3",
        issue_date: "2026-08-10",
        title: "第 33 周 AI 周报",
        snippet: "本周主线：半导体走强。",
        kind: "weekly",
        iso_week: "2026-W33",
        month: null,
      },
      {
        public_id: "brw_20260803_a1b2c3",
        issue_date: "2026-08-03",
        title: "第 32 周 AI 周报",
        snippet: "本周主线：防御轮动。",
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
        public_id: "brm_202608_d4e5f6",
        issue_date: "2026-08-01",
        title: "2026 年 8 月 AI 月报",
        snippet: "八月主线：波动放大。",
        kind: "monthly",
        iso_week: null,
        month: "2026-08",
      },
      {
        public_id: "brm_202607_g7h8i9",
        issue_date: "2026-07-01",
        title: "2026 年 7 月 AI 月报",
        snippet: "七月主线：缓慢修复。",
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

  it("labels the heading as history instead of archive", () => {
    expect(render({})).toContain("历史");
    expect(render({ locale: "en" })).toContain("History");
    expect(render({})).not.toContain(">归档<");
    expect(render({ locale: "en" })).not.toContain(">Archive<");
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

  it("renders ISO week markers and rollup links on the weekly tab", () => {
    const html = render({ activeKind: "weekly", groups: weeklyGroups });
    expect(html).toContain("W33");
    expect(html).toContain("W32");
    expect(html).toContain("第 33 周 AI 周报");
    expect(html).toContain("本周主线：半导体走强。");
    expect(html).toContain("/zh/brief/rollup/brw_20260810_x1y2z3");
    expect(html).toContain("/zh/brief/rollup/brw_20260803_a1b2c3");
    expect(html).not.toContain("/zh/brief/brw_");
  });

  it("groups monthly rollups by year with month markers and rollup links", () => {
    const zh = render({ activeKind: "monthly", groups: monthlyGroups });
    expect(zh).toContain("2026 年");
    expect(zh).toContain("8 月");
    expect(zh).toContain("7 月");
    expect(zh).toContain("/zh/brief/rollup/brm_202608_d4e5f6");
    expect(zh).not.toContain("/zh/brief/brm_");

    const en = render({
      activeKind: "monthly",
      groups: monthlyGroups,
      locale: "en",
    });
    expect(en).toContain("Aug");
    expect(en).toContain("Jul");
    expect(en).toContain("/en/brief/rollup/brm_202608_d4e5f6");
  });

  it("shows an honest empty state when there are no archived issues", () => {
    const zh = render({ groups: [] });
    expect(zh).toContain("暂无归档期号");
    expect(zh).not.toContain("/brief/brf_");

    const en = render({ groups: [], locale: "en" });
    expect(en).toContain("No archived issues yet.");
  });

  it("shows rollup-specific empty states on the weekly and monthly tabs", () => {
    const weekly = render({ activeKind: "weekly", groups: [] });
    expect(weekly).toContain("暂无 AI 周报。");
    const monthly = render({ activeKind: "monthly", groups: [] });
    expect(monthly).toContain("暂无 AI 月报。");

    const weeklyEn = render({ activeKind: "weekly", groups: [], locale: "en" });
    expect(weeklyEn).toContain("No AI weekly briefs yet.");
    const monthlyEn = render({ activeKind: "monthly", groups: [], locale: "en" });
    expect(monthlyEn).toContain("No AI monthly briefs yet.");
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

describe("rollup tabs data path", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function stubRollupFetch(payload: BriefRollupListResponse) {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("feeds weekly rollups from /api/brief/rollups into the sidebar view", async () => {
    const fetchMock = stubRollupFetch({
      kind: "weekly",
      locale: "zh",
      total: 2,
      items: [
        {
          public_id: "brw_20260810_x1y2z3",
          kind: "weekly",
          period_key: "2026-W33",
          period_start: "2026-08-10",
          period_end: "2026-08-16",
          locale: "zh",
          status: "published",
          title: "第 33 周 AI 周报",
          snippet: "本周主线：半导体走强。",
        },
        {
          public_id: "brw_20260720_j4k5l6",
          kind: "weekly",
          period_key: "2026-W30",
          period_start: "2026-07-20",
          period_end: "2026-07-26",
          locale: "zh",
          status: "published",
          title: "第 30 周 AI 周报",
          snippet: "当周主线：缩量整理。",
        },
      ],
    });

    const response = await listBriefRollups("weekly", "zh", 30);
    expect(String(fetchMock.mock.calls[0][0])).toContain(
      "/api/brief/rollups?kind=weekly&locale=zh&limit=30",
    );

    const groups = buildBriefRollupSidebarGroups(response.items, "weekly");
    // Weekly groups are keyed by the month of period_start, newest first.
    expect(groups.map((group) => group.key)).toEqual(["2026-08", "2026-07"]);

    const html = render({ activeKind: "weekly", groups });
    expect(html).toContain("W33");
    expect(html).toContain("第 33 周 AI 周报");
    expect(html).toContain("本周主线：半导体走强。");
    expect(html).toContain("2026 年 8 月");
    expect(html).toContain("/zh/brief/rollup/brw_20260810_x1y2z3");
    expect(html).not.toContain("/zh/brief/brw_");
    // The older month group stays collapsed, so its entries are not rendered.
    expect(html).toContain("2026 年 7 月");
    expect(html).not.toContain("W30");
    expect(html).not.toContain("/zh/brief/rollup/brw_20260720_j4k5l6");
  });

  it("feeds monthly rollups from /api/brief/rollups into the sidebar view", async () => {
    stubRollupFetch({
      kind: "monthly",
      locale: "zh",
      total: 2,
      items: [
        {
          public_id: "brm_202607_g7h8i9",
          kind: "monthly",
          period_key: "2026-07",
          period_start: "2026-07-01",
          period_end: "2026-07-31",
          locale: "zh",
          status: "published",
          title: "2026 年 7 月 AI 月报",
          snippet: "七月主线：缓慢修复。",
        },
        {
          public_id: "brm_202608_d4e5f6",
          kind: "monthly",
          period_key: "2026-08",
          period_start: "2026-08-01",
          period_end: "2026-08-31",
          locale: "zh",
          status: "published",
          title: "2026 年 8 月 AI 月报",
          snippet: "八月主线：波动放大。",
        },
      ],
    });

    const response = await listBriefRollups("monthly", "zh", 30);
    const groups = buildBriefRollupSidebarGroups(response.items, "monthly");
    // Monthly groups are keyed by the year of period_start, newest entries first.
    expect(groups.map((group) => group.key)).toEqual(["2026"]);
    expect(groups[0]?.entries.map((entry) => entry.public_id)).toEqual([
      "brm_202608_d4e5f6",
      "brm_202607_g7h8i9",
    ]);

    const html = render({ activeKind: "monthly", groups });
    expect(html).toContain("2026 年");
    expect(html).toContain("8 月");
    expect(html).toContain("7 月");
    expect(html).toContain("2026 年 8 月 AI 月报");
    expect(html).toContain("/zh/brief/rollup/brm_202608_d4e5f6");
  });

  it("renders the rollup empty state when the endpoint returns no items", async () => {
    stubRollupFetch({ kind: "weekly", locale: "zh", total: 0, items: [] });

    const response = await listBriefRollups("weekly", "zh", 30);
    const groups = buildBriefRollupSidebarGroups(response.items, "weekly");
    const html = render({ activeKind: "weekly", groups });
    expect(html).toContain("暂无 AI 周报。");
    expect(html).not.toContain("/brief/rollup/");
  });
});

describe("BriefArchiveSidebar container contract", () => {
  it("keeps the daily tab on the archive endpoint and wires rollup tabs to /api/brief/rollups", () => {
    const source = readFileSync(sidebarPath, "utf8");

    // Daily tab still consumes the combined archive view.
    expect(source).toContain("buildBriefArchivePath(locale, ARCHIVE_MONTHS)");
    expect(source).toContain("view?.daily");
    // Weekly/monthly tabs consume the rollup endpoints instead.
    expect(source).toContain("buildBriefRollupListPath(kind, locale, ROLLUP_LIMIT)");
    expect(source).toContain("buildBriefRollupSidebarGroups");
    // Rollup entries deep-link to the rollup detail route.
    expect(source).toContain('"/brief/rollup"');
  });
});
