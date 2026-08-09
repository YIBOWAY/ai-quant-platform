import Link from "next/link";
import { BriefDailyChange } from "@/components/brief/BriefDailyChange";
import { BriefPerformanceChart } from "@/components/brief/BriefPerformanceChart";
import { getBriefIssue } from "@/lib/api";
import {
  normalizeBriefIssueEnvelope,
  type BriefArchivePayload,
} from "@/lib/briefArchive";
import { selectBriefPerformanceSeries } from "@/lib/briefPerformance";

type Props = { params: Promise<{ publicId: string }> };

export default async function BriefIssueArchivePage({ params }: Props) {
  const { publicId } = await params;
  const envelope = await getBriefIssue(publicId);
  const { issue, snapshot } = envelope;
  const archive = normalizeBriefIssueEnvelope(envelope);
  const title =
    typeof snapshot.payload.title === "string" && snapshot.payload.title.trim().length > 0
      ? snapshot.payload.title
      : archive.title;
  const isZh = archive.locale === "zh";

  return (
    <main className="h-full overflow-y-auto bg-paper-ink text-ink">
      <article className="mx-auto flex min-h-full max-w-editorial-column flex-col gap-8 px-5 py-8 md:px-10 lg:px-14">
        <header className="border-b-[3px] border-double border-ink pb-6 text-center">
          <p className="font-editorial-caps text-ink-secondary">
            {isZh ? "每日晨报 · 历史快照" : "Daily Brief · Archived Snapshot"}
          </p>
          <h1 className="mt-3 font-editorial-display text-ink">{title}</h1>
          <p className="mt-3 font-data-mono text-xs text-ink-secondary">
            {isZh
              ? "本页只读取数据库中的已保存快照，不使用当前行情覆盖历史。"
              : "This page only reads the stored database snapshot; current data never replaces history."}
          </p>
          <div className="mt-6 grid gap-3 text-left sm:grid-cols-2 lg:grid-cols-4">
            <MetaItem label={isZh ? "日期" : "Issue Date"} value={issue.issue_date || "--"} />
            <MetaItem label={isZh ? "版本" : "Version"} value={`v${archive.version}`} />
            <MetaItem label={isZh ? "状态" : "Status"} value={archive.status || "--"} />
            <MetaItem label="Public ID" value={archive.publicId || publicId} />
          </div>
        </header>

        {archive.apiError ? (
          <Alert title={isZh ? "归档读取失败" : "Archive Error"} messages={[archive.apiError]} />
        ) : null}

        {archive.payload ? (
          <ArchiveDocument
            account={archive.payload.account}
            aiNews={archive.payload.ai_news}
            generatedAt={archive.payload.generated_at}
            hermesLog={archive.payload.hermes_log}
            isZh={isZh}
            lede={archive.payload.lede}
            marketNote={archive.payload.market_note}
            markets={archive.payload.markets}
            paperEquity={archive.payload.paper_equity}
            performance={archive.payload.performance}
          />
        ) : archive.apiError ? null : (
          <Alert
            title={isZh ? "旧版空归档不可展示" : "Legacy empty archive cannot be displayed"}
            messages={[
              isZh
                ? "该记录没有保存账户、行情、AI 新闻和 Hermes 运行事实；为避免伪装成完整日报，本页不会现场补数据。"
                : "This record did not store account, market, AI-news, and Hermes facts. Live data is not substituted.",
            ]}
          />
        )}

        {archive.warnings.length ? (
          <Alert title={isZh ? "快照警告" : "Snapshot Warnings"} messages={archive.warnings} />
        ) : null}

        <section className="border-t border-editorial-rule pt-5">
          <h2 className="font-label-caps uppercase text-ink-secondary">
            {isZh ? "来源水位" : "Source Watermark"}
          </h2>
          {archive.sourceWatermark ? (
            <div className="mt-4 space-y-3">
              <p className="font-data-mono text-xs text-ink-secondary">
                {isZh ? "快照时间" : "Captured at"}: {archive.sourceWatermark.captured_at}
              </p>
              <div className="grid gap-3 md:grid-cols-2">
                {archive.sourceWatermark.sources.map((source) => (
                  <div className="border border-editorial-rule bg-paper-surface p-3" key={source.name}>
                    <div className="flex items-center justify-between gap-3">
                      <strong className="font-data-mono text-sm text-ink">{source.name}</strong>
                      <span className={sourceStatusClass(source.status)}>{source.status}</span>
                    </div>
                    <p className="mt-2 font-data-mono text-xs text-ink-secondary">
                      {source.as_of ?? "--"} · {source.detail ?? "--"}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          ) : archive.sourceWatermarkEntries.length ? (
            <dl className="mt-4 grid gap-3 md:grid-cols-2">
              {archive.sourceWatermarkEntries.map(([key, value]) => (
                <MetaItem key={key} label={key} value={value} />
              ))}
            </dl>
          ) : (
            <p className="mt-4 font-body-sm text-ink-secondary">{isZh ? "没有来源记录" : "No source record"}</p>
          )}
        </section>

        <footer className="border-t border-editorial-rule py-6 text-center font-data-mono text-[11px] uppercase tracking-[0.14em] text-ink-secondary">
          HERMES MORNING BRIEF · {isZh ? "只读历史快照" : "READ-ONLY HISTORICAL SNAPSHOT"}
        </footer>
      </article>
    </main>
  );
}

function ArchiveDocument({
  account,
  aiNews,
  generatedAt,
  hermesLog,
  isZh,
  lede,
  marketNote,
  markets,
  paperEquity,
  performance,
}: {
  account: BriefArchivePayload["account"];
  aiNews: BriefArchivePayload["ai_news"];
  generatedAt: string;
  hermesLog: BriefArchivePayload["hermes_log"];
  isZh: boolean;
  lede: string;
  marketNote: string;
  markets: BriefArchivePayload["markets"];
  paperEquity: BriefArchivePayload["paper_equity"];
  performance: BriefArchivePayload["performance"];
}) {
  const selectedPerformanceSeries = performance
    ? selectBriefPerformanceSeries(performance)
    : [];
  return (
    <>
      <section className="border-b border-editorial-rule pb-7 text-center">
        <p className="font-editorial-body text-xl leading-9 text-ink">{lede}</p>
        <p className="mt-3 font-data-mono text-xs text-ink-secondary">
          {isZh ? "生成于" : "Generated at"} {generatedAt}
        </p>
      </section>

      <section className="border-b border-editorial-rule pb-7">
        <SectionTitle zh="模拟账户" en="PAPER ACCOUNT" isZh={isZh} />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Metric label={isZh ? "权益" : "Equity"} value={money(account.equity, account.base_currency)} />
          <Metric label={isZh ? "现金" : "Cash"} value={money(account.cash, account.base_currency)} />
          <Metric label={isZh ? "盈亏" : "P&L"} value={money(account.pnl_abs, account.base_currency)} />
          <Metric label={isZh ? "投入比例" : "Invested"} value={percent(account.invested_pct)} />
        </div>
        <div className="mt-5 overflow-x-auto border border-editorial-rule">
          <table className="w-full min-w-[720px] border-collapse font-data-mono text-xs">
            <thead className="bg-paper-surface-muted text-left text-ink-secondary">
              <tr>
                <Th>{isZh ? "标的" : "Symbol"}</Th>
                <Th>{isZh ? "数量" : "Quantity"}</Th>
                <Th>{isZh ? "成本" : "Average"}</Th>
                <Th>{isZh ? "现价" : "Last"}</Th>
                <Th>{isZh ? "市值" : "Market value"}</Th>
                <Th>{isZh ? "日涨跌" : "Daily"}</Th>
                <Th>{isZh ? "未实现盈亏" : "Unrealized P&L"}</Th>
              </tr>
            </thead>
            <tbody>
              {account.positions.length ? (
                account.positions.map((position) => (
                  <tr className="border-t border-editorial-rule" key={position.symbol}>
                    <Td>{position.symbol}</Td>
                    <Td>{number(position.quantity)}</Td>
                    <Td>{money(position.avg_cost, account.base_currency)}</Td>
                    <Td>{money(position.last_price, account.base_currency)}</Td>
                    <Td>{money(position.market_value, account.base_currency)}</Td>
                    <Td>
                      <BriefDailyChange value={position.day_change_ratio} />
                    </Td>
                    <Td>{money(position.unrealized_pnl, account.base_currency)}</Td>
                  </tr>
                ))
              ) : (
                <tr><Td colSpan={7}>{isZh ? "快照时为空仓" : "No positions in this snapshot"}</Td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="border-b border-editorial-rule pb-7">
        {performance ? (
          <>
            <SectionTitle
              zh="模拟盘与基准收益"
              en="PAPER VS SPY · QQQ"
              isZh={isZh}
            />
            <p className="mb-3 font-data-mono text-xs text-ink-secondary">
              {isZh ? "归档主范围" : "Archived master range"}: {performance.master_range} ·{" "}
              {isZh ? "保存时选择" : "Selected when saved"}: {performance.selected_range} ·{" "}
              {performance.actual_start ?? "--"} → {performance.actual_end ?? "--"}
            </p>
            <BriefPerformanceChart
              ariaLabel={
                isZh
                  ? "归档模拟盘、SPY 与 QQQ 收益曲线"
                  : "Archived paper, SPY, and QQQ performance"
              }
              emptyLabel={
                isZh
                  ? "归档中没有可对齐的收益数据"
                  : "No aligned performance data in this archive"
              }
              series={selectedPerformanceSeries}
            />
          </>
        ) : (
          <>
            <SectionTitle
              zh="模拟盘权益记录（旧版）"
              en="LEGACY PAPER EQUITY"
              isZh={isZh}
            />
            {paperEquity.length ? (
              <div className="grid gap-3 md:grid-cols-3">
                {paperEquity.map((point) => (
                  <Metric
                    key={`${point.timestamp}-${point.source}`}
                    label={`${point.timestamp} · ${point.source}`}
                    value={money(point.equity, account.base_currency)}
                  />
                ))}
              </div>
            ) : (
              <Empty>
                {isZh
                  ? "快照中没有权益曲线点"
                  : "No equity points in this snapshot"}
              </Empty>
            )}
          </>
        )}
      </section>

      <section className="border-b border-editorial-rule pb-7">
        <SectionTitle zh="市场" en="MARKET" isZh={isZh} />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {markets.map((market) => (
            <Metric
              key={market.symbol}
              label={`${market.symbol} · ${market.source ?? "--"} · ${market.as_of ?? "--"}`}
              value={`${market.last === null ? "--" : number(market.last)} · ${market.change_pct === null ? "--" : signedPercent(market.change_pct)}`}
            />
          ))}
        </div>
        <blockquote className="mt-5 border-l-4 border-editorial-accent bg-paper-surface px-5 py-4 font-editorial-body italic text-ink">
          “{marketNote}”
        </blockquote>
      </section>

      <section className="border-b border-editorial-rule pb-7">
        <SectionTitle zh="AI 情报摘要" en="AI INTELLIGENCE" isZh={isZh} />
        {aiNews.length ? (
          <div className="grid gap-5 md:grid-cols-2">
            {aiNews.map((item) => {
              const href = safeExternalUrl(item.url);
              return (
                <article className="border-t-2 border-ink pt-3" key={item.id}>
                  <p className="font-data-mono text-[10px] uppercase tracking-[0.12em] text-editorial-down">
                    {item.source} · {item.category ?? "feed"} · {item.published_at ?? "--"}
                  </p>
                  <h3 className="mt-2 font-editorial-body text-lg font-bold text-ink">
                    {href ? <a href={href} rel="noreferrer noopener" target="_blank">{item.title}</a> : item.title}
                  </h3>
                  <p className="mt-2 font-body-sm leading-6 text-ink-secondary">{item.summary ?? item.url}</p>
                </article>
              );
            })}
          </div>
        ) : (
          <Empty>{isZh ? "快照中没有 AI 新闻" : "No AI news in this snapshot"}</Empty>
        )}
      </section>

      <section className="border-b border-editorial-rule pb-7">
        <SectionTitle zh="研究活动记录" en="RESEARCH ACTIVITY LOG" isZh={isZh} />
        {hermesLog.length ? (
          <div className="space-y-2 font-data-mono text-xs">
            {hermesLog.map((entry, index) => (
              <div className="grid gap-2 border-b border-dotted border-editorial-rule py-2 md:grid-cols-[180px_24px_1fr]" key={`${entry.text}-${index}`}>
                <span className="text-ink-secondary">{entry.timestamp ?? "--"}</span>
                <span className={entry.status === "ok" ? "text-editorial-up" : "text-warning"}>{entry.status === "ok" ? "✓" : "△"}</span>
                <span className="text-ink">
                  {entry.href?.startsWith("/") ? <Link href={entry.href}>{entry.text}</Link> : entry.text}
                  {entry.summary ? <span className="ml-2 text-ink-secondary">· {entry.summary}</span> : null}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <Empty>{isZh ? "快照中没有研究活动记录" : "No research activity log in this snapshot"}</Empty>
        )}
      </section>
    </>
  );
}

function SectionTitle({ zh, en, isZh }: { zh: string; en: string; isZh: boolean }) {
  return <h2 className="mb-4 font-editorial-display text-2xl text-ink">{isZh ? zh : en}</h2>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="border-t-2 border-ink pt-2"><p className="font-data-mono text-xs text-ink-secondary">{label}</p><p className="mt-1 font-editorial-body text-xl font-bold text-ink">{value}</p></div>;
}

function Alert({ title, messages }: { title: string; messages: string[] }) {
  return <section className="border border-warning/50 bg-warning/10 p-4"><h2 className="font-label-caps uppercase text-warning">{title}</h2><ul className="mt-2 space-y-1 font-body-sm text-ink">{messages.map((message) => <li key={message}>{message}</li>)}</ul></section>;
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0 border border-editorial-rule bg-paper-surface-muted p-3"><p className="font-label-caps uppercase text-ink-secondary">{label}</p><p className="mt-1 break-words font-data-mono text-ink">{value}</p></div>;
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="font-data-mono text-sm text-ink-secondary">{children}</p>;
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-3 py-2 font-medium">{children}</th>;
}

function Td({ children, colSpan }: { children: React.ReactNode; colSpan?: number }) {
  return <td className="px-3 py-2 text-ink" colSpan={colSpan}>{children}</td>;
}

function money(value: number, currency: string) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 2 }).format(value);
}

function number(value: number) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(value);
}

function percent(value: number) {
  return new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 2 }).format(value);
}

function signedPercent(value: number) {
  return `${value >= 0 ? "+" : ""}${percent(value)}`;
}

function safeExternalUrl(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : "";
  } catch {
    return "";
  }
}

function sourceStatusClass(status: "available" | "stale" | "unavailable") {
  if (status === "available") return "font-data-mono text-xs text-editorial-up";
  if (status === "stale") return "font-data-mono text-xs text-warning";
  return "font-data-mono text-xs text-danger";
}
