import { Database, ExternalLink, Link2, RotateCcw, Search } from "lucide-react";
import Link from "next/link";

import { Card, StatusPill } from "@/components/ui/primitives";
import { formatDateTime } from "@/components/hermes/artifacts/formatters";
import {
  resultAuthorityLabel,
  resultDisplayTitle,
  resultFreshnessLabel,
  resultFreshnessTone,
  resultKindLabel,
  resultReadStatusLabel,
  resultReadStatusTone,
  resultSourceLabel,
  resultStatusLabel,
  resultSummaryText,
  resultWarningText,
} from "@/lib/hermes/resultsPresentation";
import {
  hermesResultKey,
  type HermesResultItem,
  type HermesResultItemHrefs,
  type HermesResultsEnvelope,
  type HermesResultsFilterModel,
  type HermesResultsPaginationModel,
} from "@/lib/hermes/resultsTypes";
import type { Locale } from "@/lib/locale";

export type UnifiedResultsIndexProps = {
  envelope: HermesResultsEnvelope;
  locale: Locale;
  itemHrefs: HermesResultItemHrefs;
  filters: HermesResultsFilterModel;
  pagination: HermesResultsPaginationModel;
};

const copy = {
  en: {
    title: "Unified results",
    subtitle:
      "Read-only index across authoritative platform and HQA result stores. It does not enumerate standalone Hermes runs; Hermes appears only through exact links attached to a result.",
    sourceStatus: "Source status",
    filterAria: "Result filters",
    activeFilters: "Active filters",
    clear: "Clear filters",
    searchLabel: "Search unified results",
    searchPlaceholder: "Search title, summary, or resource ID",
    searchSubmit: "Search results",
    resultList: "Unified result records",
    status: "status",
    read: "read",
    source: "source",
    authority: "authority",
    exactLinks: "exact run links",
    exactLinksEmpty: "0 exact run links",
    exactLinksUnavailable: "link authority unavailable",
    degradedTitle: "Some result sources are degraded",
    degradedBody:
      "Available records remain readable. Missing or corrupt records stay visible and are never presented as successful results.",
    emptyTitle: "No unified results",
    emptyBody: "The catalog read succeeded, but no results match the current filter state.",
    outOfRangeTitle: "This results page is out of range",
    outOfRangeBody:
      "There are no results on this page. Return to the previous page or adjust the filters.",
    unavailableTitle: "Results catalog unavailable",
    unavailableBody:
      "Result availability cannot be determined. This is not an empty catalog.",
    range: "Showing",
    of: "of",
    unknownTotal: "total unknown",
    emptyPageCount: "0 results on this page",
    totalLabel: "total",
    previous: "Previous",
    next: "Next",
  },
  zh: {
    title: "统一结果",
    subtitle:
      "查看已保存的研究、回测和运行记录。每条结果保留原始来源，以及实际记录的 Hermes 会话关联。",
    sourceStatus: "来源状态",
    filterAria: "结果筛选",
    activeFilters: "当前筛选",
    clear: "清除筛选",
    searchLabel: "搜索统一结果",
    searchPlaceholder: "搜索标题或摘要",
    searchSubmit: "搜索结果",
    resultList: "统一结果记录",
    status: "状态",
    read: "读取",
    source: "来源",
    authority: "原始记录来源",
    exactLinks: "条精确运行关联",
    exactLinksEmpty: "0 条精确运行关联",
    exactLinksUnavailable: "会话关联暂时无法读取",
    degradedTitle: "部分结果来源已降级",
    degradedBody: "可用记录仍可读取；缺失或损坏记录会保留显示，绝不会伪装成成功结果。",
    emptyTitle: "暂无统一结果",
    emptyBody: "结果目录读取成功，但当前筛选条件下没有结果。",
    outOfRangeTitle: "本页已超出结果范围",
    outOfRangeBody: "当前页没有结果，请返回上一页或重新调整筛选条件。",
    unavailableTitle: "结果目录不可用",
    unavailableBody: "当前无法判断是否存在结果；这不是空目录。",
    range: "当前显示",
    of: "共",
    unknownTotal: "总数未知",
    emptyPageCount: "本页 0 条",
    totalLabel: "共",
    previous: "上一页",
    next: "下一页",
  },
} as const;

const focusClass =
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info";

function ResultRow({
  item,
  href,
  locale,
}: {
  item: HermesResultItem;
  href: string | undefined;
  locale: Locale;
}) {
  const text = copy[locale];
  const runLinks = item.run_links ?? null;
  const content = (
    <>
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <Database className="mt-0.5 shrink-0 text-text-secondary" size={16} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-label-caps text-info">{resultKindLabel(item.kind, locale)}</span>
          </div>
          <h3 className="mt-1 font-body-sm font-semibold text-text-primary">
            {resultDisplayTitle(item, locale)}
          </h3>
          {resultSummaryText(item, locale) ? (
            <p className="mt-1 font-body-sm text-text-secondary">
              {resultSummaryText(item, locale)}
            </p>
          ) : null}
          <div className="mt-2 flex flex-wrap gap-1.5">
            {item.data_mode === "sample" && <StatusPill label="" value={locale === "zh" ? "样例数据 · 非真实表现" : "SAMPLE · NOT REAL PERFORMANCE"} tone="warning" />}
            <StatusPill label={text.status} value={resultStatusLabel(item.status, locale)} />
            <StatusPill
              label={text.read}
              value={resultReadStatusLabel(item.read_status, locale)}
              tone={resultReadStatusTone(item.read_status)}
            />
            {item.freshness === "stale" ? (
              <StatusPill
                label=""
                value={resultFreshnessLabel(item.freshness, locale)}
                tone={resultFreshnessTone(item.freshness)}
              />
            ) : null}
            <StatusPill label={text.source} value={resultSourceLabel(item.source, locale)} />
          </div>
          <p className="mt-2 font-body-sm text-text-secondary">
            <span className="font-semibold text-text-primary">{text.authority}: </span>
            {resultAuthorityLabel(item.authority, locale)}
          </p>
          <p className="mt-1 font-data-mono text-xs text-text-secondary">
            <time dateTime={item.occurred_at}>{formatDateTime(item.occurred_at, locale)}</time>
            <span
              className={`ml-3 inline-flex items-center gap-1 ${
                runLinks === null ? "text-warning" : ""
              }`}
              data-hermes-result-run-links-state={
                runLinks === null
                  ? "unavailable"
                  : runLinks.length
                    ? "linked"
                    : "empty"
              }
            >
              <Link2 size={12} />
              {runLinks === null
                ? text.exactLinksUnavailable
                : runLinks.length
                  ? `${runLinks.length} ${text.exactLinks}`
                  : text.exactLinksEmpty}
            </span>
          </p>
        </div>
      </div>
      {href ? <ExternalLink className="shrink-0 text-text-secondary" size={15} /> : null}
    </>
  );

  return (
    <li
      data-hermes-result-key={hermesResultKey(item)}
      data-hermes-result-read-status={item.read_status}
    >
      {href ? (
        <Link
          className={`flex min-h-11 items-start gap-3 rounded-lg border border-border-subtle bg-bg-surface p-4 transition-colors hover:border-info/40 hover:bg-info/5 ${focusClass}`}
          href={href}
          prefetch={false}
        >
          {content}
        </Link>
      ) : (
        <article className="flex items-start gap-3 rounded-lg border border-border-subtle bg-bg-surface p-4">
          {content}
        </article>
      )}
    </li>
  );
}

export function UnifiedResultsIndex({
  envelope,
  locale,
  itemHrefs,
  filters,
  pagination,
}: UnifiedResultsIndexProps) {
  const text = copy[locale];
  const isOutOfRange =
    !envelope.apiError &&
    envelope.total_is_exact &&
    typeof envelope.total === "number" &&
    envelope.items.length === 0 &&
    envelope.offset > 0 &&
    envelope.offset >= envelope.total;
  const readState = envelope.apiError
    ? "unavailable"
    : isOutOfRange
      ? "out_of_range"
    : envelope.read_status === "available" && envelope.total_is_exact && envelope.total === 0
      ? "empty"
      : envelope.read_status;
  const first = envelope.items.length ? envelope.offset + 1 : 0;
  const last = envelope.offset + envelope.items.length;

  return (
    <section aria-labelledby="unified-results-title" className="space-y-4" data-hermes-results-index>
      <header className="space-y-2">
        <h2 className="font-headline-lg text-text-primary" id="unified-results-title">
          {text.title}
        </h2>
        <p className="max-w-3xl font-body-sm text-text-secondary">{text.subtitle}</p>
      </header>

      {envelope.sources.length ? (
        <section aria-labelledby="result-source-status-title">
          <h3 className="font-label-caps text-text-secondary" id="result-source-status-title">
            {text.sourceStatus}
          </h3>
          <ul className="mt-2 flex flex-wrap gap-2" data-hermes-result-sources>
            {envelope.sources.map((source) => (
              <li key={source.source}>
                <StatusPill
                  label={resultSourceLabel(source.source, locale)}
                  value={`${resultReadStatusLabel(source.read_status, locale)} · ${source.item_count}`}
                  tone={resultReadStatusTone(source.read_status)}
                />
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {envelope.read_status === "degraded" ? (
        <div data-hermes-results-degraded role="status">
          <Card tone="warning">
            <p className="font-body-sm font-semibold text-warning">{text.degradedTitle}</p>
            <p className="mt-1 font-body-sm text-text-secondary">{text.degradedBody}</p>
            {envelope.warnings.length ? (
              <ul className="mt-2 space-y-1 font-data-mono text-xs text-text-secondary">
                {envelope.warnings.map((warning, index) => (
                  <li key={`${warning.source}:${warning.code}:${warning.resource_id ?? index}`}>
                    {resultWarningText(warning, locale)}
                  </li>
                ))}
              </ul>
            ) : null}
          </Card>
        </div>
      ) : null}

      {readState === "unavailable" ? (
        <div data-hermes-results-unavailable role="alert">
          <Card tone="danger">
            <p className="font-body-sm font-semibold text-danger">{text.unavailableTitle}</p>
            <p className="mt-1 font-body-sm text-text-secondary">{text.unavailableBody}</p>
            {envelope.apiError ? (
              <p className="mt-2 break-words font-data-mono text-xs text-danger">
                {envelope.apiError}
              </p>
            ) : null}
            {envelope.warnings.length ? (
              <ul className="mt-2 space-y-1 font-data-mono text-xs text-text-secondary">
                {envelope.warnings.map((warning, index) => (
                  <li key={`${warning.source}:${warning.code}:${warning.resource_id ?? index}`}>
                    {resultWarningText(warning, locale)}
                  </li>
                ))}
              </ul>
            ) : null}
          </Card>
        </div>
      ) : null}

      {filters.groups.length ? (
        <nav aria-label={text.filterAria} className="space-y-3 rounded-lg border border-border-subtle bg-bg-surface p-3">
          <form
            action={filters.search.action}
            className="flex flex-col gap-2 sm:flex-row"
            method="get"
            role="search"
          >
            {filters.search.hiddenFields.map((field) => (
              <input key={field.name} name={field.name} type="hidden" value={field.value} />
            ))}
            <label className="sr-only" htmlFor="hermes-results-search">
              {text.searchLabel}
            </label>
            <div className="relative min-w-0 flex-1">
              <Search
                aria-hidden="true"
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary"
                size={15}
              />
              <input
                className={`min-h-11 w-full rounded-lg border border-border-subtle bg-bg-base py-2 pl-9 pr-3 font-body-sm text-text-primary placeholder:text-text-secondary ${focusClass}`}
                defaultValue={filters.search.value}
                id="hermes-results-search"
                maxLength={256}
                name="search"
                placeholder={text.searchPlaceholder}
                type="search"
              />
            </div>
            <button
              className={`inline-flex min-h-11 items-center justify-center rounded-lg border border-info/40 bg-info/10 px-4 font-data-mono text-xs text-info hover:bg-info/15 ${focusClass}`}
              type="submit"
            >
              {text.searchSubmit}
            </button>
          </form>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-body-sm text-text-secondary">
              <span className="font-semibold text-text-primary">{text.activeFilters}: </span>
              {filters.activeSummary ?? "—"}
            </p>
            {filters.clearHref ? (
              <Link
                className={`inline-flex min-h-11 items-center gap-1 rounded-lg px-3 font-data-mono text-xs text-info hover:bg-info/10 ${focusClass}`}
                href={filters.clearHref}
                prefetch={false}
              >
                <RotateCcw size={13} /> {text.clear}
              </Link>
            ) : null}
          </div>
          {filters.groups.map((group) => (
            <div className="flex flex-wrap items-center gap-2" key={group.key}>
              <span className="w-full font-label-caps text-text-secondary sm:w-28">{group.label}</span>
              <ul className="flex flex-wrap gap-1.5">
                {group.options.map((option) => (
                  <li key={option.key}>
                    <Link
                      aria-current={option.active ? "page" : undefined}
                      className={`inline-flex min-h-11 items-center rounded-lg border px-3 font-data-mono text-xs transition-colors ${focusClass} ${
                        option.active
                          ? "border-info/50 bg-info/10 text-info"
                          : "border-border-subtle text-text-secondary hover:border-info/30 hover:text-text-primary"
                      }`}
                      href={option.href}
                      prefetch={false}
                    >
                      {option.label}
                      {option.count === undefined ? null : (
                        <span className="ml-2 text-[10px] opacity-70">{option.count}</span>
                      )}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
      ) : null}

      {readState === "empty" ? (
        <div data-hermes-results-empty role="status">
          <Card>
            <p className="font-body-sm font-semibold text-text-primary">{text.emptyTitle}</p>
            <p className="mt-1 font-body-sm text-text-secondary">{text.emptyBody}</p>
          </Card>
        </div>
      ) : null}

      {readState === "out_of_range" ? (
        <div data-hermes-results-out-of-range role="status">
          <Card>
            <p className="font-body-sm font-semibold text-text-primary">
              {text.outOfRangeTitle}
            </p>
            <p className="mt-1 font-body-sm text-text-secondary">
              {text.outOfRangeBody}
            </p>
          </Card>
        </div>
      ) : null}

      {readState !== "empty" &&
      readState !== "out_of_range" &&
      readState !== "unavailable" ? (
        <ul aria-label={text.resultList} className="space-y-2" data-hermes-result-list>
          {envelope.items.map((item) => (
            <ResultRow
              href={itemHrefs[hermesResultKey(item)]}
              item={item}
              key={hermesResultKey(item)}
              locale={locale}
            />
          ))}
        </ul>
      ) : null}

      {readState !== "empty" && readState !== "unavailable" ? (
        <Card className="flex flex-wrap items-center justify-between gap-3" padded={false}>
          <p className="px-3 py-2 font-data-mono text-xs text-text-secondary">
            {envelope.items.length ? (
              <>
                {text.range} {first}–{last} {text.of}{" "}
                {envelope.total_is_exact ? envelope.total : text.unknownTotal}
              </>
            ) : (
              <>
                {text.emptyPageCount} · {text.totalLabel}{" "}
                {envelope.total_is_exact ? envelope.total : text.unknownTotal}
              </>
            )}
          </p>
          <nav
            aria-label={locale === "zh" ? "结果分页" : "Result pagination"}
            className="flex items-center gap-1 p-1"
          >
            {pagination.previousHref ? (
              <Link
                className={`inline-flex min-h-11 items-center rounded-lg px-3 font-data-mono text-xs text-info hover:bg-info/10 ${focusClass}`}
                href={pagination.previousHref}
                prefetch={false}
                rel="prev"
              >
                {text.previous}
              </Link>
            ) : (
              <span
                aria-disabled="true"
                className="inline-flex min-h-11 items-center px-3 font-data-mono text-xs text-text-secondary opacity-50"
              >
                {text.previous}
              </span>
            )}
            {pagination.nextHref ? (
              <Link
                className={`inline-flex min-h-11 items-center rounded-lg px-3 font-data-mono text-xs text-info hover:bg-info/10 ${focusClass}`}
                href={pagination.nextHref}
                prefetch={false}
                rel="next"
              >
                {text.next}
              </Link>
            ) : (
              <span
                aria-disabled="true"
                className="inline-flex min-h-11 items-center px-3 font-data-mono text-xs text-text-secondary opacity-50"
              >
                {text.next}
              </span>
            )}
          </nav>
        </Card>
      ) : null}
    </section>
  );
}
