import Link from "next/link";

import type {
  BriefRollupListItem,
  BriefRollupPayload,
  BriefRollupView,
} from "@/lib/briefRollup";
import { localizePath } from "@/lib/locale";

type RollupLocale = "en" | "zh";

const copy = {
  en: {
    aiSynthesis: "AI SYNTHESIS",
    readOnlyNote:
      "This page only reads the stored rollup snapshot; current data never replaces history.",
    basedOn: (dailyCount: number, model: string) =>
      `Based on ${dailyCount} daily snapshots · model ${model} · paper only · not investment advice`,
    storyline: "THE MAIN STORYLINE",
    statsDaily: "Daily issues",
    statsEvents: "Distinct events",
    statsEquity: "Paper equity change",
    topics: "HIGHLIGHTS",
    noTopics: "No topics in this snapshot.",
    previous: "← Previous",
    next: "Next →",
    provenance: "PROVENANCE",
    model: "Model",
    criticModel: "Critic model",
    generatedAt: "Generated at",
    factsDigest: "Facts digest",
    sourceIssues: "Source daily issues",
    archiveError: "Rollup Error",
    invalidTitle: "Rollup snapshot cannot be displayed",
    invalidBody:
      "This record did not store a valid rollup payload. Live data is not substituted.",
    warnings: "Snapshot Warnings",
    footer: "READ-ONLY HISTORICAL SNAPSHOT · PAPER ONLY · NOT INVESTMENT ADVICE",
  },
  zh: {
    aiSynthesis: "AI 综合",
    readOnlyNote: "本页只读取数据库中的已保存快照，不使用当前行情覆盖历史。",
    basedOn: (dailyCount: number, model: string) =>
      `基于 ${dailyCount} 期日报快照 · 模型 ${model} · 模拟盘 · 非投资建议`,
    storyline: "本期主线",
    statsDaily: "日报期数",
    statsEvents: "独立事件数",
    statsEquity: "账户期间权益变化",
    topics: "本期看点",
    noTopics: "快照中没有看点。",
    previous: "← 上一期",
    next: "下一期 →",
    provenance: "生成来源",
    model: "模型",
    criticModel: "校订模型",
    generatedAt: "生成时间",
    factsDigest: "事实摘要指纹",
    sourceIssues: "来源日报",
    archiveError: "周报/月报读取失败",
    invalidTitle: "快照不可展示",
    invalidBody: "该记录没有保存有效的周报/月报事实内容；为避免伪装成完整刊物，本页不会现场补数据。",
    warnings: "快照警告",
    footer: "只读历史快照 · 模拟盘 · 非投资建议",
  },
} as const;

export type BriefRollupDocumentProps = {
  locale: RollupLocale;
  next: BriefRollupListItem | null;
  previous: BriefRollupListItem | null;
  rollup: BriefRollupView;
};

/** Pure presentational rollup document: fully determined by props, SSR-renderable. */
export function BriefRollupDocument({
  locale,
  next,
  previous,
  rollup,
}: BriefRollupDocumentProps) {
  const isZh = locale === "zh";
  const text = copy[locale];
  const payload = rollup.payload;
  const stats = payload?.stats;
  const provenance = payload?.provenance;
  const periodKey = payload?.period_key || rollup.periodKey || "--";
  const periodStart = payload?.date_range.start || rollup.periodStart || "--";
  const periodEnd = payload?.date_range.end || rollup.periodEnd || "--";
  const baseCurrency = rollupBaseCurrency(payload);

  return (
    <article className="mx-auto flex min-h-full max-w-editorial-column flex-col gap-8 px-5 py-8 md:px-10 lg:px-14">
      <header className="border-b-[3px] border-double border-ink pb-6 text-center">
        <p className="font-editorial-caps text-ink-secondary">
          {`VOL.${periodKey} · ${periodStart} ~ ${periodEnd} · ${text.aiSynthesis}`}
        </p>
        <h1 className="mt-3 font-editorial-display text-ink">{rollup.title}</h1>
        <p className="mt-3 font-data-mono text-xs text-ink-secondary">
          {payload && stats && provenance
            ? text.basedOn(stats.daily_count, provenance.model)
            : text.readOnlyNote}
        </p>
      </header>

      {rollup.apiError ? (
        <Alert messages={[rollup.apiError]} title={text.archiveError} />
      ) : null}

      {payload ? (
        <>
          <section className="border-b border-editorial-rule pb-7 text-center">
            <h2 className="font-editorial-caps text-sm text-ink-secondary">{text.storyline}</h2>
            <p className="mt-3 font-editorial-body text-xl leading-9 text-ink">
              {payload.main_storyline}
            </p>
          </section>

          <section className="border-b border-editorial-rule pb-7">
            <div className="grid gap-4 sm:grid-cols-3">
              <Metric label={text.statsDaily} value={String(stats?.daily_count ?? "--")} />
              <Metric label={text.statsEvents} value={String(stats?.event_count ?? "--")} />
              <Metric
                label={text.statsEquity}
                tone={periodChangeTone(stats?.period_change_pct)}
                value={formatPeriodChange(stats?.period_change_pct)}
                valueDetail={equityRange(stats, baseCurrency)}
              />
            </div>
          </section>

          <section className="border-b border-editorial-rule pb-7">
            <SectionTitle>{text.topics}</SectionTitle>
            {payload.topics.length ? (
              <ol className="space-y-6">
                {payload.topics.map((topic, position) => (
                  <li key={`${topic.index}-${topic.title}`}>
                    <div className="flex items-baseline gap-3">
                      <span className="font-data-mono text-sm text-editorial-accent">
                        {String(Number.isFinite(topic.index) ? topic.index : position + 1).padStart(2, "0")}
                      </span>
                      <h3 className="font-editorial-body text-lg font-bold text-ink">{topic.title}</h3>
                    </div>
                    <p className="mt-2 font-body-sm leading-6 text-ink-secondary">{topic.synthesis}</p>
                    {topic.source_items.length ? (
                      <ul className="mt-3 space-y-1.5 border-l border-editorial-rule pl-4">
                        {topic.source_items.map((item) => {
                          const href = safeExternalUrl(item.url);
                          return (
                            <li className="font-editorial-body text-sm leading-6 text-ink" key={item.id || item.url || item.title}>
                              {href ? (
                                <a
                                  className="transition-colors hover:text-editorial-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-editorial-accent"
                                  href={href}
                                  rel="noreferrer noopener"
                                  target="_blank"
                                >
                                  {item.title}
                                </a>
                              ) : (
                                item.title
                              )}
                              <span className="ml-2 font-data-mono text-[11px] text-ink-secondary">
                                {item.source} · {item.published_at ?? "--"} · {item.issue_date ?? "--"}
                              </span>
                            </li>
                          );
                        })}
                      </ul>
                    ) : null}
                  </li>
                ))}
              </ol>
            ) : (
              <p className="font-data-mono text-sm text-ink-secondary">{text.noTopics}</p>
            )}
          </section>
        </>
      ) : rollup.apiError ? null : (
        <Alert messages={[text.invalidBody]} title={text.invalidTitle} />
      )}

      {rollup.warnings.length ? (
        <Alert messages={rollup.warnings} title={text.warnings} />
      ) : null}

      <nav className="flex items-center justify-between gap-4 border-t border-editorial-rule pt-5 font-data-mono text-sm">
        <span className="min-w-0">
          {previous ? (
            <Link
              className="text-ink-secondary transition-colors hover:text-editorial-accent"
              href={localizePath(`/brief/rollup/${previous.public_id}`, locale)}
            >
              {text.previous} · {previous.period_key}
            </Link>
          ) : null}
        </span>
        <span className="min-w-0 text-right">
          {next ? (
            <Link
              className="text-ink-secondary transition-colors hover:text-editorial-accent"
              href={localizePath(`/brief/rollup/${next.public_id}`, locale)}
            >
              {text.next} · {next.period_key}
            </Link>
          ) : null}
        </span>
      </nav>

      {provenance ? (
        <section className="border-t border-editorial-rule pt-5">
          <SectionTitle>{text.provenance}</SectionTitle>
          <div className="grid gap-3 sm:grid-cols-2">
            <MetaItem label={text.model} value={provenance.model || "--"} />
            <MetaItem label={text.criticModel} value={provenance.critic_model ?? "--"} />
            <MetaItem label={text.generatedAt} value={provenance.generated_at || "--"} />
            <MetaItem label={text.factsDigest} value={provenance.facts_digest ?? "--"} />
          </div>
          <h3 className="mt-4 font-label-caps uppercase text-ink-secondary">{text.sourceIssues}</h3>
          {provenance.source_issue_public_ids.length ? (
            <ul className="mt-2 space-y-1 font-data-mono text-xs">
              {provenance.source_issue_public_ids.map((id) => (
                <li key={id}>
                  <Link
                    className="text-ink-secondary transition-colors hover:text-editorial-accent"
                    href={localizePath(`/brief/${id}`, locale)}
                  >
                    {id}
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 font-data-mono text-xs text-ink-secondary">--</p>
          )}
        </section>
      ) : null}

      <footer className="border-t border-editorial-rule py-6 text-center font-data-mono text-[11px] uppercase tracking-[0.14em] text-ink-secondary">
        HERMES MORNING BRIEF · {text.footer}
      </footer>
    </article>
  );
}

function rollupBaseCurrency(payload: BriefRollupPayload | null) {
  const currency = payload?.account_summary?.base_currency;
  return typeof currency === "string" && currency.trim().length > 0 ? currency : "USD";
}

function periodChangeTone(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "neutral" as const;
  }
  return value >= 0 ? ("up" as const) : ("down" as const);
}

function formatPeriodChange(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "--";
  }
  // period_change_pct is already percentage points (like asia-radar *_pct
  // fields), so it is never re-scaled by formatPercent.
  return `${value >= 0 ? "▲ +" : "▼ -"}${Math.abs(value).toFixed(2)}%`;
}

function equityRange(
  stats: BriefRollupPayload["stats"] | undefined,
  baseCurrency: string,
) {
  if (!stats) {
    return undefined;
  }
  const start = stats.equity_start;
  const end = stats.equity_end;
  if (start === null || start === undefined || end === null || end === undefined) {
    return undefined;
  }
  return `${money(start, baseCurrency)} → ${money(end, baseCurrency)}`;
}

function money(value: number, currency: string) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(value);
}

function safeExternalUrl(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : "";
  } catch {
    return "";
  }
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="mb-4 font-editorial-display text-2xl text-ink">{children}</h2>;
}

function Metric({
  label,
  tone = "neutral",
  value,
  valueDetail,
}: {
  label: string;
  tone?: "down" | "neutral" | "up";
  value: string;
  valueDetail?: string;
}) {
  const toneClass =
    tone === "up" ? "text-editorial-up" : tone === "down" ? "text-editorial-down" : "text-ink";
  return (
    <div className="border-t-2 border-ink pt-2">
      <p className="font-data-mono text-xs text-ink-secondary">{label}</p>
      <p className={`mt-1 font-editorial-body text-xl font-bold ${toneClass}`}>{value}</p>
      {valueDetail ? (
        <p className="mt-1 font-data-mono text-[11px] text-ink-secondary">{valueDetail}</p>
      ) : null}
    </div>
  );
}

function Alert({ messages, title }: { messages: string[]; title: string }) {
  return (
    <section className="border border-warning/50 bg-warning/10 p-4">
      <h2 className="font-label-caps uppercase text-warning">{title}</h2>
      <ul className="mt-2 space-y-1 font-body-sm text-ink">
        {messages.map((message) => (
          <li key={message}>{message}</li>
        ))}
      </ul>
    </section>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 border border-editorial-rule bg-paper-surface-muted p-3">
      <p className="font-label-caps uppercase text-ink-secondary">{label}</p>
      <p className="mt-1 break-words font-data-mono text-ink">{value}</p>
    </div>
  );
}
