'use client';

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
  ExternalLink,
  RefreshCw,
  Rss,
  Search,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  getAiHotDaily,
  getAiHotDailies,
  getAiHotItems,
  getAiHotStatus,
  type AiHotDailyIndex,
  type AiHotDailyResponse,
  type AiHotItem,
} from "@/lib/api";
import { useIsHydrated } from "@/lib/hydration";
import { Card, SectionTitle, StatusPill } from "@/components/ui/primitives";

type Locale = "en" | "zh";
type Tab = "feed" | "daily";
type WindowKey = "24h" | "3d" | "7d";

const inputClass =
  "rounded-lg border border-border-subtle bg-bg-surface-muted px-3 py-2 text-text-primary outline-none transition-colors focus:border-info";

const categoryOptions = [
  { value: "", en: "All categories", zh: "全部分类" },
  { value: "ai-models", en: "AI models", zh: "模型发布" },
  { value: "ai-products", en: "AI products", zh: "产品发布" },
  { value: "industry", en: "Industry", zh: "行业动态" },
  { value: "paper", en: "Papers", zh: "论文研究" },
  { value: "tip", en: "Tips", zh: "技巧观点" },
];

const copy = {
  en: {
    eyebrow: "Read-only · External beta source",
    title: "AI News Research Feed",
    subtitle:
      "AI HOT headlines for research reading. No strategy, backtest, paper account, or trade path is triggered from this page.",
    safetyCompact: "Read-only AI HOT beta. Verify summaries against originals. No strategy, backtest, paper account, or trade path is triggered.",
    mode: "Mode",
    selected: "Selected",
    all: "All",
    category: "Category",
    keyword: "Keyword",
    keywordPlaceholder: "OpenAI, Sora, agents...",
    window: "Time window",
    take: "Items",
    refresh: "Refresh",
    feed: "Feed",
    daily: "Daily",
    source: "Provider",
    beta: "Beta",
    fetched: "Fetched",
    none: "None",
    safety:
      "AI HOT is an external beta source. Summaries may be LLM-generated. Verify against original sources before citing. This page does not create trading signals, trigger strategies, or mutate the paper account.",
    feedTitle: "News feed",
    feedHint: "Read-only headlines grouped into a Beijing-time research timeline.",
    dailyTitle: "Daily report",
    dailyHint: "AI HOT daily sections and archive links.",
    dailyDate: "Daily date",
    latestDaily: "Latest",
    archive: "Recent dailies",
    openOriginal: "Open original",
    selectedBadge: "Selected",
    emptyFeed: "No AI HOT items returned for this filter.",
    emptyDaily: "No daily report returned.",
    archiveEmpty: "No daily archive entries returned.",
    loadMore: "Load more",
    loadingMore: "Loading...",
    unavailable: "Unavailable",
    beijingTime: "Beijing time",
    researchNote: "Research note",
    unknownDate: "Unscheduled",
  },
  zh: {
    eyebrow: "只读 · 外部测试版数据源",
    title: "AI 新闻研究流",
    subtitle: "读取 AI HOT 热点用于研究浏览。本页不会触发策略、回测、模拟账户或任何交易链路。",
    safetyCompact: "只读 AI HOT 测试源；摘要需回原文核对；不会触发策略、回测、模拟账户或任何交易链路。",
    mode: "模式",
    selected: "精选",
    all: "全部",
    category: "分类",
    keyword: "关键词",
    keywordPlaceholder: "OpenAI、Sora、智能体...",
    window: "时间窗",
    take: "条数",
    refresh: "刷新",
    feed: "动态",
    daily: "日报",
    source: "来源",
    beta: "测试版",
    fetched: "抓取时间",
    none: "无",
    safety:
      "AI HOT 是外部测试版数据源，摘要可能由 LLM 生成。引用前请回原文核对。本页不会生成交易信号，不会触发策略，也不会修改模拟账户。",
    feedTitle: "新闻动态",
    feedHint: "只读外部标题，按北京时间组织成研究时间轴。",
    dailyTitle: "AI 日报",
    dailyHint: "AI HOT 日报版块和近期归档。",
    dailyDate: "日报日期",
    latestDaily: "最新",
    archive: "近期日报",
    openOriginal: "打开原文",
    selectedBadge: "精选",
    emptyFeed: "当前筛选没有返回 AI HOT 条目。",
    emptyDaily: "没有返回日报内容。",
    archiveEmpty: "没有返回日报归档。",
    loadMore: "加载更多",
    loadingMore: "加载中...",
    unavailable: "不可用",
    beijingTime: "北京时间",
    researchNote: "研究关注点",
    unknownDate: "未定时间",
  },
};

export function AiNewsView({ locale = "en" }: { locale?: Locale }) {
  const text = copy[locale];
  const hydrated = useIsHydrated();
  const [tab, setTab] = useState<Tab>("feed");
  const [mode, setMode] = useState<"selected" | "all">("selected");
  const [category, setCategory] = useState("");
  const [keyword, setKeyword] = useState("");
  const [windowKey, setWindowKey] = useState<WindowKey>("24h");
  const [take, setTake] = useState(50);
  const [dailyDate, setDailyDate] = useState("");

  const since = useMemo(() => sinceForWindow(windowKey), [windowKey]);
  const normalizedKeyword = keyword.trim();
  const debouncedKeyword = useDebouncedValue(normalizedKeyword, 350);

  const statusQuery = useQuery({
    queryKey: ["aihot-status"],
    enabled: hydrated,
    queryFn: getAiHotStatus,
  });
  const itemsQuery = useInfiniteQuery({
    queryKey: ["aihot-items", mode, category, debouncedKeyword, since, take],
    enabled: hydrated,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      getAiHotItems({
        mode,
        category: category || undefined,
        cursor: typeof pageParam === "string" ? pageParam : undefined,
        q: debouncedKeyword || undefined,
        since,
        take,
      }),
    getNextPageParam: (lastPage) =>
      lastPage.has_next && lastPage.next_cursor ? lastPage.next_cursor : undefined,
  });
  const dailyQuery = useQuery({
    queryKey: ["aihot-daily", dailyDate],
    enabled: hydrated && tab === "daily",
    queryFn: () => getAiHotDaily(dailyDate || undefined),
  });
  const dailiesQuery = useQuery({
    queryKey: ["aihot-dailies"],
    enabled: hydrated && tab === "daily",
    queryFn: () => getAiHotDailies(14),
  });

  function refreshActive() {
    void statusQuery.refetch();
    if (tab === "feed") {
      void itemsQuery.refetch();
    } else {
      void dailyQuery.refetch();
      void dailiesQuery.refetch();
    }
  }

  function loadMore() {
    void itemsQuery.fetchNextPage();
  }

  const feedPages = itemsQuery.data?.pages ?? [];
  const feedItems = feedPages.flatMap((page) => page.items);
  const feedWarnings = uniqueStrings(feedPages.flatMap((page) => page.warnings ?? []));
  const feedApiError = feedPages.find((page) => page.apiError)?.apiError;
  const activeFetchedAt = tab === "feed" ? feedPages[0]?.fetched_at : dailyQuery.data?.generated_at;
  const activeWarnings = tab === "feed" ? feedWarnings : dailyQuery.data?.warnings;
  const isRefreshing =
    statusQuery.isFetching || itemsQuery.isFetching || dailyQuery.isFetching || dailiesQuery.isFetching;

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-bg-base text-text-primary">
      <main className="mx-auto flex w-full max-w-[1240px] flex-col gap-4 px-4 py-4 sm:px-6 lg:py-6">
        <div className="flex items-center gap-2 rounded-lg border border-warning/25 bg-warning/5 px-3 py-2 font-body-sm text-warning">
          <ShieldCheck className="shrink-0" size={15} />
          <span>{text.safetyCompact}</span>
        </div>

        <header className="rounded-lg border border-border-subtle bg-bg-surface p-4 sm:p-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="font-label-caps uppercase text-info">{text.eyebrow}</p>
              <div className="mt-2 flex items-center gap-2">
                <Rss className="shrink-0 text-info" size={22} />
                <h1 className="font-headline-xl text-text-primary">{text.title}</h1>
              </div>
              <p className="mt-2 max-w-3xl font-body-sm text-text-secondary">{text.subtitle}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <StatusPill
                label={text.source}
                value={statusQuery.data?.enabled === false ? text.unavailable : "AI HOT"}
                tone={statusQuery.data?.enabled === false ? "warning" : "info"}
              />
              <StatusPill label={text.beta} value={statusQuery.data?.provider_beta ? "ON" : "--"} tone="warning" />
              <StatusPill label={text.fetched} value={formatDateTime(activeFetchedAt, locale) || text.none} />
              <button
                className="inline-flex h-8 items-center justify-center gap-2 rounded-lg border border-border-subtle bg-bg-surface-muted px-3 font-body-sm text-text-primary transition-colors hover:border-info hover:text-info disabled:opacity-50"
                disabled={!hydrated || isRefreshing}
                onClick={refreshActive}
                title={text.refresh}
                type="button"
              >
                <RefreshCw className={isRefreshing ? "animate-spin" : ""} size={15} />
                {text.refresh}
              </button>
            </div>
          </div>

          <form className="mt-4 border-t border-border-subtle pt-4" onSubmit={(event) => event.preventDefault()}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex rounded-lg border border-border-subtle bg-bg-base p-1">
                {(["feed", "daily"] as const).map((item) => (
                  <button
                    className={`rounded-md px-3 py-1.5 font-body-sm transition-colors ${
                      tab === item
                        ? "bg-bg-surface-muted text-text-primary"
                        : "text-text-secondary hover:text-text-primary"
                    }`}
                    key={item}
                    onClick={() => setTab(item)}
                    type="button"
                  >
                    {item === "feed" ? text.feed : text.daily}
                  </button>
                ))}
              </div>

              {tab === "feed" ? (
                <label className="flex min-w-[240px] flex-1 items-center gap-2 rounded-lg border border-border-subtle bg-bg-base px-3 py-2 font-body-sm text-text-secondary focus-within:border-info sm:max-w-sm">
                  <Search size={16} className="shrink-0" />
                  <input
                    className="min-w-0 flex-1 bg-transparent text-text-primary outline-none"
                    onChange={(event) => setKeyword(event.target.value)}
                    placeholder={text.keywordPlaceholder}
                    value={keyword}
                  />
                </label>
              ) : null}
            </div>

            {tab === "feed" ? (
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <div className="flex rounded-lg border border-border-subtle bg-bg-base p-1">
                  {(["selected", "all"] as const).map((item) => (
                    <button
                      className={`rounded-md px-3 py-1.5 font-body-sm transition-colors ${
                        mode === item
                          ? "bg-bg-surface-muted text-text-primary"
                          : "text-text-secondary hover:text-text-primary"
                      }`}
                      key={item}
                      onClick={() => setMode(item)}
                      type="button"
                    >
                      {item === "selected" ? text.selected : text.all}
                    </button>
                  ))}
                </div>

                <div className="flex max-w-full gap-2 overflow-x-auto pb-1">
                  {categoryOptions.map((item) => (
                    <button
                      className={`shrink-0 rounded-md border px-3 py-1.5 font-body-sm transition-colors ${
                        category === item.value
                          ? "border-info/50 bg-info/10 text-info"
                          : "border-border-subtle bg-bg-base text-text-secondary hover:bg-bg-surface-muted hover:text-text-primary"
                      }`}
                      key={item.value || "all"}
                      onClick={() => setCategory(item.value)}
                      type="button"
                    >
                      {item[locale]}
                    </button>
                  ))}
                </div>

                <div className="flex rounded-lg border border-border-subtle bg-bg-base p-1">
                  {(["24h", "3d", "7d"] as const).map((item) => (
                    <button
                      className={`rounded-md px-3 py-1.5 font-data-mono transition-colors ${
                        windowKey === item
                          ? "bg-bg-surface-muted text-text-primary"
                          : "text-text-secondary hover:text-text-primary"
                      }`}
                      key={item}
                      onClick={() => setWindowKey(item)}
                      type="button"
                    >
                      {item}
                    </button>
                  ))}
                </div>

                <label className="flex items-center gap-2 rounded-lg border border-border-subtle bg-bg-base px-3 py-1.5 font-label-caps uppercase text-text-secondary">
                  <span>{text.take}</span>
                  <input
                    className="w-12 bg-transparent font-data-mono text-text-primary outline-none"
                    max={100}
                    min={1}
                    onChange={(event) => setTake(clamp(Number(event.target.value), 1, 100))}
                    type="number"
                    value={take}
                  />
                </label>
              </div>
            ) : null}
          </form>
        </header>

        <ErrorStrip
          errors={[
            statusQuery.data?.apiError,
            tab === "feed" ? feedApiError : dailyQuery.data?.apiError,
          ]}
        />
        <OperationalWarningStrip warnings={activeWarnings ?? []} />

        {tab === "feed" ? (
          <FeedPanel
            hasNext={Boolean(itemsQuery.hasNextPage)}
            items={feedItems}
            loading={!hydrated || (itemsQuery.isFetching && feedItems.length === 0)}
            loadingMore={itemsQuery.isFetchingNextPage}
            locale={locale}
            onLoadMore={loadMore}
          />
        ) : (
          <DailyPanel
            archive={dailiesQuery.data?.items ?? []}
            daily={dailyQuery.data}
            dailyDate={dailyDate}
            loading={!hydrated || dailyQuery.isFetching}
            locale={locale}
            onDailyDateChange={setDailyDate}
          />
        )}
      </main>
    </div>
  );
}

function FeedPanel({
  hasNext,
  items,
  loading,
  loadingMore,
  locale,
  onLoadMore,
}: {
  hasNext: boolean;
  items: AiHotItem[];
  loading: boolean;
  loadingMore: boolean;
  locale: Locale;
  onLoadMore: () => void;
}) {
  const text = copy[locale];
  const groups = groupFeedItems(items, locale, text.unknownDate);

  return (
    <section className="mt-5">
      <SectionTitle title={text.feedTitle} hint={text.feedHint} />
      {loading ? <LoadingRows /> : null}
      {!loading && items.length === 0 ? <EmptyState label={text.emptyFeed} /> : null}
      <div className="grid gap-5">
        {groups.map((group) => (
          <div className="grid gap-2" key={group.label}>
            <div className="grid items-center gap-0 sm:grid-cols-[86px_28px_minmax(0,1fr)]">
              <div className="pr-2 font-body-md text-text-secondary sm:text-right">{group.label}</div>
              <div className="hidden md:block" />
            </div>
            <div className="grid gap-0">
              {group.items.map((item) => (
                <TimelineArticle item={item} key={item.id} locale={locale} />
              ))}
            </div>
          </div>
        ))}
      </div>
      {!loading && hasNext ? (
        <div className="mt-4 flex justify-center">
          <button
            className="inline-flex h-9 items-center justify-center rounded-lg border border-border-subtle bg-bg-surface px-4 font-body-sm text-text-primary transition-colors hover:border-info hover:text-info disabled:opacity-50"
            disabled={loadingMore}
            onClick={onLoadMore}
            type="button"
          >
            {loadingMore ? text.loadingMore : text.loadMore}
          </button>
        </div>
      ) : null}
    </section>
  );
}

function TimelineArticle({ item, locale }: { item: AiHotItem; locale: Locale }) {
  const text = copy[locale];
  const time = formatTime(item.published_at, locale);
  const summary = item.summary || item.title_en || "";
  const safeUrl = safeExternalUrl(item.url);

  return (
    <div className="grid grid-cols-[52px_18px_minmax(0,1fr)] pb-2 sm:grid-cols-[86px_28px_minmax(0,1fr)]">
      <div className="pr-2 pt-3 text-right font-data-mono text-[14px] font-extrabold leading-5 text-text-primary sm:text-[18px]">
        {time || text.unknownDate}
      </div>
      <div className="relative flex justify-center">
        <span className="absolute inset-y-0 w-px bg-border-subtle/80" />
        <span className="relative mt-[18px] h-2 w-2 rounded-full bg-info/80 shadow-[0_0_0_4px_rgba(56,189,248,0.10)]" />
      </div>
      <article className="group rounded-lg border border-border-subtle bg-bg-surface px-4 py-3.5 transition-colors hover:bg-bg-surface-muted/60">
        <div className="mb-1.5 flex items-start justify-between gap-3">
          <div className="min-w-0 truncate text-[11px] leading-[11px] text-text-secondary/70">
            {item.source}
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {item.selected ? (
              <span className="rounded-md border border-warning/30 bg-warning/10 px-2 py-[3px] font-data-mono text-[10.5px] font-semibold leading-none text-warning">
                {text.selectedBadge}
              </span>
            ) : null}
            {typeof item.score === "number" ? (
              <span className="rounded-md border border-info/25 bg-info/10 px-[7px] py-[3px] font-data-mono text-[11px] font-extrabold leading-none text-info">
                {scoreLabel(item.score)}
              </span>
            ) : null}
          </div>
        </div>

        {safeUrl ? (
          <a
            className="block text-[15px] font-bold leading-[22.5px] text-text-primary transition-colors hover:text-info"
            href={safeUrl}
            rel="noreferrer"
            target="_blank"
          >
            {item.title}
          </a>
        ) : (
          <div className="block text-[15px] font-bold leading-[22.5px] text-text-primary">
            {item.title}
          </div>
        )}
        {summary ? (
          <p className="mt-1.5 line-clamp-2 text-[12.5px] leading-5 text-text-secondary">{summary}</p>
        ) : null}

        <div className="mt-2 flex flex-wrap gap-1.5">
          {item.category ? (
            <span className="rounded-[5px] bg-bg-surface-muted px-2 py-1 text-[11px] leading-none text-text-secondary">
              {categoryName(item.category, locale)}
            </span>
          ) : null}
          {safeUrl ? (
            <a
              className="rounded-[5px] bg-bg-surface-muted px-2 py-1 text-[11px] leading-none text-text-secondary transition-colors hover:text-info"
              href={safeUrl}
              rel="noreferrer"
              target="_blank"
            >
              {text.openOriginal}
            </a>
          ) : null}
        </div>

      </article>
    </div>
  );
}

function DailyPanel({
  archive,
  daily,
  dailyDate,
  loading,
  locale,
  onDailyDateChange,
}: {
  archive: AiHotDailyIndex[];
  daily?: AiHotDailyResponse;
  dailyDate: string;
  loading: boolean;
  locale: Locale;
  onDailyDateChange: (value: string) => void;
}) {
  const text = copy[locale];
  return (
    <section className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_280px]">
      <div>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <SectionTitle title={text.dailyTitle} hint={text.dailyHint} />
          <label className="flex items-center gap-2 font-body-sm text-text-secondary">
            {text.dailyDate}
            <input
              className={`${inputClass} font-data-mono`}
              onChange={(event) => onDailyDateChange(event.target.value)}
              type="date"
              value={dailyDate}
            />
            <button
              className="rounded-lg border border-border-subtle px-3 py-2 text-text-primary hover:border-info hover:text-info"
              onClick={() => onDailyDateChange("")}
              type="button"
            >
              {text.latestDaily}
            </button>
          </label>
        </div>
        {loading ? <LoadingRows /> : null}
        {!loading && !daily?.date ? <EmptyState label={text.emptyDaily} /> : null}
        {!loading && daily?.date ? <DailyReport daily={daily} locale={locale} /> : null}
      </div>
      <aside>
        <SectionTitle title={text.archive} />
        <div className="grid gap-2">
          {archive.length === 0 ? <EmptyState label={text.archiveEmpty} /> : null}
          {archive.map((item) => (
            <button
              className="rounded-lg border border-border-subtle bg-bg-surface px-3 py-2 text-left transition-colors hover:border-info"
              key={item.date}
              onClick={() => onDailyDateChange(item.date)}
              type="button"
            >
              <div className="font-data-mono text-xs text-info">{item.date}</div>
              <div className="mt-1 font-body-sm text-text-secondary">{item.lead_title ?? text.none}</div>
            </button>
          ))}
        </div>
      </aside>
    </section>
  );
}

function DailyReport({ daily, locale }: { daily: AiHotDailyResponse; locale: Locale }) {
  const text = copy[locale];
  return (
    <div className="grid gap-3">
      {daily.lead ? (
        <Card>
          <div className="font-data-mono text-xs text-info">{daily.date}</div>
          <h2 className="mt-2 font-headline-lg text-text-primary">{recordText(daily.lead, "title")}</h2>
          <p className="mt-2 font-body-sm text-text-secondary">
            {recordText(daily.lead, "leadParagraph")}
          </p>
          <p className="mt-3 font-body-sm text-text-secondary">
            {formatDateTime(daily.generated_at, locale)} {text.beijingTime}
          </p>
        </Card>
      ) : null}
      {daily.sections.map((section, index) => (
        <article className="rounded-lg border border-border-subtle bg-bg-surface p-4" key={sectionKey(section, index)}>
          <h3 className="font-label-caps text-text-primary">{recordText(section, "label")}</h3>
          <div className="mt-3 grid gap-3">
            {recordItems(section).map((item, itemIndex) => (
              <DailyItem item={item} key={`${sectionKey(section, index)}-${itemIndex}`} locale={locale} />
            ))}
          </div>
        </article>
      ))}
      {daily.flashes.length > 0 ? (
        <article className="rounded-lg border border-border-subtle bg-bg-surface p-4">
          <h3 className="font-label-caps text-text-primary">Flashes</h3>
          <div className="mt-3 grid gap-2">
            {daily.flashes.map((flash, index) => (
              <DailyItem item={flash} key={`flash-${index}`} locale={locale} />
            ))}
          </div>
        </article>
      ) : null}
    </div>
  );
}

function DailyItem({ item, locale }: { item: Record<string, unknown>; locale: Locale }) {
  const text = copy[locale];
  const sourceUrl = recordText(item, "sourceUrl") || recordText(item, "url");
  const safeSourceUrl = safeExternalUrl(sourceUrl);
  return (
    <div className="rounded-lg border border-border-subtle bg-bg-surface-muted p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-body-sm font-semibold text-text-primary">{recordText(item, "title")}</div>
          <div className="mt-1 font-body-sm text-text-secondary">
            {recordText(item, "sourceName") || recordText(item, "source")}
          </div>
        </div>
        {safeSourceUrl ? (
          <a
            className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-border-subtle px-2 py-1 font-body-sm text-text-primary hover:border-info hover:text-info"
            href={safeSourceUrl}
            rel="noreferrer"
            target="_blank"
          >
            <ExternalLink size={14} />
            {text.openOriginal}
          </a>
        ) : null}
      </div>
      {recordText(item, "summary") ? (
        <p className="mt-2 font-body-sm text-text-secondary">{recordText(item, "summary")}</p>
      ) : null}
    </div>
  );
}

function ErrorStrip({ errors }: { errors: Array<string | undefined> }) {
  const active = errors.filter(Boolean);
  if (active.length === 0) {
    return null;
  }
  return (
    <div className="mt-4 rounded-lg border border-warning/40 bg-warning/5 p-3 font-body-sm text-warning">
      {active.join(" · ")}
    </div>
  );
}

function OperationalWarningStrip({ warnings }: { warnings: string[] }) {
  const operationalWarnings = warnings.filter(
    (warning) => warning && !warning.includes("external beta source"),
  );
  if (operationalWarnings.length === 0) {
    return null;
  }
  return (
    <div className="mt-4 rounded-lg border border-warning/35 bg-warning/5 p-3 font-body-sm text-warning">
      {operationalWarnings.join(" · ")}
    </div>
  );
}

function LoadingRows() {
  return (
    <div className="grid gap-3">
      {[0, 1, 2].map((item) => (
        <div className="h-28 animate-pulse rounded-lg border border-border-subtle bg-bg-surface" key={item} />
      ))}
    </div>
  );
}

function EmptyState({ label }: { label: string }) {
  return (
    <div className="rounded-lg border border-border-subtle bg-bg-surface p-6 font-body-sm text-text-secondary">
      {label}
    </div>
  );
}

function groupFeedItems(items: AiHotItem[], locale: Locale, fallbackLabel: string) {
  const groups: Array<{ label: string; items: AiHotItem[] }> = [];
  for (const item of items) {
    const label = formatDateLabel(item.published_at, locale) || fallbackLabel;
    const last = groups[groups.length - 1];
    if (last?.label === label) {
      last.items.push(item);
    } else {
      groups.push({ label, items: [item] });
    }
  }
  return groups;
}

function uniqueStrings(values: string[]) {
  return Array.from(new Set(values.filter(Boolean)));
}

function useDebouncedValue<T>(value: T, delayMs: number) {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timeoutId);
  }, [value, delayMs]);

  return debounced;
}

function sinceForWindow(windowKey: WindowKey) {
  const hours = windowKey === "24h" ? 24 : windowKey === "3d" ? 72 : 168;
  return new Date(Date.now() - hours * 60 * 60 * 1000).toISOString();
}

function clamp(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) {
    return min;
  }
  return Math.min(Math.max(value, min), max);
}

function formatDateTime(value: string | null | undefined, locale: Locale) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Shanghai",
  }).format(date);
}

function formatDateLabel(value: string | null | undefined, locale: Locale) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    month: locale === "zh" ? "numeric" : "short",
    day: "numeric",
    timeZone: "Asia/Shanghai",
  }).format(date);
}

function formatTime(value: string | null | undefined, locale: Locale) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Shanghai",
  }).format(date);
}

function scoreLabel(value: number) {
  return Math.round(value).toString();
}

function categoryName(value: string, locale: Locale) {
  return categoryOptions.find((item) => item.value === value)?.[locale] ?? value;
}

function recordText(record: Record<string, unknown> | null | undefined, key: string) {
  const value = record?.[key];
  return typeof value === "string" ? value : "";
}

function safeExternalUrl(value: string | null | undefined) {
  if (!value) {
    return "";
  }
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : "";
  } catch {
    return "";
  }
}

function recordItems(record: Record<string, unknown>) {
  const items = record.items;
  return Array.isArray(items)
    ? items.filter((item): item is Record<string, unknown> => item !== null && typeof item === "object")
    : [];
}

function sectionKey(section: Record<string, unknown>, index: number) {
  return recordText(section, "label") || `section-${index}`;
}
