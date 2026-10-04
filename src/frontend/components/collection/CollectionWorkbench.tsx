"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  BookOpen,
  ChevronRight,
  Code2,
  FlaskConical,
  Layers3,
  Search,
  Sigma,
} from "lucide-react";
import type { components } from "@/lib/api.generated";
import { localizePath, type Locale } from "@/lib/locale";
import { TableScrollHint, tableScrollHintText } from "@/components/ui/primitives";
import { ItemEvaluationSummary } from "@/components/research/ResearchEvaluationView";

type Catalog = components["schemas"]["CollectionResponse"];
type RawItem = Catalog["items"][number];
function materialize(item: RawItem) {
  return {
    ...item,
    intro: {
      status: "missing" as const,
      summary: null,
      logic: [] as string[],
      usage: [] as string[],
      limitations: [] as string[],
      ...item.intro,
    },
    evidence: (item.evidence ?? []).map((row) => ({
      ...row,
      metrics: row.metrics ?? {},
    })),
    notes: item.notes ?? [],
    links: item.links ?? [],
    universe: item.universe ?? [],
    source_refs: item.source_refs ?? [],
  };
}
type Item = ReturnType<typeof materialize>;
type Evidence = Item["evidence"][number];
type Kind = Item["kind"];
const names = {
  zh: { research: "研究成果", strategy: "策略模板", factor: "因子组件" },
  en: {
    research: "Research",
    strategy: "Strategy templates",
    factor: "Factors",
  },
};
const numeric = (value: number | null | undefined, digits = 3) =>
  value == null || !Number.isFinite(value) ? "—" : value.toFixed(digits);
const percent = (value: number | null | undefined, absolute = false) =>
  value == null || !Number.isFinite(value)
    ? "—"
    : `${((absolute ? Math.abs(value) : value) * 100).toFixed(2)}%`;
const title = (item: Item, locale: Locale) =>
  locale === "zh" ? item.name : item.name_en || item.name;
const introReady = (item: Item) =>
  item.intro.status === "ready" &&
  Boolean(item.source_digest) &&
  item.intro.source_digest === item.source_digest;

function status(item: Item, zh: boolean) {
  if (item.implementation_status === "draft") return zh ? "研究草稿" : "Draft";
  if (item.implementation_status === "source_unavailable")
    return zh ? "实现待核对" : "Source unavailable";
  if (["hung", "running"].includes(item.simulation_status ?? ""))
    return zh ? "模拟运行中" : "Paper running";
  if (item.kind === "research") return zh ? "已完成研究" : "Research completed";
  if (
    item.evidence.some(
      (row) => row.kind === "factor_lab" && row.status === "historical",
    )
  )
    return zh ? "有历史探索" : "Historical study";
  return zh ? "已实现 · 待评估" : "Implemented · not evaluated";
}

function FactorStudy({ evidence, zh }: { evidence: Evidence; zh: boolean }) {
  const available =
    evidence.status !== "unavailable" &&
    (evidence.metrics.sample_count ?? 0) > 0;
  return (
    <div className="mt-4 rounded-lg border border-border-subtle p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-medium">
          {zh ? "历史因子探索" : "Historical factor study"}
        </h4>
        <span className="font-mono text-[11px] text-text-secondary">
          {evidence.start} → {evidence.end}
        </span>
      </div>
      {available ? (
        <dl className="mt-5 grid grid-cols-3 gap-4">
          {[
            ["Rank IC", numeric(evidence.metrics.ic_mean, 4)],
            [
              zh ? "有效样本" : "Samples",
              numeric(evidence.metrics.sample_count, 0),
            ],
            [zh ? "覆盖率" : "Coverage", percent(evidence.metrics.coverage)],
          ].map(([label, value]) => (
            <div key={label}>
              <dt className="text-xs text-text-secondary">{label}</dt>
              <dd className="mt-1 font-mono text-xl">{value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="mt-4 text-sm text-text-secondary">
          {zh
            ? "这次历史探索没有足够的有效样本，指标留空。"
            : "This historical study has no usable samples."}
        </p>
      )}
      <p className="mt-4 text-xs leading-6 text-text-secondary">
        {evidence.note}
      </p>
      {available ? (
        <p className="mt-2 text-xs leading-6 text-text-secondary">
          {zh
            ? "Rank IC 衡量因子排序与后续收益排序的关系，不等于策略收益或夏普率。"
            : "Rank IC compares factor ranks with subsequent return ranks, rather than portfolio performance."}
        </p>
      ) : null}
    </div>
  );
}

function EvidencePanel({ item, locale }: { item: Item; locale: Locale }) {
  const zh = locale === "zh";
  const runs = item.evidence.filter(
    (row) =>
      ["dual_engine", "backtest", "replication"].includes(row.kind) &&
      row.status !== "unavailable",
  );
  const studies = item.evidence.filter((row) => row.kind === "factor_lab");
  return (
    <section
      className="border-t border-border-subtle pt-6"
      aria-label={zh ? "研究与回测证据" : "Research evidence"}
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        <h3 className="text-base font-semibold">
          {zh ? "研究与回测" : "Research & backtests"}
        </h3>
        <span className="text-xs text-text-secondary">
          {item.evidence.length
            ? `${item.evidence.length} ${zh ? "份记录" : "records"}`
            : zh
              ? "尚无真实评估记录"
              : "No real evaluation yet"}
        </span>
      </div>
      {runs.length ? (
        <>
          <div
            aria-label={zh ? "研究与回测证据" : "Research & backtests"}
            className="overflow-x-auto"
            role="region"
            tabIndex={0}
          >
            <table className="w-full min-w-[480px] text-left text-sm">
              <thead className="border-b border-border-subtle text-xs text-text-secondary">
                <tr>
                  {[
                    zh ? "评价来源" : "Engine",
                    "Sharpe",
                    zh ? "总收益" : "Return",
                    zh ? "最大回撤" : "Drawdown",
                  ].map((label) => (
                    <th className="py-3 pr-3 font-medium" key={label}>
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {runs.map((row, i) => (
                  <tr
                    className="border-b border-border-subtle/60"
                    key={`${row.engine}-${i}`}
                  >
                    <td className="py-4 pr-3">
                      <p className="font-medium">{row.engine}</p>
                      <p className="mt-1 text-[11px] text-text-secondary">
                        {row.start && row.end
                          ? `${row.start} → ${row.end}`
                          : (row.created_at?.slice(0, 10) ?? "—")}
                      </p>
                    </td>
                    <td className="font-mono text-lg">
                      {numeric(row.metrics.sharpe, 4)}
                    </td>
                    <td className="font-mono">
                      {percent(row.metrics.total_return)}
                    </td>
                    <td className="font-mono text-danger">
                      {percent(row.metrics.max_drawdown, true)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <TableScrollHint label={tableScrollHintText[locale]} />
          {item.comparison ? (
            <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-xs">
              <span
                className={
                  item.comparison.status === "accepted"
                    ? "text-success"
                    : "text-warning"
                }
              >
                {zh ? "双引擎执行比较" : "Engine comparison"} ·{" "}
                {item.comparison.status === "accepted"
                  ? zh
                    ? "一致"
                    : "Matched"
                  : zh
                    ? "未通过或待核对"
                    : "Not matched / unavailable"}
              </span>
              <span className="text-text-secondary">
                {zh ? "收益相关性" : "Return correlation"}{" "}
                <span className="font-mono text-text-primary">
                  {numeric(item.comparison.daily_return_correlation, 6)}
                </span>
              </span>
              <span className="text-text-secondary">
                {zh ? "最终净值差" : "Terminal NAV difference"}{" "}
                <span className="font-mono text-text-primary">
                  {numeric(item.comparison.terminal_nav_difference_bps, 2)} bp
                </span>
              </span>
            </div>
          ) : null}
          <div className="mt-4 space-y-2 text-xs leading-6 text-text-secondary">
            {[...new Set(runs.map((row) => row.note))].map((note) => (
              <p key={note}>{note}</p>
            ))}
            {runs.some((row) => row.metrics.total_return == null) ? (
              <p>
                {zh
                  ? "部分引擎原始记录没有提供总收益，表中保留为 —；没有借用另一引擎的数值。"
                  : "Some original engine records omit total return; it remains —, not copied from another engine."}
              </p>
            ) : null}
            {item.comparison ? (
              <p>
                {zh
                  ? "一致表示两套引擎对同一输入的执行结果相近，不表示通过了独立样本外检验。"
                  : "A match confirms execution consistency on the same inputs, not an independent out-of-sample test."}
              </p>
            ) : null}
          </div>
        </>
      ) : studies.length === 0 ? (
        <div className="rounded-lg bg-bg-surface-muted/50 px-4 py-5 text-sm leading-7 text-text-secondary">
          {item.implementation_status === "draft"
            ? zh
              ? "这份草稿尚无可执行实现，不能给它展示另一条策略的回测结果。"
              : "This draft has no executable implementation or corresponding backtest."
            : item.kind === "factor"
              ? zh
                ? "这是计算信号的因子，需要单独研究预测能力，或在明确的策略组合中回测。组合收益不会当作该因子的独立业绩。"
                : "This factor computes a signal. Portfolio returns are not attributed as its standalone performance."
              : item.kind === "research"
                ? zh
                  ? "该研究的原始回测记录目前无法核对，指标暂不展示。具体原因见下方当前记录。"
                  : "This research's original backtest records cannot currently be verified. See the notes below."
                : zh
                  ? "这是可配置的策略模板，尚未找到对应的真实评估。这里不会显示示例回测的收益。"
                  : "No matching real evaluation has been found for this configurable template."}
        </div>
      ) : null}
      {studies.map((row, i) => (
        <FactorStudy key={i} evidence={row} zh={zh} />
      ))}
    </section>
  );
}

function ItemDetail({ item, locale }: { item: Item; locale: Locale }) {
  const zh = locale === "zh";
  const ready = introReady(item);
  const sections = [
    [zh ? "怎样工作" : "How it works", item.intro.logic],
    [zh ? "适合怎样使用" : "Use", item.intro.usage],
    [zh ? "实现边界" : "Limitations", item.intro.limitations],
  ] as const;
  return (
    <article
      className="min-w-0 p-5 sm:p-7 lg:p-8"
      aria-label={`${zh ? "详情" : "Details"} ${title(item, locale)}`}
    >
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <span className="text-[var(--color-hermes)]">
          {names[locale][item.kind]}
        </span>
        <span className="rounded-full bg-bg-surface-muted px-3 py-1 text-text-secondary">
          {status(item, zh)}
        </span>
      </div>
      <h2 className="mt-4 break-words text-2xl font-semibold leading-snug tracking-tight sm:text-3xl">
        {title(item, locale)}
      </h2>
      <p className="mt-2 break-all font-mono text-[11px] text-text-secondary">
        {item.id}
      </p>
      <div className="mt-6">
        <p className="max-w-4xl whitespace-pre-line text-[15px] leading-8">
          {ready ? item.intro.summary : item.description}
        </p>
        <p className="mt-3 text-[11px] text-text-secondary">
          {ready
            ? `${item.intro.model} · ${item.intro.reasoning_effort} · ${zh ? "结合实现代码生成" : "Generated from implementation"} · ${item.intro.generated_at?.slice(0, 10)}`
            : zh
              ? "当前显示注册说明；源码介绍尚未生成或需要更新。"
              : "Registry description; code-based introduction is not yet available."}
        </p>
        {item.intro.error ? (
          <p className="mt-2 text-xs text-warning">{item.intro.error}</p>
        ) : null}
      </div>
      <div className="mt-7">
        {item.key.startsWith("research:strategy-") ? <p className="mb-4 text-sm leading-7 text-text-secondary">{zh ? "以下为这份完整策略已保存的历史验证。它保留自己的因子权重、仓位和调仓频率；继续验证请打开下方对应策略，不套用旧单因子参考规则。" : "Saved validation of this exact strategy, with its own weights, exposure and rebalance schedule. Continue from the matching strategy below."}</p> : <ItemEvaluationSummary
          key={item.key}
          itemKey={item.key}
          locale={locale}
        />}
        <EvidencePanel item={item} locale={locale} />
      </div>
      {ready ? (
        <div className="my-7 grid gap-6 xl:grid-cols-3">
          {sections.map(([label, lines]) => (
            <section key={label}>
              <h3 className="mb-3 text-sm font-semibold">{label}</h3>
              <ul className="space-y-2 text-[13px] leading-7 text-text-secondary">
                {lines.map((line, i) => (
                  <li key={i} className="border-l border-border-strong pl-3">
                    {line}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      ) : (
        <div className="h-6" />
      )}
      {item.universe.length ? (
        <div className="mb-6 flex flex-wrap items-center gap-2">
          <span className="mr-1 text-xs text-text-secondary">
            {zh ? "研究范围" : "Universe"}
          </span>
          {item.universe.map((symbol) => (
            <span
              key={symbol}
              className="rounded bg-bg-surface-muted px-2 py-1 font-mono text-[11px]"
            >
              {symbol}
            </span>
          ))}
        </div>
      ) : null}
      {item.notes.length ? (
        <section className="mt-6 border-t border-border-subtle pt-5">
          <h3 className="text-sm font-medium">
            {zh ? "当前记录" : "Current notes"}
          </h3>
          <ul className="mt-3 space-y-2 text-xs leading-6 text-text-secondary">
            {item.notes.map((note, i) => (
              <li key={i}>{note}</li>
            ))}
          </ul>
        </section>
      ) : null}
      <div className="mt-7 flex flex-wrap gap-3">
        {item.links.map((link) => (
          <Link
            key={link.href}
            href={
              link.href.startsWith("/api/")
                ? link.href
                : localizePath(link.href, locale)
            }
            prefetch={false}
            className="app-touch-target inline-flex items-center gap-2 rounded-md border border-border-strong px-4 text-sm transition-colors hover:border-[var(--color-hermes)] hover:bg-bg-surface-muted"
          >
            {link.label}
            <ArrowUpRight size={14} />
          </Link>
        ))}
      </div>
      <details className="mt-7 border-t border-border-subtle pt-3">
        <summary className="app-touch-target cursor-pointer py-3 text-xs text-text-secondary">
          {zh ? "源码与原始记录" : "Source and raw records"}
        </summary>
        <div className="space-y-3 py-3 text-xs text-text-secondary">
          {item.source_refs.map((ref, index) => (
            <div key={`${ref.path}:${ref.label}:${ref.digest}:${index}`}>
              <p className="font-medium text-text-primary">{ref.label}</p>
              <p className="mt-1 break-all font-mono text-[10px]">{ref.path}</p>
              <p className="mt-1 break-all font-mono text-[10px]">
                SHA256 {ref.digest}
              </p>
            </div>
          ))}
          {item.evidence.map((row, index) => (
            <div
              key={`${row.engine}-${index}`}
              className="border-t border-border-subtle pt-3"
            >
              <p className="font-medium text-text-primary">
                {row.engine} ·{" "}
                {row.source ??
                  (zh ? "数据源未记录" : "Data source not recorded")}
              </p>
              {row.run_id ? (
                <p className="mt-1 break-all font-mono text-[10px]">
                  {row.run_id}
                </p>
              ) : null}
              {row.source_ref ? (
                <p className="mt-1 break-all font-mono text-[10px]">
                  {row.source_ref}
                </p>
              ) : null}
            </div>
          ))}
        </div>
      </details>
    </article>
  );
}

export function CollectionWorkbench({
  data,
  locale,
  initialKey,
}: {
  data: Catalog;
  locale: Locale;
  initialKey?: string;
}) {
  const zh = locale === "zh";
  const items = data.items.map(materialize);
  const initial = items.find((item) => item.key === initialKey);
  const [kind, setKind] = useState<Kind>(initial?.kind ?? "research");
  const [selected, setSelected] = useState<string | null>(initial?.key ?? null);
  const [query, setQuery] = useState("");
  const visible = items.filter(
    (item) =>
      item.kind === kind &&
      `${item.name} ${item.name_en} ${item.id} ${item.description} ${item.intro.summary ?? ""}`
        .toLowerCase()
        .includes(query.trim().toLowerCase()),
  );
  const active = visible.find((item) => item.key === selected) ?? visible[0];
  return (
    <div className="mx-auto w-full max-w-[1640px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <header className="flex flex-wrap items-start justify-between gap-5">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">
            {zh ? "策略与因子" : "Strategies & factors"}
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-7 text-text-secondary">
            {zh
              ? "看懂每个想法的实现，找到它的研究结果，再跟踪模拟表现。"
              : "Understand the implementation, examine the research and follow paper performance."}
          </p>
        </div>
        <div className="flex flex-wrap gap-3"><Link
          className="app-touch-target inline-flex items-center gap-2 rounded-md border border-[var(--color-hermes)] px-5 text-sm font-medium text-[var(--color-hermes)] hover:bg-bg-surface"
          href={localizePath("/strategy-library", locale)}
        >
          <Layers3 size={16} />
          {zh ? "我的策略" : "My strategies"}
        </Link><Link
          className="app-touch-target inline-flex items-center gap-2 rounded-md bg-[var(--color-hermes)] px-5 text-sm font-medium text-bg-base hover:brightness-110"
          href={localizePath("/hermes", locale)}
        >
          <FlaskConical size={16} />
          {zh ? "把新想法交给 Hermes" : "Research an idea"}
        </Link></div>
      </header>
      <div className="mt-7 flex flex-wrap items-center justify-between gap-3 border-b border-border-subtle pb-4">
        <nav
          aria-label={zh ? "资料分类" : "Collection categories"}
          className="flex flex-wrap gap-1"
        >
          {(["research", "strategy", "factor"] as Kind[]).map((value) => {
            const Icon =
              value === "research"
                ? FlaskConical
                : value === "strategy"
                  ? Layers3
                  : Sigma;
            return (
              <button
                key={value}
                type="button"
                aria-pressed={kind === value}
                onClick={() => {
                  setKind(value);
                  setSelected(null);
                  setQuery("");
                }}
                className={`app-touch-target inline-flex items-center gap-2 whitespace-nowrap rounded-md px-4 text-sm ${kind === value ? "bg-bg-surface-muted font-medium text-[var(--color-hermes)]" : "text-text-secondary hover:bg-bg-surface"}`}
              >
                <Icon size={15} />
                {names[locale][value]}
                <span className="ml-1 font-mono text-xs opacity-70">
                  {data.items.filter((item) => item.kind === value).length}
                </span>
              </button>
            );
          })}
        </nav>
        <div className="flex flex-wrap gap-4 text-xs text-text-secondary">
          {[
            ["/research-evaluation", zh ? "策略研究与回测" : "Strategy research & backtests"],
            ["/backtest", zh ? "回测工具" : "Backtester"],
            ["/factor-lab", zh ? "因子实验室" : "Factor lab"],
            ["/paper-trading", zh ? "模拟表现" : "Paper performance"],
          ].map(([href, label]) => (
            <Link
              prefetch={false}
              className="app-touch-target inline-flex items-center gap-1 hover:text-text-primary"
              key={href}
              href={localizePath(href, locale)}
            >
              {label}
              <ArrowUpRight size={12} />
            </Link>
          ))}
        </div>
      </div>
      <p className="mt-3 text-xs leading-6 text-text-secondary">{zh ? "策略研究与回测：横向比较固定方案，查看每期选股、成交和收益依据；因子组件与可执行策略分别评价。" : "Strategy research & backtests compares fixed profiles and shows the selections, fills and evidence behind returns. Factor components and executable strategies are evaluated separately."}</p>
      <p className="py-4 text-xs leading-6 text-text-secondary">
        {kind === "research"
          ? zh
            ? "每项研究绑定具体实现与回测记录。双引擎比较、历史更正和模拟状态分别展示。"
            : "Implementation, engine comparison and paper status are shown separately."
          : kind === "factor"
            ? zh
              ? "因子是策略的组成部分。这里展示因子自身的预测研究，不把组合收益分摊给它。"
              : "Factors show their own predictive studies, not borrowed portfolio returns."
            : zh
              ? "模板定义选股和调仓方式。实际效果取决于因子、参数和数据范围。"
              : "Templates define portfolio construction; results depend on factors, parameters and data."}
        {data.excluded_sample_runs > 0
          ? zh
            ? ` 已从业绩展示排除 ${data.excluded_sample_runs} 条示例回测。`
            : ` ${data.excluded_sample_runs} sample runs excluded.`
          : ""}
      </p>
      <div className="grid min-h-[600px] overflow-hidden rounded-xl border border-border-subtle bg-bg-surface/40 lg:grid-cols-[minmax(260px,320px)_minmax(0,1fr)]">
        <aside className="min-w-0 border-b border-border-subtle bg-bg-sidebar/50 lg:border-b-0 lg:border-r">
          <label className="m-4 flex items-center gap-2 rounded-md border border-border-subtle bg-bg-base px-3">
            <Search size={15} className="shrink-0 text-text-secondary" />
            <input
              className="h-10 min-w-0 w-full bg-transparent text-sm outline-none placeholder:text-text-secondary"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={
                zh ? "搜索名称或介绍" : "Search names or descriptions"
              }
              aria-label={zh ? "搜索策略与因子" : "Search collection"}
            />
          </label>
          <div
            className="max-h-[300px] overflow-y-auto pb-3 lg:max-h-[850px]"
            aria-label={zh ? "条目列表" : "Items"}
          >
            {visible.map((item) => (
              <button
                key={item.key}
                type="button"
                aria-pressed={active?.key === item.key}
                onClick={() => setSelected(item.key)}
                className={`group flex w-full items-start gap-3 border-l-2 px-5 py-4 text-left transition-colors ${active?.key === item.key ? "border-[var(--color-hermes)] bg-bg-surface-muted" : "border-transparent hover:bg-bg-surface"}`}
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium leading-6">
                    {title(item, locale)}
                  </p>
                  <p className="mt-2 line-clamp-2 text-xs leading-6 text-text-secondary">
                    {introReady(item) ? item.intro.summary : item.description}
                  </p>
                  <p className="mt-2 text-[10px] text-[var(--color-hermes)]">
                    {status(item, zh)}
                  </p>
                </div>
                <ChevronRight
                  size={15}
                  className="mt-1 shrink-0 text-text-secondary"
                />
              </button>
            ))}
          </div>
          {!visible.length ? (
            <p className="px-5 py-7 text-sm text-text-secondary">
              {zh ? "没有匹配的条目" : "No matching items"}
            </p>
          ) : null}
        </aside>
        {active ? (
          <ItemDetail key={active.key} item={active} locale={locale} />
        ) : (
          <div className="flex min-h-64 flex-col items-center justify-center gap-3 text-text-secondary">
            <BookOpen size={24} />
            <p className="text-sm">
              {zh
                ? "这里会展示所选条目的说明和真实记录"
                : "Select an item to inspect its implementation and records"}
            </p>
          </div>
        )}
      </div>
      <p className="mt-4 flex items-center gap-2 text-[11px] text-text-secondary">
        <Code2 size={12} />
        {zh
          ? "介绍依据实际代码生成；运行记录保留原始来源和区间。"
          : "Introductions are code-based; records retain original sources and periods."}
      </p>
    </div>
  );
}
