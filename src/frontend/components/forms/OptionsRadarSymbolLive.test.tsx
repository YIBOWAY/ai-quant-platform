import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { readFileSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LocaleProvider } from "@/components/LocaleProvider";
import { OptionsRadarSymbolLive, LiveSnapshotMetrics, futuIvPercent } from "./OptionsRadarSymbolLive";

function renderLive(locale: "en" | "zh", setup?: (client: QueryClient) => void) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  setup?.(client);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <LocaleProvider locale={locale}>
        <OptionsRadarSymbolLive symbol="AAPL" />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

function seedExpirationsError(client: QueryClient) {
  const query = client.getQueryCache().build(client, {
    queryKey: ["options-symbol-expirations", "AAPL"],
  });
  query.setState({
    status: "error",
    error: new Error("futu opend offline"),
    fetchStatus: "idle",
    errorUpdatedAt: Date.now(),
  });
}

describe("OptionsRadarSymbolLive locale", () => {
  it("renders Futu percent IV without multiplying it again, including low IV", () => {
    expect(futuIvPercent(214.227)).toBe("214.23%");
    expect(futuIvPercent(0.5)).toBe("0.50%");
  });

  it("never labels a different expiry snapshot as the selected chain IV", () => {
    const html = renderToStaticMarkup(<LiveSnapshotMetrics locale="zh" selectedExpiry="2026-09-18" snapshot={{
      success: true, ticker: "SPY", source: "futu", price: 500, nearest_expiry: "2026-09-14",
      iv_expiry: "2026-09-14", atm_iv: 0.25, iv_rank: 88, iv_rank_source: "local_hv_proxy", assumptions: [],
    }} />);
    expect(html).toContain("2026-09-18");
    expect(html).not.toContain("25.00%");
    expect(html).not.toContain(">88.0<");
    expect(html).toContain("缺少同口径期权 IV 历史");
  });
  it("renders the zh panel fully in Chinese before loading", () => {
    const html = renderLive("zh");

    expect(html).toContain("实时期权链");
    expect(html).toContain("只读 Futu 快照与期权链");
    expect(html).toContain("加载实时链");
    expect(html).toContain("左侧显示已保存的雷达行");
    expect(html).not.toContain("Live Option Chain");
    expect(html).not.toContain("Load Live Chain");
  });

  it("renders the en panel before loading", () => {
    const html = renderLive("en");

    expect(html).toContain("Live Option Chain");
    expect(html).toContain("Load Live Chain");
    expect(html).toContain("This area never places orders");
  });

  it("surfaces an expirations failure in the reader's locale", () => {
    const zh = renderLive("zh", seedExpirationsError);
    expect(zh).toContain("到期日列表不可用");

    const en = renderLive("en", seedExpirationsError);
    expect(en).toContain("Expiration list unavailable");
  });

  it("renders honest empty states instead of an endless loader", () => {
    const source = readFileSync(
      path.join(process.cwd(), "components/forms/OptionsRadarSymbolLive.tsx"),
      "utf8",
    );

    expect(source).toContain("expirationsQuery.error ? (");
    expect(source).toContain("text.noExpirations");
    expect(source).toContain("text.chainEmpty");
  });
});
