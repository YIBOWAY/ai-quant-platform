"use client";

/**
 * Hermes today = the three-ledger blotter, wired to the remote book
 * plus the existing research/result surfaces passed in as slots.
 */

import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import type { HungSleeveEffectResponse } from "@/lib/api";
import { apiRequest, apiRequestOnce, ApiClientError } from "@/lib/apiClient";
import { localizePath } from "@/lib/locale";
import { candidatePresentation } from "@/lib/hermes/candidatePresentation";
import { HermesDeskChatRail } from "./HermesDeskChatRail";
import { useHermesDesk } from "./HermesDeskContext";
import { DutyMarketTape } from "./DutyMarketTape";

export type DeskLedger = "duty" | "research" | "paper";

const YESTERDAY_ABSENT_LABEL = {
  en: "Yesterday's observation: absent (not run)",
  zh: "昨日观察：缺席（未运行）",
} as const;

type RemoteCandidate = {
  candidate_id: string;
  objective?: string;
  status?: string;
  sleeve_id?: string | null;
  source_digest?: string | null;
  factor_id?: string;
  universe?: string[];
  display_name?: string;
  display_name_zh?: string;
  summary_zh?: string;
  fossil?: boolean;
  official_observation?: boolean;
};

type RemoteRequest = {
  request_id: string;
  objective?: string;
  status?: string;
  job_key?: string | null;
  mode?: string;
};

const EMPTY_EFFECT_LABEL = {
  en: "1 simulated strategy · 0 observation days · Waiting for the first observation night",
  zh: "1 条模拟运行中 · 观察日 0 · 等第一个观察夜",
} as const;

type ObservationCalendar = {
  yesterday: {
    date: string;
    status: "absent" | "recorded" | "pending" | "not_scheduled" | string;
    label_zh: string;
    counts_as_observation_day: boolean;
    is_no_signal: boolean;
    reason?: string | null;
  };
  observation_day_count: number;
};

type RemoteBook = {
  candidates?: RemoteCandidate[];
  requests?: RemoteRequest[];
  verified_count?: number;
  hung_count?: number;
  fossil_count?: number;
};

function errorText(error: unknown, isZh: boolean): string {
  if (error instanceof ApiClientError) return error.message;
  if (error instanceof Error) return error.message;
  return isZh ? "请求失败" : "Request failed";
}

function researchRequestStatusLabel(item: RemoteRequest, isZh: boolean) {
  if (!isZh) return item.status || "requested";
  if (item.mode === "book_only" && !item.job_key) return "未入队";
  const labels: Record<string, string> = {
    requested: "已记录",
    pending: "等待处理",
    queued: "排队中",
    leased: "已领取",
    running: "运行中",
    candidate_ready: "已完成",
    failed: "失败",
    outcome_unknown: "结果待确认",
  };
  return labels[item.status || "requested"] ?? "状态待确认";
}

function researchRequestIsQueued(item: RemoteRequest) {
  if (item.mode === "book_only" && !item.job_key) return false;
  return ["requested", "pending", "queued", "leased", "running"].includes(
    item.status || "requested",
  );
}

function researchRequestSummary(item: RemoteRequest, isZh: boolean) {
  if (!isZh) {
    if (item.status === "outcome_unknown") {
      return "Research outcome could not be confirmed; it is not still running.";
    }
    return item.objective || "Research request recorded.";
  }
  const status = researchRequestStatusLabel(item, true);
  if (item.mode === "book_only" && !item.job_key) {
    return `研究请求已记录，尚未入队。当前状态：${status}。`;
  }
  if (item.status === "outcome_unknown") {
    return `研究结果未能确认，不是仍在执行。当前状态：${status}。`;
  }
  if (item.status === "failed") {
    return `研究失败。当前状态：${status}。`;
  }
  if (item.status === "candidate_ready") {
    return `研究已完成。当前状态：${status}。`;
  }
  if (researchRequestIsQueued(item)) {
    return `研究请求已入队，完成后会回到本对话。当前状态：${status}。`;
  }
  return `当前状态：${status}。`;
}

function researchRequestActionLabel(item: RemoteRequest, isZh: boolean) {
  if (item.mode === "book_only" && !item.job_key) {
    return isZh ? "只入本地账、未入队" : "Recorded locally, not queued";
  }
  if (item.status === "outcome_unknown") {
    return isZh ? "待确认" : "Unconfirmed";
  }
  if (item.status === "failed") {
    return isZh ? "失败" : "Failed";
  }
  if (item.status === "candidate_ready") {
    return isZh ? "已完成" : "Completed";
  }
  if (researchRequestIsQueued(item)) {
    return isZh ? "已入队研究" : "Research queued";
  }
  return isZh ? "待确认" : "Unconfirmed";
}

function CandidateTechnicalDetails({
  item,
  isZh,
}: {
  item: RemoteCandidate;
  isZh: boolean;
}) {
  const rows = [
    [isZh ? "候选编号" : "Candidate ID", item.candidate_id],
    [isZh ? "因子编号" : "Factor ID", item.factor_id],
    [isZh ? "来源校验指纹" : "Source fingerprint", item.source_digest],
    [isZh ? "策略仓编号" : "Strategy sleeve ID", item.sleeve_id],
    [isZh ? "原始研究目标" : "Research objective", item.objective],
  ].filter((row): row is [string, string] => typeof row[1] === "string" && row[1].length > 0);
  if (!rows.length) return null;
  return (
    <details className="mt-2 font-body-sm text-text-secondary">
      <summary className="app-touch-target cursor-pointer select-none">{isZh ? "技术信息" : "Technical details"}</summary>
      <dl className="mt-1 space-y-1">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt className="inline">{label}：</dt>
            <dd className="inline break-all font-data-mono text-[10px]">{value}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

export function HermesDeskToday(props: {
  dutyExtra?: ReactNode;
}) {
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  );
  return (
    <QueryClientProvider client={queryClient}>
      <HermesDeskTodayBody {...props} />
    </QueryClientProvider>
  );
}

function HermesDeskTodayBody({
  dutyExtra,
}: {
  dutyExtra?: ReactNode;
}) {
  const { ledger, locale, isMobile, chatRailOpen } = useHermesDesk();
  const isZh = locale === "zh";
  const mobileDrawerOpen = isMobile && chatRailOpen;
  const yesterdayAbsentLabel = YESTERDAY_ABSENT_LABEL[locale];
  const yesterdayUnavailableLabel = isZh
    ? "昨日观察：已运行，但信号数据不可用"
    : "Yesterday's observation: ran, but signal data was unavailable";

  const bookQuery = useQuery({
    queryKey: ["assistant-remote-book"],
    queryFn: () => apiRequestOnce<RemoteBook>("/api/assistant/remote/book"),
    refetchInterval: 15_000,
    retry: false,
  });
  const calendarQuery = useQuery({
    queryKey: ["observation-calendar"],
    queryFn: () =>
      apiRequest<ObservationCalendar>("/api/paper/strategy-sleeves/observation-calendar"),
    refetchInterval: 15_000,
    enabled: ledger === "duty",
  });
  const effectQuery = useQuery({
    queryKey: ["hung-sleeve-effect"],
    queryFn: () =>
      apiRequest<HungSleeveEffectResponse>("/api/paper/strategy-sleeves/hung-effect"),
    refetchInterval: 15_000,
    enabled: ledger === "paper",
  });
  const book = bookQuery.data;
  const bookReady = Boolean(book && !bookQuery.isError && !bookQuery.isPending);
  const candidates = book?.candidates ?? [];
  const official = candidates.filter(
    (item) => item.fossil !== true && item.official_observation !== false,
  );
  const verified = official.filter((item) => item.status === "verified");
  const hung = official.filter((item) => item.status === "hung");
  const fossils = candidates.filter(
    (item) => item.fossil === true || item.official_observation === false,
  );
  const requests = book?.requests ?? [];

  const hero = useMemo(() => {
    if (bookQuery.isError)
      return isZh
        ? "暂时无法读取研究与模拟状态。"
        : "Research and simulation status is unavailable.";
    if (bookQuery.isPending) return isZh ? "正在读取研究与模拟状态…" : "Loading research and simulation status…";
    if (verified.length > 0)
      return isZh
        ? `${verified.length} 条已验证候选可查看准入结果。`
        : `${verified.length} verified candidate${verified.length === 1 ? "" : "s"} ready for review.`;
    if (hung.length > 0)
      return isZh
        ? `有 ${hung.length} 条模拟运行中。还没有新的已验证候选。`
        : `${hung.length} running in simulation. No new verified candidates yet.`;
    return isZh
      ? "发起一次研究，结果与模拟进度会出现在这里。"
      : "Start a research task to see its results and simulation progress here.";
  }, [bookQuery.isError, bookQuery.isPending, hung.length, isZh, verified.length]);

  return (
    <>
      <div
        aria-labelledby={`hermes-ledger-tab-${ledger}`}
        aria-hidden={mobileDrawerOpen ? true : undefined}
        className="dp-main dp-scroll"
        id="hermes-ledger-panel"
        inert={mobileDrawerOpen ? true : undefined}
        role="tabpanel"
        style={{ minWidth: 0 }}
        tabIndex={0}
      >
        <section className="dp-hero">
          <h2 className="dp-hero-title">{isZh ? "研究与运行" : "Research & simulation"}</h2>
          <p className="dp-hero-description" role="status">{hero}</p>
          <div className="dp-hero-sub">
            <span>
              {isZh ? "已验证候选" : "Verified candidates"}{" "}
              <span className="dp-num">{bookReady ? book?.verified_count ?? "—" : "—"}</span>
            </span>
            <span>
              {isZh ? "模拟运行中" : "Running in simulation"}{" "}
              <span className="dp-num">{bookReady ? book?.hung_count ?? "—" : "—"}</span>
            </span>
            {bookQuery.isFetching ? (
              <span>{isZh ? "对账中…" : "Reconciling…"}</span>
            ) : null}
            {bookQuery.isError ? (
              <span>
                {isZh ? "账本错误：" : "Book error: "}
                {errorText(bookQuery.error, isZh)}
              </span>
            ) : null}
          </div>
        </section>

         {ledger === "duty" && calendarQuery.data?.yesterday.status === "absent" ? (
           <p className="dp-hero-sub" data-observation-yesterday="absent">
             {isZh
               ? calendarQuery.data.yesterday.label_zh || yesterdayAbsentLabel
               : yesterdayAbsentLabel}
           </p>
         ) : null}
         {ledger === "duty" &&
         calendarQuery.data?.yesterday.status === "data_unavailable" ? (
           <p
             className="dp-hero-sub"
             data-observation-yesterday="data_unavailable"
           >
             {isZh
               ? calendarQuery.data.yesterday.label_zh || yesterdayUnavailableLabel
               : yesterdayUnavailableLabel}
           </p>
         ) : null}

        {ledger === "duty" ? <details className="dp-diagnostics"><summary>{isZh ? "市场参照 · SPY / QQQ / SOXX" : "Market context · SPY / QQQ / SOXX"}</summary><DutyMarketTape /></details> : null}

        <div className="dp-sechead">
          <h2>
            {ledger === "duty"
              ? isZh
                ? "策略状态"
                : "Strategy status"
              : ledger === "research"
                ? isZh
                  ? "研究账"
                  : "Research book"
                : isZh
                  ? "模拟账"
                  : "Paper book"}
          </h2>
          <span className="count dp-num">
            {!bookReady ? (isZh ? "记录未知" : "Records unknown") : ledger === "research"
              ? isZh
                ? `请求 ${requests.length} · 候选 ${verified.length}`
                : `Requests ${requests.length} · Candidates ${verified.length}`
              : ledger === "paper"
                ? isZh
                  ? `模拟运行中 ${hung.length}`
                  : `Running in simulation ${hung.length}`
                : isZh
                  ? `模拟运行中 ${hung.length} · 候选 ${verified.length}`
                  : `Running in simulation ${hung.length} · Candidates ${verified.length}`}
          </span>
        </div>

        <div className="dp-blotter" data-ledger={ledger} data-book-read-status={bookReady ? "available" : bookQuery.isError ? "unavailable" : "loading"}>
          <table>
            <thead>
              <tr>
                <th style={{ width: 96 }}>{isZh ? "状态" : "Status"}</th>
                <th>{isZh ? "策略 / 因子" : "Strategy / factor"}</th>
                <th style={{ minWidth: 240 }}>{isZh ? "说明" : "Description"}</th>
                <th>{isZh ? "标的范围" : "Symbols"}</th>
                <th>{isZh ? "动作" : "Actions"}</th>
              </tr>
            </thead>
            <tbody>
              {!bookReady ? <tr className="dp-row"><td colSpan={5}><div className="dp-summary" role="status">{bookQuery.isError
                ? (isZh ? "策略与研究记录暂时无法读取，不能判断是否有正在运行的策略或研究。" : "Strategy and research records are unavailable. Active work cannot be determined.")
                : (isZh ? "正在读取策略与研究记录…" : "Loading strategy and research records…")}</div></td></tr> : null}
              {bookReady && ledger !== "research"
                ? (ledger === "paper" ? hung : [...hung, ...verified]).map((item) => {
                    const presentation = candidatePresentation(item, locale);
                    return (
                    <tr className="dp-row" key={item.candidate_id}>
                      <td>
                        <span
                          className="dp-status"
                          data-kind={item.status === "hung" ? "hung" : "candidate"}
                        >
                          {item.status === "hung"
                            ? isZh
                              ? "模拟运行中"
                              : "Running in simulation"
                            : isZh
                              ? "尚未启用"
                              : "Not enabled"}
                        </span>
                      </td>
                      <td>
                        <div className="dp-strat-name">{presentation.name}</div>
                        <CandidateTechnicalDetails isZh={isZh} item={item} />
                      </td>
                      <td className="wrap">
                        <div className="dp-summary">{presentation.summary}</div>
                      </td>
                      <td>{(item.universe ?? []).join(" · ") || "—"}</td>
                      <td>
                        {item.status === "verified" ? (
                          <Link
                            className="dp-hangbtn app-touch-target"
                            href={localizePath("/library", locale)}
                          >
                            {isZh ? "去候选库" : "Open candidate library"}
                          </Link>
                        ) : (
                          <span className="dp-strat-sub">{isZh ? "模拟运行中" : "Simulation active"}</span>
                        )}
                      </td>
                    </tr>
                    );
                  })
                : null}
              {bookReady && ledger === "research"
                ? requests.map((item) => (
                    <tr className="dp-row" key={item.request_id}>
                      <td>
                         <span className="dp-status" data-kind="paused">
                            {researchRequestStatusLabel(item, isZh)}
                        </span>
                      </td>
                      <td>
                        <div className="dp-strat-name">{isZh ? "研究请求" : "Research request"}</div>
                        <details className="mt-1 font-body-sm text-text-secondary">
                          <summary className="app-touch-target cursor-pointer select-none">{isZh ? "技术信息" : "Technical details"}</summary>
                          <div className="break-all font-data-mono text-[10px]">{item.request_id}</div>
                           <div className="break-all font-data-mono text-[10px]">{item.mode || "book_only"}</div>
                           {item.job_key ? <div className="break-all font-data-mono text-[10px]">{item.job_key}</div> : null}
                           {item.objective ? <div className="break-all font-data-mono text-[10px]">{item.objective}</div> : null}
                        </details>
                      </td>
                      <td className="wrap">
                         <div className="dp-summary">{researchRequestSummary(item, isZh)}</div>
                      </td>
                       <td className="dp-strat-sub">—</td>
                       <td className="dp-strat-sub">
                         {researchRequestActionLabel(item, isZh)}
                       </td>
                    </tr>
                  ))
                : null}
              {bookReady && ledger === "research"
                ? verified.map((item) => {
                    const presentation = candidatePresentation(item, locale);
                    return (
                    <tr className="dp-row" key={item.candidate_id}>
                      <td>
                        <span className="dp-status" data-kind="candidate">
                          {isZh ? "已验证候选" : "Verified candidate"}
                        </span>
                      </td>
                      <td>
                        <div className="dp-strat-name">{presentation.name}</div>
                        <CandidateTechnicalDetails isZh={isZh} item={item} />
                      </td>
                      <td className="wrap">
                        <div className="dp-summary">{presentation.summary}</div>
                      </td>
                      <td>{(item.universe ?? []).join(" · ")}</td>
                      <td>
                        <Link
                          className="dp-hangbtn app-touch-target"
                          href={localizePath("/library", locale)}
                        >
                          {isZh ? "去候选库" : "Open candidate library"}
                        </Link>
                      </td>
                    </tr>
                    );
                  })
                : null}
              {bookReady && ledger === "paper" && fossils.length > 0
                ? fossils.map((item) => (
                    <tr className="dp-row" data-dim="true" key={`fossil-${item.candidate_id}`}>
                      <td>
                        <span className="dp-status" data-kind="paused">
                          {isZh ? "化石" : "Fossil"}
                        </span>
                      </td>
                      <td>
                        <div className="dp-strat-name">{isZh ? "历史测试仓" : "Historical test sleeve"}</div>
                        <CandidateTechnicalDetails isZh={isZh} item={item} />
                      </td>
                      <td className="wrap">
                        <div className="dp-summary">
                          {isZh
                            ? "历史测试仓，不计入策略效果。"
                            : item.objective || "Preview seed sleeve, not a daily observation"}
                        </div>
                      </td>
                      <td>—</td>
                      <td className="dp-strat-sub">
                        {isZh ? "不计入 P&L" : "Excluded from P&L"}
                      </td>
                    </tr>
                  ))
                : null}
              {bookReady && ((ledger === "duty" && hung.length + verified.length === 0) ||
              (ledger === "research" && requests.length + verified.length === 0) ||
              (ledger === "paper" && hung.length + fossils.length === 0)) ? (
                <tr className="dp-row" key="ledger-empty">
                  <td colSpan={5}>
                    <div className="dp-summary">
                      {isZh
                        ? "还没有研究记录。可以在对话中发送策略或论文。"
                        : "No research yet. Send a strategy or paper in the conversation."}
                    </div>
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        {ledger === "paper" ? (
          <section className="dp-embed" data-hung-effect>
            <h2>{isZh ? "模拟策略效果" : "Simulated strategy performance"}</h2>
            {effectQuery.isError ? (
              <p data-hung-effect-unavailable="true">
                {isZh ? "效果暂不可用：" : "Performance unavailable: "}
                {errorText(effectQuery.error, isZh)}
              </p>
            ) : effectQuery.data?.empty !== false ? (
              <p data-hung-effect-empty="true">
                {isZh
                  ? effectQuery.data?.empty_label_zh || EMPTY_EFFECT_LABEL.zh
                  : EMPTY_EFFECT_LABEL.en}
              </p>
            ) : (
              <ul data-hung-effect-empty="false">
                <li>
                  {isZh ? "真实成交日" : "Days with fills"}{" "}
                  {effectQuery.data.observation_day_count}
                </li>
                <li>
                  {isZh ? "估值截至" : "Valuation as of"}{" "}
                  {effectQuery.data.as_of || "—"}
                  {isZh ? " · 覆盖 " : " · Covers "}
                  {effectQuery.data.covered_sleeve_count ?? "—"}/{effectQuery.data.hung_count}
                  {isZh ? " 条策略；不是实时资产" : " strategies; not live equity"}
                </li>
                {effectQuery.data.missing_valuation_dates?.length ? <li>
                  {isZh ? "缺价估值日" : "Missing valuation dates"}{" "}
                  {effectQuery.data.missing_valuation_dates.join("、")}
                </li> : null}
                <li>
                  {isZh ? "策略净值" : "Strategy NAV"}{" "}
                  {effectQuery.data.sleeve_equity_status !== "available" ||
                  effectQuery.data.sleeve_equity == null
                    ? isZh
                      ? `不可用（${effectQuery.data.sleeve_equity_reason || "缺价格"}）`
                      : "Unavailable (missing price)"
                    : effectQuery.data.sleeve_equity.toLocaleString("en-US", {
                        style: "currency",
                        currency: "USD",
                      })}
                </li>
                <li>
                  {effectQuery.data.return_method === "net_profit_over_allocated_capital"
                    ? isZh ? "累计盈亏 / 累计投入" : "Profit / allocated capital"
                    : isZh ? "首个成交收盘起算收益" : "Return since first fill close"}{" "}
                  {effectQuery.data.sleeve_equity_status !== "available" ||
                  effectQuery.data.sleeve_return_pct == null
                    ? isZh
                      ? "不可用"
                      : "Unavailable"
                    : `${effectQuery.data.sleeve_return_pct.toFixed(2)}%`}
                </li>
                <li>
                  {isZh ? "累计投入 / 累计盈亏（美元）" : "Allocated capital / profit (USD)"}{" "}
                  {effectQuery.data.allocated_cash?.toLocaleString("en-US", { maximumFractionDigits: 2 }) ?? "—"}
                  {" / "}
                  {effectQuery.data.net_profit_usd?.toLocaleString("en-US", { maximumFractionDigits: 2 }) ?? "—"}
                  {isZh ? "；不是时间加权收益" : "; not time-weighted return"}
                </li>
                <li>
                  SPY{" "}
                  {effectQuery.data.spy_status !== "available" ||
                  effectQuery.data.spy_return_pct == null
                    ? isZh
                      ? `不可用（${effectQuery.data.spy_reason || "缺价格"}）`
                      : "Unavailable (missing price)"
                    : `${effectQuery.data.spy_return_pct.toFixed(2)}%`}
                </li>
                <li>
                  {isZh ? "换手" : "Turnover"}{" "}
                  {effectQuery.data.turnover == null
                    ? "—"
                    : effectQuery.data.turnover.toFixed(2)}
                </li>
                <li>
                  {isZh ? "成本拖累" : "Cost drag"}{" "}
                  {effectQuery.data.cost_drag_pct == null
                    ? "—"
                    : `${effectQuery.data.cost_drag_pct.toFixed(4)}%`}
                </li>
                <li>
                  {isZh ? "价格源" : "Price source"}{" "}
                  {effectQuery.data.price_source || (isZh ? "不可用" : "Unavailable")}
                </li>
              </ul>
            )}
          </section>
        ) : null}

        {ledger === "duty" && dutyExtra ? (
          <div className="mt-10 space-y-8 border-t border-[var(--dp-border)] pt-8">
            {dutyExtra}
          </div>
        ) : null}
      </div>

      <HermesDeskChatRail />

    </>
  );
}
