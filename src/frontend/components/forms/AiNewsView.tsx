'use client';

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
  ExternalLink,
  RefreshCw,
  Rss,
  Search,
  ShieldCheck,
} from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import {
  getNewsDaily,
  getNewsDailies,
  getNewsItems,
  getNewsStatus,
  type AiHotDailyIndex,
  type AiHotDailyResponse,
  type AiHotItem,
  type NewsServedFrom,
} from "@/lib/api";
import { useIsHydrated } from "@/lib/hydration";
import {
  Card,
  SectionTitle,
  StatusPill,
  TerminalTable,
  TerminalToolbarButton,
} from "@/components/ui/primitives";

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

const aiNewsAccentRailClass =
  "bg-[linear-gradient(90deg,#2dd4bf_0%,#57c1ff_35%,#f0b90b_70%,#c084fc_100%)]";

const aiNewsHeaderWashClass =
  "bg-[linear-gradient(135deg,#2dd4bf18_0%,#57c1ff12_45%,#f0b90b10_100%)]";

type NewsTone = {
  name: string;
  badge: string;
  buttonActive: string;
  dot: string;
};

const categoryToneClasses: Record<string, NewsTone> = {
  default: {
    name: "neutral",
    badge: "border-border-subtle bg-bg-surface-muted text-text-primary",
    buttonActive: "border-text-secondary/40 bg-text-secondary/10 text-text-primary",
    dot: "bg-text-secondary/70 shadow-[0_0_0_3px_rgba(138,141,149,0.12)]",
  },
  "ai-models": {
    name: "ai-models",
    badge: "border-[#57c1ff]/45 bg-[#57c1ff]/10 text-text-primary",
    buttonActive: "border-[#57c1ff]/55 bg-[#57c1ff]/10 text-[#d8f2ff]",
    dot: "bg-[#57c1ff] shadow-[0_0_0_3px_rgba(87,193,255,0.16)]",
  },
  "ai-products": {
    name: "ai-products",
    badge: "border-[#2dd4bf]/45 bg-[#2dd4bf]/10 text-text-primary",
    buttonActive: "border-[#2dd4bf]/55 bg-[#2dd4bf]/10 text-[#d6fffb]",
    dot: "bg-[#2dd4bf] shadow-[0_0_0_3px_rgba(45,212,191,0.16)]",
  },
  industry: {
    name: "industry",
    badge: "border-[#f0b90b]/45 bg-[#f0b90b]/10 text-text-primary",
    buttonActive: "border-[#f0b90b]/55 bg-[#f0b90b]/10 text-[#ffe8a3]",
    dot: "bg-[#f0b90b] shadow-[0_0_0_3px_rgba(240,185,11,0.16)]",
  },
  paper: {
    name: "paper",
    badge: "border-[#c084fc]/45 bg-[#c084fc]/10 text-text-primary",
    buttonActive: "border-[#c084fc]/55 bg-[#c084fc]/10 text-[#eadcff]",
    dot: "bg-[#c084fc] shadow-[0_0_0_3px_rgba(192,132,252,0.16)]",
  },
  tip: {
    name: "tip",
    badge: "border-[#ff8a65]/45 bg-[#ff8a65]/10 text-text-primary",
    buttonActive: "border-[#ff8a65]/55 bg-[#ff8a65]/10 text-[#ffddcf]",
    dot: "bg-[#ff8a65] shadow-[0_0_0_3px_rgba(255,138,101,0.16)]",
  },
};

const copy = {
  en: {
    eyebrow: "Read-only · Research-only dual source",
    title: "AI News Research Feed",
    subtitle:
      "Main source: AI HOT (beta). Standby: self-hosted Horizon. Verify summaries against originals. Research-only — no strategy, backtest, paper account, or trade path is triggered from this page.",
    safetyCompact:
      "Read-only research feed. Main source AI HOT (beta); standby self-hosted Horizon. Verify originals. No strategy, backtest, paper account, or trade path is triggered.",
    safetyShort: "Research-only news. Verify originals. No strategy, backtest, paper account, or trade path.",
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
      "Main source is AI HOT (external beta); standby is self-hosted Horizon. Summaries may be LLM-generated — verify against original sources before citing. Research-only: this page does not create trading signals, trigger strategies, or mutate the paper account.",
    feedTitle: "News feed",
    feedHint: "Read-only headlines in a Beijing-time market-news blotter.",
    feedCount: "Rows",
    time: "Time",
    headline: "Headline",
    categoryColumn: "Category",
    signalColumn: "Focus",
    action: "Action",
    score: "Score",
    newTab: "opens in a new tab",
    dailyTitle: "Daily report",
    dailyHint: "Daily sections and archive links (AI HOT primary, Horizon standby).",
    dailyDate: "Daily date",
    latestDaily: "Latest",
    archive: "Recent dailies",
    openOriginal: "Open original",
    selectedBadge: "Selected",
    emptyFeed: "No news items returned for this filter.",
    emptyDaily: "No daily report returned.",
    archiveEmpty: "No daily archive entries returned.",
    loadMore: "Load more",
    loadingMore: "Loading...",
    unavailable: "Unavailable",
    beijingTime: "Beijing time",
    researchNote: "Research note",
    unknownDate: "Unscheduled",
    failoverActive: "Failover active",
    failoverBanner:
      "Primary AI HOT is unavailable — serving standby Horizon. Research-only; verify originals.",
    servedFrom: "Served from",
  },
  zh: {
    eyebrow: "只读 · 双源研究资讯",
    title: "AI 新闻研究流",
    subtitle:
      "主源：AI HOT（测试版）；备用：自托管 Horizon。摘要请回原文核对。仅供研究——本页不会触发策略、回测、模拟账户或任何交易链路。",
    safetyCompact:
      "只读研究资讯。主源 AI HOT（测试版）；备用自托管 Horizon；请回原文核对；不会触发策略、回测、模拟账户或交易链路。",
    safetyShort: "仅供研究；请回原文核对；不触发策略、回测、模拟账户或交易链路。",
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
      "主源为 AI HOT（外部测试版），备用为自托管 Horizon。摘要可能由 LLM 生成，引用前请回原文核对。仅供研究：本页不会生成交易信号，不会触发策略，也不会修改模拟账户。",
    feedTitle: "新闻动态",
    feedHint: "只读外部标题，按北京时间组织成市场新闻 blotter。",
    feedCount: "行数",
    time: "时间",
    headline: "标题",
    categoryColumn: "分类",
    signalColumn: "关注",
    action: "操作",
    score: "评分",
    newTab: "新标签页打开",
    dailyTitle: "AI 日报",
    dailyHint: "日报版块和近期归档（AI HOT 主源，Horizon 备用）。",
    dailyDate: "日报日期",
    latestDaily: "最新",
    archive: "近期日报",
    openOriginal: "打开原文",
    selectedBadge: "精选",
    emptyFeed: "当前筛选没有返回新闻条目。",
    emptyDaily: "没有返回日报内容。",
    archiveEmpty: "没有返回日报归档。",
    loadMore: "加载更多",
    loadingMore: "加载中...",
    unavailable: "不可用",
    beijingTime: "北京时间",
    researchNote: "研究关注点",
    unknownDate: "未定时间",
    failoverActive: "故障切换中",
    failoverBanner: "主源 AI HOT 不可用，当前使用备用 Horizon。仅供研究；请回原文核对。",
    servedFrom: "供应路径",
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
  const [mobileSearchOpen, setMobileSearchOpen] = useState(false);

  const since = useMemo(() => sinceForWindow(windowKey), [windowKey]);
  const normalizedKeyword = keyword.trim();
  const debouncedKeyword = useDebouncedValue(normalizedKeyword, 350);

  const statusQuery = useQuery({
    queryKey: ["news-status"],
    enabled: hydrated,
    queryFn: getNewsStatus,
  });
  const itemsQuery = useInfiniteQuery({
    queryKey: ["news-items", mode, category, debouncedKeyword, since, take],
    enabled: hydrated,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      getNewsItems({
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
    queryKey: ["news-daily", dailyDate],
    enabled: hydrated && tab === "daily",
    queryFn: () => getNewsDaily(dailyDate || undefined),
  });
  const dailiesQuery = useQuery({
    queryKey: ["news-dailies"],
    enabled: hydrated && tab === "daily",
    queryFn: () => getNewsDailies(14),
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
  // Prefer payload provider/served_from from items/daily over status-only.
  const activeProvider =
    tab === "feed"
      ? feedPages[0]?.provider ?? statusQuery.data?.provider
      : dailyQuery.data?.provider ?? statusQuery.data?.provider;
  const activeServedFrom: NewsServedFrom | undefined =
    tab === "feed" ? feedPages[0]?.served_from : dailyQuery.data?.served_from;
  const failoverActive = activeServedFrom === "failover";
  const providerLabel = formatProviderLabel(activeProvider);
  const isRefreshing =
    statusQuery.isFetching || itemsQuery.isFetching || dailyQuery.isFetching || dailiesQuery.isFetching;

  return (
    <div
      aria-busy={isRefreshing}
      className="h-full min-h-0 overflow-y-auto bg-bg-base text-text-primary"
      data-testid="ai-news-root"
    >
      <main className="mx-auto flex w-full max-w-[1240px] flex-col gap-3 px-3 py-3 sm:px-6 lg:py-4">
        <div
          className="sr-only"
          data-testid="ai-news-readonly-safety"
        >
          <ShieldCheck aria-hidden="true" className="shrink-0" size={15} />
          <span>{text.safetyCompact}</span>
        </div>

        <header className={`relative overflow-hidden rounded-lg border border-border-subtle bg-bg-surface p-3 sm:p-4 ${aiNewsHeaderWashClass}`}>
          <span
            aria-hidden="true"
            className={`absolute inset-x-0 top-0 h-0.5 ${aiNewsAccentRailClass}`}
            data-ai-news-accent-rail="true"
          />
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="font-label-caps uppercase text-text-secondary">{text.eyebrow}</p>
              <div className="mt-1.5 flex items-center justify-between gap-2">
                <Rss className="shrink-0 text-info" size={20} />
                <h1 className="min-w-0 flex-1 font-headline-xl text-text-primary">{text.title}</h1>
                <TerminalToolbarButton
                  className="border-info/40 bg-info/5 text-text-primary hover:border-info sm:hidden"
                  disabled={!hydrated || isRefreshing}
                  onClick={refreshActive}
                  title={text.refresh}
                >
                  <RefreshCw aria-hidden="true" className={isRefreshing ? "animate-spin" : ""} size={15} />
                  {text.refresh}
                </TerminalToolbarButton>
              </div>
              <p className="mt-1 max-w-3xl font-body-sm text-text-secondary sm:hidden">
                {text.safetyShort}
              </p>
              <p className="mt-1 hidden max-w-3xl font-body-sm text-text-secondary sm:block">
                {text.subtitle}
              </p>
            </div>
            <div className="hidden flex-wrap items-center gap-2 sm:flex">
              <HeaderStatusPill
                label={text.source}
                tone={
                  statusQuery.data?.enabled === false || failoverActive || !activeProvider
                    ? "warning"
                    : "info"
                }
                value={
                  statusQuery.data?.enabled === false && !activeProvider
                    ? text.unavailable
                    : providerLabel || text.unavailable
                }
              />
              {failoverActive ? (
                <HeaderStatusPill label={text.servedFrom} tone="warning" value={text.failoverActive} />
              ) : null}
              <StatusPill
                label={text.beta}
                value={
                  (feedPages[0]?.provider_beta ??
                    dailyQuery.data?.provider_beta ??
                    statusQuery.data?.provider_beta)
                    ? "ON"
                    : "--"
                }
              />
              <StatusPill label={text.fetched} value={formatDateTime(activeFetchedAt, locale) || text.none} />
              <TerminalToolbarButton
                className="border-info/40 bg-info/5 text-text-primary hover:border-info"
                disabled={!hydrated || isRefreshing}
                onClick={refreshActive}
                title={text.refresh}
              >
                <RefreshCw aria-hidden="true" className={isRefreshing ? "animate-spin" : ""} size={15} />
                {text.refresh}
              </TerminalToolbarButton>
            </div>
          </div>

          <form
            className="mt-3 border-t border-border-subtle pt-3"
            data-testid="ai-news-toolbar"
            onSubmit={(event) => event.preventDefault()}
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div
                aria-label={text.mode}
                className="flex rounded-lg border border-border-subtle bg-bg-base p-1"
              >
                {(["feed", "daily"] as const).map((item) => (
                  <button
                    aria-pressed={tab === item}
                    className={`rounded-md px-3 py-1.5 font-body-sm transition-colors ${
                      tab === item
                        ? "bg-info/10 text-text-primary shadow-[inset_0_-1px_0_rgba(87,193,255,0.55)]"
                        : "text-text-secondary hover:text-text-primary"
                    }`}
                    data-testid="ai-news-view-toggle"
                    key={item}
                    onClick={() => setTab(item)}
                    type="button"
                  >
                    {item === "feed" ? text.feed : text.daily}
                  </button>
                ))}
              </div>

              {tab === "feed" ? (
                <>
                  <button
                    aria-controls="ai-news-mobile-search"
                    aria-expanded={mobileSearchOpen || Boolean(keyword)}
                    className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-border-subtle bg-bg-base px-3 font-body-sm text-text-secondary transition-colors hover:border-info/45 hover:bg-bg-surface-muted hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info sm:hidden"
                    onClick={() => setMobileSearchOpen((value) => !value)}
                    type="button"
                  >
                    <Search aria-hidden="true" size={15} />
                    {text.keyword}
                  </button>
                  <label className="hidden min-w-[240px] flex-1 items-center gap-2 rounded-lg border border-border-subtle bg-bg-base px-3 py-2 font-body-sm text-text-secondary focus-within:border-info sm:flex sm:max-w-sm">
                    <Search aria-hidden="true" size={16} className="shrink-0" />
                    <input
                      aria-label={text.keyword}
                      data-testid="ai-news-search"
                      className="min-w-0 flex-1 bg-transparent text-text-primary outline-none"
                      onChange={(event) => setKeyword(event.target.value)}
                      placeholder={text.keywordPlaceholder}
                      value={keyword}
                    />
                  </label>
                </>
              ) : null}
            </div>

            {tab === "feed" && (mobileSearchOpen || keyword) ? (
              <label
                className="mt-2 flex items-center gap-2 rounded-lg border border-border-subtle bg-bg-base px-3 py-2 font-body-sm text-text-secondary focus-within:border-info sm:hidden"
                id="ai-news-mobile-search"
              >
                <Search aria-hidden="true" size={15} className="shrink-0" />
                <input
                  aria-label={text.keyword}
                  data-testid="ai-news-search"
                  className="min-w-0 flex-1 bg-transparent text-text-primary outline-none"
                  onChange={(event) => setKeyword(event.target.value)}
                  placeholder={text.keywordPlaceholder}
                  value={keyword}
                />
              </label>
            ) : null}

            {tab === "feed" ? (
              <div className="mt-2 flex flex-wrap items-center gap-2 pb-1 sm:flex-nowrap sm:overflow-x-auto">
                <div
                  aria-label={text.mode}
                  className="flex shrink-0 rounded-lg border border-border-subtle bg-bg-base p-1"
                  role="group"
                >
                  {(["selected", "all"] as const).map((item) => (
                    <button
                      aria-pressed={mode === item}
                      className={`rounded-md px-3 py-1.5 font-body-sm transition-colors ${
                        mode === item
                          ? "bg-info/10 text-text-primary shadow-[inset_0_-1px_0_rgba(87,193,255,0.55)]"
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

                <div
                  aria-label={text.category}
                  className="flex min-w-0 flex-wrap gap-2 sm:shrink-0 sm:flex-nowrap"
                  data-testid="ai-news-category-strip"
                  role="group"
                >
                  {categoryOptions.map((item) => (
                    <button
                      aria-pressed={category === item.value}
                      className={`shrink-0 rounded-md border px-3 py-1.5 font-body-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info ${
                        category === item.value
                          ? categoryToneClass(item.value).buttonActive
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

                <div
                  aria-label={text.window}
                  className="flex shrink-0 rounded-lg border border-border-subtle bg-bg-base p-1"
                  data-testid="ai-news-window-filter"
                  role="group"
                >
                  {(["24h", "3d", "7d"] as const).map((item) => (
                    <button
                      aria-pressed={windowKey === item}
                      className={`rounded-md px-3 py-1.5 font-data-mono transition-colors ${
                        windowKey === item
                          ? "bg-info/10 text-text-primary shadow-[inset_0_-1px_0_rgba(87,193,255,0.55)]"
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

                <label className="hidden items-center gap-2 whitespace-nowrap rounded-lg border border-border-subtle bg-bg-base px-3 py-1.5 font-label-caps uppercase text-text-secondary lg:flex">
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
        {failoverActive ? (
          <div
            aria-live="polite"
            className="rounded-lg border border-warning/35 bg-warning/5 p-3 font-body-sm text-warning"
            data-testid="ai-news-failover-banner"
          >
            {text.failoverBanner}
            {providerLabel ? ` · ${text.source}: ${providerLabel}` : null}
          </div>
        ) : null}
        <OperationalWarningStrip warnings={activeWarnings ?? []} />

        {tab === "feed" ? (
          <FeedPanel
            hasNext={Boolean(itemsQuery.hasNextPage)}
            items={feedItems}
            loading={!hydrated || (itemsQuery.isFetching && feedItems.length === 0)}
            loadingMore={itemsQuery.isFetchingNextPage}
            locale={locale}
            onLoadMore={loadMore}
            panelId="ai-news-feed-panel"
          />
        ) : (
          <DailyPanel
            archive={dailiesQuery.data?.items ?? []}
            daily={dailyQuery.data}
            dailyDate={dailyDate}
            loading={!hydrated || dailyQuery.isFetching}
            locale={locale}
            onDailyDateChange={setDailyDate}
            panelId="ai-news-daily-panel"
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
  panelId,
}: {
  hasNext: boolean;
  items: AiHotItem[];
  loading: boolean;
  loadingMore: boolean;
  locale: Locale;
  onLoadMore: () => void;
  panelId: string;
}) {
  const text = copy[locale];
  const groups = groupFeedItems(items, locale, text.unknownDate);

  return (
    <section
      className="mt-2"
      data-testid="ai-news-feed"
      id={panelId}
    >
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <h2 className="font-label-caps text-text-primary">{text.feedTitle}</h2>
          <span className="hidden font-body-sm text-text-secondary sm:inline">{text.feedHint}</span>
        </div>
        <span className="shrink-0 font-data-mono text-[10px] uppercase text-text-secondary">
          {text.feedCount} {items.length}
        </span>
      </div>
      {loading ? <LoadingRows /> : null}
      {!loading && items.length === 0 ? <EmptyState label={text.emptyFeed} /> : null}
      <div className="grid gap-3">
        {groups.map((group) => (
          <div className="grid gap-2" key={group.label}>
            <div className="flex items-center gap-2">
              <span className="font-data-mono text-xs font-semibold uppercase text-text-primary">{group.label}</span>
              <span className="h-px flex-1 bg-border-subtle" />
            </div>
            <FeedCardList items={group.items} locale={locale} />
            <FeedTable items={group.items} locale={locale} />
          </div>
        ))}
      </div>
      {!loading && hasNext ? (
        <div className="mt-4 flex justify-center">
          <TerminalToolbarButton disabled={loadingMore} onClick={onLoadMore}>
            {loadingMore ? text.loadingMore : text.loadMore}
          </TerminalToolbarButton>
        </div>
      ) : null}
    </section>
  );
}

function FeedCardList({ items, locale }: { items: AiHotItem[]; locale: Locale }) {
  return (
    <div className="grid gap-2 lg:hidden" data-ai-news-card-list="true">
      {items.map((item, index) => (
        <FeedCard isFirst={index === 0} item={item} key={item.id} locale={locale} />
      ))}
    </div>
  );
}

function FeedCard({
  isFirst = false,
  item,
  locale,
}: {
  isFirst?: boolean;
  item: AiHotItem;
  locale: Locale;
}) {
  const text = copy[locale];
  const time = formatTime(item.published_at, locale);
  const summary = item.summary || item.title_en || "";
  const safeUrl = safeExternalUrl(item.url);
  const tone = categoryToneClass(item.category);

  return (
    <article
      className="relative overflow-hidden rounded-lg border border-border-subtle bg-bg-surface p-3 pl-8 transition-colors hover:bg-bg-surface-muted/45"
      data-ai-news-card="true"
      data-ai-news-first-item={isFirst ? "true" : undefined}
      data-category={item.category ?? ""}
      data-has-score={typeof item.score === "number" ? "true" : "false"}
      data-item-id={item.id}
      data-selected={item.selected ? "true" : "false"}
      data-testid="ai-news-item"
    >
      <span
        aria-hidden="true"
        className={`absolute left-3 top-5 h-2.5 w-2.5 rounded-full ${tone.dot}`}
        data-ai-news-timeline-dot="true"
      />
      <span
        aria-hidden="true"
        className="absolute bottom-4 left-[16px] top-9 w-px bg-border-subtle/80"
      />
      <div className="flex flex-wrap items-center gap-2 font-data-mono text-[11px] text-text-secondary">
        <span>{time || text.unknownDate}</span>
        <span className="h-1 w-1 rounded-full bg-border-subtle" />
        <span className="min-w-0 truncate">{item.source}</span>
        {item.category ? <CategoryBadge category={item.category} locale={locale} /> : null}
      </div>
      {safeUrl ? (
        <a
          className="mt-2 block font-body-sm font-semibold leading-5 text-text-primary transition-colors hover:text-info focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
          aria-label={`${text.openOriginal}: ${item.title} (${text.newTab})`}
          href={safeUrl}
          rel="noreferrer noopener"
          target="_blank"
        >
          {item.title}
        </a>
      ) : (
        <div className="mt-2 block font-body-sm font-semibold leading-5 text-text-primary">
          {item.title}
        </div>
      )}
      {summary ? <p className="mt-1 line-clamp-2 font-body-sm text-text-secondary">{summary}</p> : null}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <FeedBadges item={item} locale={locale} />
        {safeUrl ? (
          <a
            className="inline-flex min-h-8 items-center gap-1 rounded-lg border border-border-subtle px-2 py-1 font-body-sm text-text-primary transition-colors hover:border-info hover:text-info focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
            aria-label={`${text.openOriginal}: ${item.title} (${text.newTab})`}
            data-testid="ai-news-original-link"
            href={safeUrl}
            rel="noreferrer noopener"
            target="_blank"
          >
            <ExternalLink aria-hidden="true" size={13} />
            {text.openOriginal}
          </a>
        ) : null}
      </div>
    </article>
  );
}

function FeedTable({ items, locale }: { items: AiHotItem[]; locale: Locale }) {
  const text = copy[locale];

  return (
    <div className="hidden lg:block" data-testid="ai-news-feed-table">
      <TerminalTable
        columns={[
          { label: text.time, className: "w-[92px]" },
          { label: text.source, className: "w-[128px]" },
          { label: text.headline },
          { label: text.categoryColumn, className: "w-[132px]" },
          { label: text.signalColumn, align: "right", className: "w-[132px]" },
          { label: text.action, align: "right", className: "w-[116px]" },
        ]}
        minWidth="980px"
      >
        {items.map((item) => (
          <TimelineArticle item={item} key={item.id} locale={locale} />
        ))}
      </TerminalTable>
    </div>
  );
}

function TimelineArticle({ item, locale }: { item: AiHotItem; locale: Locale }) {
  const text = copy[locale];
  const time = formatTime(item.published_at, locale);
  const summary = item.summary || item.title_en || "";
  const safeUrl = safeExternalUrl(item.url);
  const tone = categoryToneClass(item.category);

  return (
    <tr className="border-b border-border-subtle/80 align-top transition-colors last:border-b-0 hover:bg-bg-surface-muted/45">
      <td className="whitespace-nowrap px-3 py-3 font-data-mono text-xs text-text-secondary">
        <span className="inline-flex items-center gap-2">
          <span
            aria-hidden="true"
            className={`h-2 w-2 rounded-full ${tone.dot}`}
            data-ai-news-timeline-dot="true"
          />
          <span>{time || text.unknownDate}</span>
        </span>
      </td>
      <td className="max-w-[140px] px-3 py-3 text-xs text-text-secondary">
        <span className="block truncate">{item.source}</span>
      </td>
      <td className="px-3 py-3">
        {safeUrl ? (
          <a
            className="block font-body-sm font-semibold leading-5 text-text-primary transition-colors hover:text-info focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
            aria-label={`${text.openOriginal}: ${item.title} (${text.newTab})`}
            href={safeUrl}
            rel="noreferrer noopener"
            target="_blank"
          >
            {item.title}
          </a>
        ) : (
          <div className="block font-body-sm font-semibold leading-5 text-text-primary">
            {item.title}
          </div>
        )}
        {summary ? (
          <p className="mt-1 line-clamp-2 font-body-sm text-text-secondary">{summary}</p>
        ) : null}
      </td>
      <td className="px-3 py-3">
        {item.category ? (
          <CategoryBadge category={item.category} locale={locale} />
        ) : (
          <span className="text-text-secondary">--</span>
        )}
      </td>
      <td className="px-3 py-3 text-right">
        <FeedBadges item={item} locale={locale} align="end" />
      </td>
      <td className="px-3 py-3 text-right">
        {safeUrl ? (
          <a
            className="inline-flex items-center justify-end gap-1 rounded-lg border border-border-subtle px-2 py-1 font-body-sm text-text-primary transition-colors hover:border-info hover:text-info focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
            aria-label={`${text.openOriginal}: ${item.title} (${text.newTab})`}
            data-testid="ai-news-original-link"
            href={safeUrl}
            rel="noreferrer noopener"
            target="_blank"
          >
            <ExternalLink aria-hidden="true" size={13} />
            {text.openOriginal}
          </a>
        ) : (
          <span className="text-text-secondary">{text.none}</span>
        )}
      </td>
    </tr>
  );
}

function FeedBadges({
  align = "start",
  item,
  locale,
}: {
  align?: "start" | "end";
  item: AiHotItem;
  locale: Locale;
}) {
  const text = copy[locale];
  const hasScore = typeof item.score === "number";

  if (!item.selected && !hasScore) {
    return <span className="text-text-secondary">--</span>;
  }

  return (
    <div className={`flex flex-wrap gap-1.5 ${align === "end" ? "justify-end" : ""}`}>
      {item.selected ? (
        <NewsBadge className="border-[#f0b90b]/45 bg-[#f0b90b]/10 text-text-primary">
          {text.selectedBadge}
        </NewsBadge>
      ) : null}
      {hasScore ? (
        <NewsBadge className={scoreToneClass(item.score as number)}>
          {text.score} {scoreLabel(item.score as number)}
        </NewsBadge>
      ) : null}
    </div>
  );
}

function CategoryBadge({ category, locale }: { category: string; locale: Locale }) {
  const tone = categoryToneClass(category);
  return (
    <span
      className={`inline-flex max-w-full items-center gap-1.5 rounded-md border px-2 py-1 font-data-mono text-[10px] uppercase leading-none ${tone.badge}`}
      data-ai-news-category-tone={tone.name}
      data-testid="ai-news-category-badge"
      title={categoryName(category, locale)}
    >
      <span
        aria-hidden="true"
        className={`h-1.5 w-1.5 shrink-0 rounded-full ${tone.dot}`}
        data-ai-news-timeline-dot="true"
      />
      <span className="truncate">{categoryName(category, locale)}</span>
    </span>
  );
}

function NewsBadge({
  children,
  className,
}: {
  children: ReactNode;
  className: string;
}) {
  return (
    <span
      className={`inline-flex max-w-full items-center rounded-md border px-2 py-1 font-data-mono text-[10px] uppercase leading-none ${className}`}
    >
      <span className="truncate">{children}</span>
    </span>
  );
}

function HeaderStatusPill({
  label,
  tone,
  value,
}: {
  label: string;
  tone: "info" | "warning";
  value: ReactNode;
}) {
  const toneClass =
    tone === "warning"
      ? "border-[#f0b90b]/45 bg-[#f0b90b]/10"
      : "border-[#57c1ff]/45 bg-[#57c1ff]/10";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 font-data-mono text-[10px] uppercase text-text-primary ${toneClass}`}
    >
      <span className="text-text-secondary">{label}</span>
      <span className="font-bold">{value}</span>
    </span>
  );
}

function formatProviderLabel(provider?: string | null): string {
  if (!provider) {
    return "";
  }
  const normalized = provider.trim().toLowerCase();
  if (normalized === "aihot" || normalized === "ai-hot" || normalized === "ai_hot") {
    return "AI HOT";
  }
  if (normalized === "horizon") {
    return "Horizon";
  }
  return provider;
}

function categoryToneClass(value: string | null | undefined) {
  return categoryToneClasses[value || "default"] ?? categoryToneClasses.default;
}

function scoreToneClass(value: number) {
  if (value >= 80) {
    return "border-[#f0b90b]/45 bg-[#f0b90b]/10 text-text-primary";
  }
  if (value >= 70) {
    return "border-[#57c1ff]/45 bg-[#57c1ff]/10 text-text-primary";
  }
  return "border-border-subtle bg-bg-surface-muted text-text-primary";
}

function DailyPanel({
  archive,
  daily,
  dailyDate,
  loading,
  locale,
  onDailyDateChange,
  panelId,
}: {
  archive: AiHotDailyIndex[];
  daily?: AiHotDailyResponse;
  dailyDate: string;
  loading: boolean;
  locale: Locale;
  onDailyDateChange: (value: string) => void;
  panelId: string;
}) {
  const text = copy[locale];
  return (
    <section
      className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_280px]"
      id={panelId}
    >
      <div>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <SectionTitle title={text.dailyTitle} hint={text.dailyHint} />
          <div className="flex items-center gap-2 font-body-sm text-text-secondary">
            <label htmlFor="ai-news-daily-date">{text.dailyDate}</label>
            <input
              className={`${inputClass} font-data-mono`}
              id="ai-news-daily-date"
              onChange={(event) => onDailyDateChange(event.target.value)}
              type="date"
              value={dailyDate}
            />
            <button
              aria-label={text.latestDaily}
              aria-pressed={dailyDate === ""}
              className="rounded-lg border border-border-subtle px-3 py-2 text-text-primary hover:border-info hover:text-info"
              onClick={() => onDailyDateChange("")}
              type="button"
            >
              {text.latestDaily}
            </button>
          </div>
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
            aria-label={`${text.openOriginal}: ${recordText(item, "title")} (${text.newTab})`}
            href={safeSourceUrl}
            rel="noreferrer noopener"
            target="_blank"
          >
            <ExternalLink aria-hidden="true" size={14} />
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
    <div
      className="mt-4 rounded-lg border border-danger/40 bg-danger/5 p-3 font-body-sm text-danger"
      role="alert"
    >
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
    <div
      aria-live="polite"
      className="mt-4 rounded-lg border border-warning/35 bg-warning/5 p-3 font-body-sm text-warning"
    >
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
