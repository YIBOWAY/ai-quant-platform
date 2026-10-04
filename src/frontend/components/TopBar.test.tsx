import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ pathname: "/zh/watch", locale: "zh", search: "pane=cross&symbol=SPY" }));
vi.mock("next/navigation", () => ({
  usePathname: () => state.pathname,
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(state.search),
}));
vi.mock("@/components/LocaleProvider", () => ({ useLocale: () => state.locale }));

import { TopBar } from "./TopBar";

describe("TopBar", () => {
  beforeEach(() => { state.pathname = "/zh/watch"; state.locale = "zh"; });

  it("shows the current page with Hermes, search, mobile navigation, language and safety still available", () => {
    const html = renderToStaticMarkup(<TopBar shellEnabled safetySlot={<span data-global-safety-strip>仅模拟</span>} />);
    expect(html).toMatch(/data-topbar-page-title="true">市场研判<\/span>/);
    expect(html).toContain('aria-label="搜索标的代码"');
    expect(html).toContain('aria-label="打开导航"');
    expect(html).toContain('href="/zh/hermes"');
    expect(html).toContain('href="/zh/settings"');
    expect(html).toContain('data-global-safety-strip="true"');
    expect(html).toContain('href="/en/watch?pane=cross&amp;symbol=SPY"');
  });

  it("uses the new daily brief title and identifies nested pages from the existing navigation catalog", () => {
    state.locale = "en";
    state.pathname = "/en/brief/archive-id";
    let html = renderToStaticMarkup(<TopBar shellEnabled />);
    expect(html).toMatch(/data-topbar-page-title="true">Daily Brief<\/span>/);
    state.pathname = "/en/watch";
    html = renderToStaticMarkup(<TopBar shellEnabled />);
    expect(html).toMatch(/data-topbar-page-title="true">Market Outlook<\/span>/);
    state.pathname = "/en/backtest";
    html = renderToStaticMarkup(<TopBar shellEnabled />);
    expect(html).toMatch(/data-topbar-page-title="true">Backtester<\/span>/);
  });

  it("labels the company research page in both languages", () => {
    state.pathname = "/zh/company-research";
    expect(renderToStaticMarkup(<TopBar shellEnabled />)).toContain('data-topbar-page-title="true">公司研究</span>');
    state.locale = "en";
    state.pathname = "/en/company-research";
    expect(renderToStaticMarkup(<TopBar shellEnabled />)).toContain('data-topbar-page-title="true">Company Research</span>');
  });
});
