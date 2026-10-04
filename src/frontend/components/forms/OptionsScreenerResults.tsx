'use client';

import { Fragment, useState } from "react";
import type { OptionsScreenerCandidate, OptionsScreenerResult } from "@/lib/api";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { InfoTip } from "@/components/InfoTip";
import { MetricStat } from "@/components/ui/primitives";
import { formatSellerScoreLine } from "@/lib/sellerScoreDisplay";

const resultHeaderClass = "whitespace-nowrap px-3 py-2 font-label-caps text-text-secondary";
const resultCellClass = "whitespace-nowrap px-3 py-2";
// The contract column stays visible while the table scrolls horizontally.
const stickyCellClass = "sticky left-0 z-10 bg-bg-surface";

const copy = {
  en: {
    assumptions: "Assumptions",
    avoid: "Avoid",
    candidates: "Candidates",
    colAnnualized: "Premium APR",
    colContract: "Contract",
    colDelta: "Delta",
    colDetails: "",
    colEvents: "Events",
    colExpiry: "Expiry · DTE",
    colIvr: "IVR",
    colMid: "Mid",
    colOi: "OI",
    colReasons: "Reasons",
    colScore: "Score",
    colSpread: "Spread",
    colStrike: "Strike",
    collapse: "Collapse",
    detailBreakeven: "Breakeven",
    detailDte21: "21 DTE",
    detailEvShare: "EV / share",
    detailExcessEv: "Excess EV annualized",
    detailExDividend: "Ex-dividend",
    detailExtrinsic: "Extrinsic",
    detailLiquidity: "Liquidity ×",
    detailOtm: "OTM distance",
    detailPop: "POP≈",
    detailTp50: "50% TP",
    details: "Details",
    earnings: "Earnings",
    earningsUnknown: "Earnings n/a",
    exDividend: "Ex-div",
    exDividendUnknown: "Ex-div n/a",
    filteredOut: "Not selected",
    filteredOutHelp:
      "Scanned contracts that did not satisfy every quality, personal-filter or market-regime condition. The breakdown below distinguishes these reasons; these rows are not eligible candidates.",
    gateFailed: "score hard gate failed",
    gatePassed: "score hard gate passed",
    hvIvStatus: "HV/IV Status",
    hvIvUnavailable: "No IV data",
    inWindow: "in window",
    noEligibleBody:
      "rejected contract record(s) were returned; none passed all eligibility checks. This is not a count of approved contracts.",
    noEligibleHint: "Tick “Show rejected contracts” and re-run to inspect why each contract failed.",
    rejectedAlreadyVisible: "Rejected contracts and their exclusion reasons are shown below; no rerun is needed.",
    noEligibleTitle: "No contract meets all selected conditions",
    noNotes: "Clear",
    notApplicable: "N/A",
    ratingLabel: "Rating",
    reasonsLabel: "Reasons",
    regime: "Market regime",
    regimeElevated:
      "Elevated - market volatility is higher than usual. Short-premium margin and drawdown pressure can rise; control position size.",
    regimeNormal: "Normal - no market-regime score penalty.",
    regimePanic:
      "Panic - market volatility is high. Selling options can require more margin and absorb sharper drawdowns; reduce size or wait.",
    regimeUnknown: "Unknown - run `quant-system options refresh-vix` then re-run the screener.",
    rejectedHint:
      "Not selected because of quality, personal filters or market regime. Unavailable metrics remain blank instead of being estimated.",
    rejectedTitle: "Not selected",
    scannedExpirations: "Scanned Expirations",
    sellerScoreLabel: "Seller score",
    statusLabel: "Status",
    strong: "Strong",
    trendPassed: "Trend passed",
    trendWeak: "Trend warning",
    typeCall: "CALL",
    typePut: "PUT",
    underlying: "Underlying",
    unavailable: "Unavailable",
    watch: "Watch",
    zeroBody:
      "No contract met all current requirements. Review the reasons below: missing data, liquidity, volatility, and pricing exclusions need different responses. Reasons can overlap; their counts are not additive.",
    zeroReasons: "Main filter reasons",
    zeroTitleA: "Scanned",
    zeroTitleB: "expirations and filtered out",
    zeroTitleC: "contracts — none passed the current filters.",
  },
  zh: {
    assumptions: "假设说明",
    avoid: "避开",
    candidates: "候选合约",
    colAnnualized: "权利金年化",
    colContract: "合约",
    colDelta: "Delta",
    colDetails: "",
    colEvents: "事件",
    colExpiry: "到期 · DTE",
    colIvr: "IVR",
    colMid: "中间价",
    colOi: "未平仓",
    colReasons: "原因",
    colScore: "评分",
    colSpread: "价差",
    colStrike: "行权价",
    collapse: "收起",
    detailBreakeven: "盈亏平衡",
    detailDte21: "21 DTE 管理日",
    detailEvShare: "EV / 股",
    detailExcessEv: "超额 EV 年化",
    detailExDividend: "除息",
    detailExtrinsic: "外在价值",
    detailLiquidity: "乘法流动性",
    detailOtm: "价外距离",
    detailPop: "POP≈",
    detailTp50: "50% TP",
    details: "详情",
    earnings: "财报",
    earningsUnknown: "财报未知",
    exDividend: "除息",
    exDividendUnknown: "除息未知",
    filteredOut: "未入选",
    filteredOutHelp:
      "未同时满足基础质量、个人筛选条件或市场状态要求的合约。下方分别列出各类原因；这些行不计入合格候选。",
    gateFailed: "未通过评分硬门",
    gatePassed: "通过评分硬门",
    hvIvStatus: "HV/IV 状态",
    hvIvUnavailable: "缺少 IV 数据",
    inWindow: "窗口内",
    noEligibleBody:
      "条拒绝记录已返回，没有合约满足全部条件；这里不是通过筛选的合约数量。",
    noEligibleHint: "勾选「显示未入选合约」并重新运行，可以查看每个合约被挡下的原因。",
    rejectedAlreadyVisible: "下方已展示未入选合约与排除原因，不需要再次勾选或重新运行。",
    noEligibleTitle: "没有合约同时满足全部条件",
    noNotes: "通过",
    notApplicable: "不适用",
    ratingLabel: "评级",
    reasonsLabel: "原因",
    regime: "市场状态",
    regimeElevated: "Elevated - 市场波动偏大，卖权保证金和回撤压力可能上升，注意控制仓位。",
    regimeNormal: "Normal - 不施加市场状态扣分。",
    regimePanic: "Panic - 市场波动很大，卖权保证金和回撤压力会更高，建议降低仓位或等待。",
    regimeUnknown: "未知 - 请先运行 `quant-system options refresh-vix` 刷新 VIX 历史后再筛选。",
    rejectedHint:
      "因基础质量、个人筛选条件或市场状态未入选的合约。无法计算的指标保留空缺，不做估算。",
    rejectedTitle: "未入选合约",
    scannedExpirations: "扫描到期日",
    sellerScoreLabel: "评分明细",
    statusLabel: "状态",
    strong: "强烈",
    trendPassed: "趋势通过",
    trendWeak: "趋势提醒",
    typeCall: "看涨",
    typePut: "看跌",
    underlying: "正股价格",
    unavailable: "数据不可用",
    watch: "观察",
    zeroBody:
      "本次没有合约同时满足条件。先看下方原因：资料缺失需要补数据；流动性、波动率或收益条件未通过，表示当前不符合这套卖方标准。原因可能重叠，数量不能相加。",
    zeroReasons: "主要过滤原因",
    zeroTitleA: "已扫描",
    zeroTitleB: "个到期日、过滤掉",
    zeroTitleC: "个合约，当前过滤条件下没有合格候选。",
  },
} as const;

type ResultsText = (typeof copy)["en"] | (typeof copy)["zh"];

type Locale = "en" | "zh";

/**
 * Split the returned rows into the main candidate table and the rejected set.
 *
 * The backend hides rating="Avoid" rows unless include_rejected=true, but a
 * row can still fail the recommendation hard gate (fixed delta band, spread,
 * OI, earnings window, quote freshness) while keeping a Strong/Watch rating.
 * Such rows carry no EV/POP/breakeven metrics at all, so they must not be
 * presented as candidates. Eligible rows are sorted by recommendation score
 * (stable, so backend tie-breaks survive); rejected rows keep backend order.
 */
export function partitionScreenerCandidates(candidates: OptionsScreenerCandidate[]) {
  const eligible: OptionsScreenerCandidate[] = [];
  const rejected: OptionsScreenerCandidate[] = [];
  for (const candidate of candidates) {
    if (candidate.hard_gate_passed && candidate.rating !== "Avoid" && candidate.screen_passed !== false) {
      eligible.push(candidate);
    } else {
      rejected.push(candidate);
    }
  }
  eligible.sort(
    (a, b) =>
      (b.recommendation_score ?? Number.NEGATIVE_INFINITY)
      - (a.recommendation_score ?? Number.NEGATIVE_INFINITY),
  );
  return { eligible, rejected };
}

export function OptionsScreenerResults({
  locale,
  result,
  showRejected,
}: {
  locale: Locale;
  result: OptionsScreenerResult;
  showRejected: boolean;
}) {
  const text = copy[locale];
  const [expanded, setExpanded] = useState<string | null>(null);
  const { eligible, rejected } = partitionScreenerCandidates(result.candidates);
  const expirationCount = result.expiration_count ?? result.scanned_expirations?.length ?? 0;
  // rejected_count is the backend count of rating=Avoid rows across the whole
  // scan; those rows are only present in `candidates` when include_rejected
  // was true for this run, in which case they already sit in `rejected`.
  const filteredOut = result.scanned_contract_count !== undefined
    ? result.scanned_contract_count - (result.eligible_count ?? 0)
    : rejected.length + (showRejected ? 0 : result.rejected_count);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <DataSourceBadge source={result.provider} />
      </div>
      <RegimeStatusBar locale={locale} result={result} text={text} />
      <div className="flex flex-wrap items-stretch divide-x divide-border-subtle rounded-lg border border-border-subtle bg-bg-surface">
        <MetricStat
          hint={trendHelp(result, locale, text)}
          label={text.underlying}
          size="inline"
          value={formatNumber(result.underlying_price)}
        />
        <MetricStat label={text.scannedExpirations} size="inline" value={String(expirationCount)} />
        <MetricStat label="HV" size="inline" value={formatPercent(result.historical_volatility)} />
        <MetricStat
          hint={hvIvHelp(result, locale)}
          label={text.hvIvStatus}
          size="inline"
          value={hvIvStatus(result, locale, text)}
        />
        <MetricStat
          label={text.candidates}
          size="inline"
          tone={eligible.length > 0 ? "success" : "warning"}
          value={String(eligible.length)}
        />
        <MetricStat
          hint={text.filteredOutHelp}
          label={text.filteredOut}
          size="inline"
          tone={filteredOut > 0 ? "warning" : "neutral"}
          value={String(filteredOut)}
        />
        <MetricStat
          hint={trendHelp(result, locale, text)}
          label="EMA21 / SMA50"
          size="inline"
          value={`${formatNumber(result.ema_21)} / ${formatNumber(result.sma_50)}`}
        />
      </div>
      {result.scanned_contract_count !== undefined ? (
        <ScreenerDiagnostics result={result} locale={locale} />
      ) : null}
      {result.candidates.length === 0 ? (
        <div className="rounded-lg border border-warning/40 bg-warning/10 p-4 font-body-sm text-warning">
          <p className="font-semibold">
            {text.zeroTitleA} {expirationCount} {text.zeroTitleB} {filteredOut}{" "}
            {text.zeroTitleC}
          </p>
          <p className="mt-2 text-text-secondary">{text.zeroBody}</p>
          <RejectionSummary locale={locale} summary={result.rejection_summary} text={text} />
        </div>
      ) : eligible.length === 0 ? (
        <div className="rounded-lg border border-warning/40 bg-warning/10 p-4 font-body-sm text-warning">
          <p className="font-semibold">
            {text.noEligibleTitle} — {result.candidates.length} {text.noEligibleBody}
          </p>
          <p className="mt-2 text-text-secondary">{showRejected ? text.rejectedAlreadyVisible : text.noEligibleHint}</p>
          <RejectionSummary locale={locale} summary={result.rejection_summary} text={text} />
        </div>
      ) : (
        <CandidateTable
          expanded={expanded}
          locale={locale}
          onToggle={(symbol) => setExpanded((current) => (current === symbol ? null : symbol))}
          rows={eligible}
          text={text}
        />
      )}
      {showRejected && rejected.length > 0 ? (
        <RejectedTable locale={locale} rows={rejected} text={text} />
      ) : null}
      {(result.watch_candidates?.length ?? 0) > 0 ? (
        <details className="rounded-lg border border-border-subtle bg-bg-surface p-3">
          <summary className="app-touch-target cursor-pointer font-body-sm text-text-primary">
            {locale === "zh" ? "仅供观察：基础质量已过，但不符合本次筛选条件" : "Observation only: quality passed, selected filters failed"}
            {` (${result.watch_candidates!.length})`}
          </summary>
          <p className="my-2 font-body-sm text-text-secondary">
            {locale === "zh" ? "最多展示 10 条，不计入合格候选。只有你修改条件并重新筛选后才会重新判定。" : "Up to 10 rows, excluded from eligible candidates. Change filters and rerun to reassess."}
          </p>
          <div className="divide-y divide-border-subtle">
            {result.watch_candidates!.map((candidate) => (
              <div key={candidate.symbol} className="py-2 font-body-sm">
                <div className="font-data-mono text-text-primary">{candidate.symbol}</div>
                <p className="text-text-secondary">
                  {locale === "zh" ? "中间价权利金年化" : "Mid premium APR"} {formatPercent(candidate.annualized_yield)}
                  {" · "}{locale === "zh" ? "买一价" : "Bid"} {formatPercent(candidate.bid_annualized_yield)}
                  {" · "}{(candidate.preference_rejection_reasons ?? []).map((reason) => translateRejectionReason(reason, locale)).join(" / ")}
                </p>
              </div>
            ))}
          </div>
        </details>
      ) : null}
      <details className="border-t border-border-subtle pt-3">
        <summary className="app-touch-target cursor-pointer font-label-caps text-text-secondary">{text.assumptions}</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 font-body-sm text-text-secondary">
          {result.assumptions.map((assumption) => (
            <li key={assumption}>{translateAssumption(assumption, locale)}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}

function ScreenerDiagnostics({ result, locale }: { result: OptionsScreenerResult; locale: Locale }) {
  const zh = locale === "zh";
  return (
    <div className="rounded-lg border border-border-subtle bg-bg-surface-muted p-3 font-body-sm">
      <p className="text-text-primary">
        {zh ? "本次完整筛选" : "Full scan"}: {result.scanned_contract_count}
        {" · "}{zh ? "基础质量未通过" : "Quality failed"}: {result.hard_gate_rejected_count ?? 0}
        {" · "}{zh ? "个人条件或市场状态不符" : "Filters or regime failed"}: {result.preference_rejected_count ?? 0}
        {" · "}{zh ? "全部符合" : "Eligible"}: {result.eligible_count ?? 0}
      </p>
      <p className="mt-1 text-text-secondary">
        {zh ? "以上三类互不重叠，按整条期权链统计；表格仅展示排序靠前的合约。事件资料、报价、流动性和正期望值检查始终保留。" : "The three outcome groups are disjoint and count the whole chain; the table shows top-ranked rows only. Event, quote, liquidity and positive-EV checks remain in force."}
      </p>
      {result.apr_alternative_max_percent != null ? (
        <p className="mt-2 text-warning">
          {zh
            ? `仅年化目标未达标的合约中，最高中间价权利金年化为 ${result.apr_alternative_max_percent.toFixed(2)}%，当前要求 ${result.requested_min_apr}%。可以手动修改收益目标后重新筛选，或等待报价变化；系统没有自动降低条件。`
            : `Among contracts missing only APR, the highest mid premium APR is ${result.apr_alternative_max_percent.toFixed(2)}%, versus your ${result.requested_min_apr}% target. Edit the target and rerun, or wait for prices to change. No filter was changed automatically.`}
        </p>
      ) : null}
      <details className="mt-2">
        <summary className="app-touch-target cursor-pointer text-text-secondary">{zh ? "查看全部排除原因与处理建议" : "All exclusion reasons and next steps"}</summary>
        <RejectionSummary locale={locale} summary={result.rejection_summary} text={copy[locale]} />
        <p className="mt-2 text-text-secondary">{zh ? "财报或除息资料缺失时补资料；报价过旧时等开市后重查；价差或成交量不合格时换标的或等待。不要为增加数量放宽这些质量要求。预设的期限、波动和收益目标需要一起看，较高的权利金通常伴随较高风险。" : "Refresh missing event evidence, recheck stale quotes after market open, and wait or choose another ticker for poor liquidity. Do not loosen quality checks to increase counts. Consider expiry, volatility and yield together; higher premium usually brings higher risk."}</p>
      </details>
    </div>
  );
}

function CandidateTable({
  expanded,
  locale,
  onToggle,
  rows,
  text,
}: {
  expanded: string | null;
  locale: Locale;
  onToggle: (symbol: string) => void;
  rows: OptionsScreenerCandidate[];
  text: ResultsText;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border-subtle bg-bg-surface">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b border-border-subtle">
            <th className={`${resultHeaderClass} ${stickyCellClass}`}>{text.colContract}</th>
            <th className={resultHeaderClass}>{text.colExpiry}</th>
            <th className={resultHeaderClass}>{text.colStrike}</th>
            <th className={resultHeaderClass}>{text.colMid}</th>
            <th className={resultHeaderClass}>
              <span className="inline-flex items-center gap-1">
                {text.colDelta}
                <InfoTip locale={locale} term="delta" />
              </span>
            </th>
            <th className={resultHeaderClass}>
              <span className="inline-flex items-center gap-1">
                {text.colAnnualized}
                <InfoTip locale={locale} term="apr" />
              </span>
            </th>
            <th className={resultHeaderClass}>
              <span className="inline-flex items-center gap-1">
                {text.colIvr}
                <InfoTip locale={locale} term="ivRank" />
              </span>
            </th>
            <th className={resultHeaderClass}>
              <span className="inline-flex items-center gap-1">
                {text.colSpread}
                <InfoTip locale={locale} term="spread" />
              </span>
            </th>
            <th className={resultHeaderClass}>
              <span className="inline-flex items-center gap-1">
                {text.colOi}
                <InfoTip locale={locale} term="openInterest" />
              </span>
            </th>
            <th className={resultHeaderClass}>{text.colEvents}</th>
            <th className={resultHeaderClass}>{text.colScore}</th>
            <th className={resultHeaderClass}>{text.colDetails}</th>
          </tr>
        </thead>
        <tbody className="font-data-mono text-data-mono text-text-primary">
          {rows.map((candidate) => {
            const isExpanded = expanded === candidate.symbol;
            const detailId = `screener-candidate-detail-${candidate.symbol}`;
            return (
              <Fragment key={candidate.symbol}>
                <tr className="border-b border-border-subtle/50">
                  <td className={`${resultCellClass} ${stickyCellClass}`}>
                    <div>{candidate.symbol}</div>
                    <div className="text-text-secondary">{typeLabel(candidate, text)}</div>
                  </td>
                  <td className={resultCellClass}>{expiryLabel(candidate, locale)}</td>
                  <td className={resultCellClass}>{formatNumber(candidate.strike)}</td>
                  <td className={resultCellClass}>{formatNumber(candidate.mid)}</td>
                  <td className={resultCellClass}>{formatNumber(candidate.delta, 3)}</td>
                  <td className={resultCellClass}>
                    <div>{formatPercent(candidate.annualized_yield ?? candidate.gross_annualized_yield)}</div>
                    <div className="font-body-sm text-text-secondary">{locale === "zh" ? "买一价" : "Bid"} {formatPercent(candidate.bid_annualized_yield)}</div>
                  </td>
                  <td className={resultCellClass}>{formatNumber(candidate.iv_rank, 1)}</td>
                  <td className={resultCellClass}>{formatPercent(candidate.spread_pct)}</td>
                  <td className={resultCellClass}>{formatNumber(candidate.open_interest, 0)}</td>
                  <td className={resultCellClass}>
                    <EventsCell candidate={candidate} locale={locale} text={text} />
                  </td>
                  <td className={resultCellClass}>
                    <div>{formatPercent(candidate.recommendation_score)}</div>
                    <div className="font-body-sm text-text-secondary">
                      {Math.round(candidate.seller_score?.composite ?? 0)}{" "}
                      {ratingLabel(candidate.rating, locale, text)}
                    </div>
                  </td>
                  <td className={resultCellClass}>
                    <button
                      aria-controls={detailId}
                      aria-expanded={isExpanded}
                      className="rounded-md text-info focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
                      onClick={() => onToggle(candidate.symbol)}
                      type="button"
                    >
                      {isExpanded ? text.collapse : text.details}
                    </button>
                  </td>
                </tr>
                {isExpanded ? (
                  <tr className="border-b border-border-subtle/50" id={detailId}>
                    <td className="px-3 py-3" colSpan={12}>
                      <CandidateDetail candidate={candidate} locale={locale} />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// Exported so the expanded-row rendering can be unit tested directly: it is
// the only place that touches optional detail fields (null ex-dividend date
// crashed the first version), and static markup cannot click the toggle.
export function CandidateDetail({
  candidate,
  locale,
}: {
  candidate: OptionsScreenerCandidate;
  locale: Locale;
}) {
  const text = copy[locale];
  const reasons = rejectionLine(candidate, locale);
  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3 lg:grid-cols-4">
        <DetailItem label={locale === "zh" ? "买一价权利金 / 张" : "Bid premium / contract"} value={formatNumber(candidate.bid_premium_per_contract)} />
        <DetailItem label={locale === "zh" ? "中间价毛权利金年化" : "Mid gross premium APR"} value={formatPercent(candidate.gross_annualized_yield)} />
        <DetailItem label={locale === "zh" ? "开平仓费用估计 / 张" : "Round-trip fee estimate / contract"} value={candidate.estimated_round_trip_fee_per_contract == null ? (locale === "zh" ? "未填写" : "Not supplied") : formatNumber(candidate.estimated_round_trip_fee_per_contract)} />
        <DetailItem label={locale === "zh" ? "买一价扣费后权利金年化" : "Bid premium APR after estimated fees"} value={formatPercent(candidate.fee_adjusted_bid_annualized_yield)} />
        <DetailItem label={locale === "zh" ? "报价时间" : "Quote time"} value={candidate.quote_as_of ?? "--"} />
        <DetailItem label={text.detailExtrinsic} value={formatNumber(candidate.extrinsic_value)} />
        <DetailItem label={text.detailPop} value={formatPercent(candidate.pop)} />
        <DetailItem label={text.detailOtm} value={formatPercent(candidate.otm_pct)} />
        <DetailItem label={text.detailEvShare} value={formatNumber(candidate.expected_value)} />
        <DetailItem
          label={text.detailExcessEv}
          value={formatPercent(candidate.excess_annualized_ev)}
        />
        <DetailItem label={text.detailLiquidity} value={formatPercent(candidate.liquidity_factor)} />
        <DetailItem label={text.detailBreakeven} value={formatNumber(candidate.breakeven)} />
        <DetailItem
          label={text.detailTp50}
          value={formatNumber(candidate.take_profit_50_price)}
        />
        <DetailItem label={text.detailDte21} value={candidate.manage_at_21_dte ?? "--"} />
        <DetailItem
          label={text.detailExDividend}
          value={eventValue(candidate.ex_dividend_date, candidate.ex_dividend_in_window, text)}
        />
      </div>
      <p className="font-body-sm text-text-secondary">
        {locale === "zh" ? "权利金年化不含期权买回成本、指派和持股盈亏。中间价与买一价均不保证成交；扣费数字只在填写费用后计算。EV 沿用未扣费的物理模型估计，不能当作实际收益。美式期权到期前也可能被指派；卖出看跌需要备好接股现金，备兑看涨需要已有足额股票。" : "Premium APR excludes buyback cost, assignment and stock P&L. Neither mid nor bid guarantees a fill. Fee-adjusted figures require supplied fees. EV remains the uncosted physical-model estimate. American options can be assigned before expiry; cash-secured puts need cash for delivery and covered calls need owned shares."}
      </p>
      <div className="font-body-sm text-text-secondary">
        {text.statusLabel}: {text.gatePassed} · {text.ratingLabel}{" "}
        {ratingLabel(candidate.rating, locale, text)} · {text.sellerScoreLabel}{" "}
        {formatSellerScoreLine(candidate.seller_score, locale)}
      </div>
      <div className="whitespace-normal break-words font-body-sm text-text-secondary">
        {text.reasonsLabel}: {reasons || text.noNotes}
      </div>
    </div>
  );
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="font-label-caps text-[10px] uppercase text-text-secondary">{label}</span>
      <span className="font-data-mono text-text-primary">{value}</span>
    </div>
  );
}

function RejectedTable({
  locale,
  rows,
  text,
}: {
  locale: Locale;
  rows: OptionsScreenerCandidate[];
  text: ResultsText;
}) {
  return (
    <div className="rounded-lg border border-dashed border-border-subtle bg-bg-surface">
      <div className="border-b border-border-subtle px-3 py-2">
        <h3 className="font-label-caps text-text-secondary">
          {text.rejectedTitle} ({rows.length})
        </h3>
        <p className="mt-1 font-body-sm text-text-secondary">{text.rejectedHint}</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="border-b border-border-subtle">
              <th className={`${resultHeaderClass} ${stickyCellClass}`}>{text.colContract}</th>
              <th className={resultHeaderClass}>{text.colExpiry}</th>
              <th className={resultHeaderClass}>{text.colStrike}</th>
              <th className={resultHeaderClass}>{text.colMid}</th>
              <th className={resultHeaderClass}>{text.colDelta}</th>
              <th className={resultHeaderClass}>{text.colSpread}</th>
              <th className={resultHeaderClass}>{text.colOi}</th>
              <th className={resultHeaderClass}>{text.colScore}</th>
              <th className={resultHeaderClass}>{text.colReasons}</th>
            </tr>
          </thead>
          <tbody className="font-data-mono text-data-mono text-text-secondary">
            {rows.map((candidate) => (
              <tr className="border-b border-border-subtle/50" key={candidate.symbol}>
                <td className={`${resultCellClass} ${stickyCellClass}`}>
                  <div>{candidate.symbol}</div>
                  <div className="text-text-secondary">{typeLabel(candidate, text)}</div>
                </td>
                <td className={resultCellClass}>{expiryLabel(candidate, locale)}</td>
                <td className={resultCellClass}>{formatNumber(candidate.strike)}</td>
                <td className={resultCellClass}>{formatNumber(candidate.mid)}</td>
                <td className={resultCellClass}>{formatNumber(candidate.delta, 3)}</td>
                <td className={resultCellClass}>{formatPercent(candidate.spread_pct)}</td>
                <td className={resultCellClass}>{formatNumber(candidate.open_interest, 0)}</td>
                <td className={resultCellClass}>
                  {Math.round(candidate.seller_score?.composite ?? 0)}{" "}
                  {ratingLabel(candidate.rating, locale, text)}
                </td>
                <td className="min-w-[280px] whitespace-normal break-words px-3 py-2 font-body-sm">
                  {rejectionLine(candidate, locale) || text.noNotes}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EventsCell({
  candidate,
  locale,
  text,
}: {
  candidate: OptionsScreenerCandidate;
  locale: Locale;
  text: ResultsText;
}) {
  const reasons = candidate.recommendation_rejection_reasons;
  const items: { label: string; warning: boolean }[] = [];
  if (candidate.earnings_date) {
    items.push({
      label: eventValue(candidate.earnings_date, candidate.earnings_in_window, text, text.earnings),
      warning: candidate.earnings_in_window,
    });
  } else if (reasons.includes("earnings_data_missing")) {
    items.push({ label: text.earningsUnknown, warning: false });
  }
  if (candidate.ex_dividend_date) {
    items.push({
      label: eventValue(
        candidate.ex_dividend_date,
        candidate.ex_dividend_in_window,
        text,
        text.exDividend,
      ),
      warning: candidate.ex_dividend_in_window,
    });
  } else if (reasons.includes("ex_dividend_data_missing")) {
    items.push({ label: text.exDividendUnknown, warning: false });
  }
  if (!items.length) {
    return <span className="text-text-secondary">{text.notApplicable}</span>;
  }
  return (
    <div className="flex flex-col gap-0.5">
      {items.map((item) => (
        <span
          className={item.warning ? "text-warning" : "text-text-primary"}
          key={item.label}
        >
          {item.label}
        </span>
      ))}
    </div>
  );
}

function eventValue(
  date: string | null | undefined,
  inWindow: boolean,
  text: ResultsText,
  prefix?: string,
) {
  if (!date) {
    return "--";
  }
  const short = date.length >= 10 ? date.slice(5, 10) : date;
  const base = prefix ? `${prefix} ${short}` : date;
  return inWindow ? `${base} (${text.inWindow})` : base;
}

function expiryLabel(candidate: OptionsScreenerCandidate, locale: Locale) {
  const dte = candidate.days_to_expiry;
  if (typeof dte !== "number" || !Number.isFinite(dte)) {
    return candidate.expiry;
  }
  return `${candidate.expiry} · ${dte}${locale === "zh" ? "天" : "d"}`;
}

function typeLabel(candidate: OptionsScreenerCandidate, text: ResultsText) {
  return candidate.option_type === "PUT" ? text.typePut : text.typeCall;
}

function rejectionLine(candidate: OptionsScreenerCandidate, locale: Locale) {
  return [
    ...candidate.recommendation_rejection_reasons.map((reason) =>
      recommendationReasonLabel(reason, locale),
    ),
    ...candidate.notes.map((note) => translateRejectionReason(note, locale)),
  ].join(" | ");
}

function RejectionSummary({
  locale,
  summary,
  text,
}: {
  locale: Locale;
  summary?: Record<string, number>;
  text: ResultsText;
}) {
  const rows = Object.entries(summary ?? {}).slice(0, 5);
  if (!rows.length) {
    return null;
  }
  return (
    <div className="mt-3 rounded-lg border border-border-subtle bg-bg-surface/70 p-3">
      <div className="font-label-caps text-text-secondary">{text.zeroReasons}</div>
      <ul className="mt-2 space-y-1 font-body-sm text-text-secondary">
        {rows.map(([reason, count]) => (
          <li className="flex justify-between gap-4" key={reason}>
            <span>{translateRejectionReason(reason, locale)}</span>
            <span className="font-data-mono text-text-primary">{count}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

type RegimeLabel = "Normal" | "Elevated" | "Panic" | "Unknown";

function RegimeStatusBar({
  locale,
  result,
  text,
}: {
  locale: Locale;
  result: OptionsScreenerResult;
  text: ResultsText;
}) {
  const label: RegimeLabel = (result.market_regime ?? "Unknown") as RegimeLabel;
  const palette: Record<RegimeLabel, string> = {
    Normal: "border-accent-success/40 bg-accent-success/10 text-accent-success",
    Elevated: "border-warning/40 bg-warning/10 text-warning",
    Panic: "border-danger/40 bg-danger/10 text-danger",
    Unknown: "border-border-subtle bg-bg-surface text-text-secondary",
  };
  const detail =
    label === "Normal"
      ? text.regimeNormal
      : label === "Elevated"
        ? text.regimeElevated
        : label === "Panic"
          ? text.regimePanic
          : text.regimeUnknown;
  const penalty = result.market_regime_penalty;
  const penaltyText =
    typeof penalty === "number" && Number.isFinite(penalty) && penalty !== 0
      ? ` (${penalty > 0 ? "+" : ""}${penalty.toFixed(0)})`
      : "";
  return (
    <div
      className={`flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border px-3 py-1.5 ${palette[label]}`}
    >
      <span className="font-label-caps text-[10px] uppercase">{text.regime}</span>
      <span className="font-data-mono text-sm font-bold">
        {label}
        {penaltyText}
      </span>
      {/* Full explanation stays accessible but no longer eats a whole banner. */}
      <span className="min-w-0 flex-1 truncate font-body-sm opacity-80" title={detail}>
        {detail}
      </span>
    </div>
  );
}

function formatNumber(value?: number | null, digits = 2) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "--";
}

function formatPercent(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${(value * 100).toFixed(2)}%`
    : "--";
}

function formatRatio(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "--";
}

function trendHelp(result: OptionsScreenerResult, locale: Locale, text: ResultsText) {
  const price = result.underlying_price;
  const ema21 = result.ema_21;
  const sma50 = result.sma_50;
  if (
    typeof ema21 !== "number"
    || !Number.isFinite(ema21)
    || typeof sma50 !== "number"
    || !Number.isFinite(sma50)
  ) {
    return locale === "zh" ? "均线数据不足，趋势只作参考。" : "Moving-average data is incomplete; trend is reference-only.";
  }
  const warnings = [];
  if (price < ema21) {
    warnings.push(locale === "zh" ? "低于 EMA21" : "below EMA21");
  }
  if (price < sma50) {
    warnings.push(locale === "zh" ? "低于 SMA50" : "below SMA50");
  }
  if (!warnings.length) {
    return text.trendPassed;
  }
  return `${text.trendWeak}: ${warnings.join(locale === "zh" ? "、" : " / ")}`;
}

function hvIvStatus(result: OptionsScreenerResult, locale: Locale, text: ResultsText) {
  const total = result.hv_iv_contract_count ?? 0;
  if (total <= 0) {
    return text.hvIvUnavailable;
  }
  const passed = result.hv_iv_pass_count ?? 0;
  return locale === "zh" ? `${passed}/${total} 通过` : `${passed}/${total} pass`;
}

function hvIvHelp(result: OptionsScreenerResult, locale: Locale) {
  const total = result.hv_iv_contract_count ?? 0;
  if (total <= 0) {
    return locale === "zh" ? "没有可用的 IV，无法判断 HV/IV。" : "No usable IV, so HV/IV cannot be judged.";
  }
  const threshold = formatRatio(result.hv_iv_threshold);
  const low = formatRatio(result.hv_iv_min);
  const high = formatRatio(result.hv_iv_max);
  return locale === "zh"
    ? `上限 ${threshold}；范围 ${low}-${high}`
    : `Limit ${threshold}; range ${low}-${high}`;
}

function ratingLabel(rating: string, locale: Locale, text: ResultsText) {
  if (locale === "en") {
    return rating;
  }
  if (rating === "Strong") {
    return text.strong;
  }
  if (rating === "Watch") {
    return text.watch;
  }
  return text.avoid;
}

const recommendationReasonZh: Record<string, string> = {
  covered_call_extrinsic_not_above_dividend: "外在价值未覆盖窗口内股息",
  delta_missing: "缺少 Delta",
  delta_outside_range: "Delta 超出评分区间",
  dividend_per_share_invalid: "股息数据无效",
  dte_inconsistent: "DTE 与日期不一致",
  dte_missing: "缺少 DTE",
  dte_outside_range: "DTE 超出评分区间",
  earnings_data_missing: "缺少财报日期真值",
  earnings_within_dte: "到期前有财报",
  ex_dividend_data_missing: "缺少除息真值",
  ex_dividend_date_past: "只有历史除息日，下一次除息日期未知",
  extrinsic_value_invalid: "外在价值无效",
  implied_volatility_invalid: "IV 数据无效",
  implied_volatility_missing: "缺少 IV",
  iv_rank_invalid: "IVR 数据无效",
  iv_rank_missing: "缺少 IVR 真值",
  mid_below_minimum: "中间价低于评分下限",
  mid_missing: "缺少中间价",
  non_positive_excess_ev: "期望赔付不低于权利金（物理 EV 不为正）",
  open_interest_below_minimum: "未平仓量低于评分下限",
  open_interest_invalid: "未平仓数据无效",
  open_interest_missing: "缺少未平仓量",
  quote_as_of_invalid: "报价时间无效",
  quote_as_of_missing: "缺少报价时间",
  quote_future: "报价时间晚于当前会话",
  quote_observed_at_invalid: "观察时间无效",
  quote_session_invalid: "报价不在交易日",
  quote_stale: "报价已过期",
  risk_free_rate_invalid: "无风险利率无效",
  risk_free_rate_missing: "缺少无风险利率",
  spread_above_maximum: "价差超过评分上限",
  spread_invalid: "价差数据无效",
  spread_missing: "缺少价差",
  strike_invalid: "行权价无效",
  underlying_price_invalid: "正股价格无效",
};

function recommendationReasonLabel(reason: string, locale: Locale) {
  return locale === "zh" ? recommendationReasonZh[reason] ?? reason : reason;
}

const assumptionZh: Record<string, string> = {
  "Read-only data mode; no order placement is available.": "只读数据模式；不会下单。",
  "When expiration is omitted, the screener scans all Futu expirations inside the configured DTE window.":
    "未指定到期日时，后端会扫描 DTE 范围内所有 Futu 到期日。",
  "Avoid-rated contracts are hidden by default; set include_rejected=true to audit rejected rows.":
    "默认隐藏 Avoid 合约；需要排查时可启用 include_rejected 查看被过滤行。",
  "Premium uses mid price when bid and ask are available.": "买卖价可用时，权利金按中间价估算。",
  "Yield estimates are simplified and ignore assignment, taxes, and commissions.":
    "中间价毛权利金年化是简化估算，未计入指派、税费和佣金。",
  "Minimum APR uses the mid-price gross premium estimate. Bid-price estimates are separate; neither is a realized strategy return.":
    "最低年化条件使用中间价毛权利金，买一价估算单独展示；二者都不是实际策略收益。",
  "Fee-adjusted bid premium is shown only when round-trip fees are supplied; it excludes buyback cost, assignment and underlying P&L. Standard 100-share contracts assumed.":
    "只有填写开平仓总费用后，才计算买一价扣费权利金；不包含买回期权、指派和持股盈亏。按标准每张100股估算。",
  "Missing IV/Greeks fields reduce confidence; they are not invented.": "缺少 IV 或希腊值会降低可信度，系统不会编造这些数据。",
  "VIX market regime is read from the offline Yahoo cache and discounts seller ratings under Elevated / Panic conditions.":
    "VIX 市场状态来自本地缓存；市场偏紧张时会下调卖方候选评级。",
};

const rejectionReasonZh: Record<string, string> = {
  "APR below minimum": "毛权利金年化低于最低要求",
  "covered call strike is below spot": "covered call 行权价低于现价",
  "delta above limit": "Delta 超过上限",
  "delta missing": "缺少 Delta",
  "DTE missing": "缺少到期天数",
  "DTE outside range": "到期天数不在范围内",
  "IV below minimum": "IV 低于最低要求",
  "IV missing": "缺少 IV",
  "IV/HV filter failed": "近期实际波动相对期权隐含波动偏高，卖方补偿不足",
  "market cap below minimum": "市值低于要求",
  "market cap missing": "缺少市值",
  "mid below absolute floor": "中间价低于最低要求",
  "missing or non-positive bid/ask": "缺少有效买卖价",
  "open interest below minimum": "未平仓量低于要求",
  "open interest missing": "缺少未平仓量",
  "premium below minimum": "权利金低于最低要求",
  "price below EMA21": "价格低于 EMA21",
  "price below SMA50": "价格低于 SMA50",
  "sell put strike is above spot": "卖出看跌行权价高于现价",
  "spread too wide": "买卖价差过宽",
  "stale quote": "报价过旧",
  "trend filter failed": "趋势过滤未通过",
  "underlying ADV below minimum": "正股成交量低于要求",
  "underlying ADV missing": "缺少正股成交量",
};

function translateAssumption(value: string, locale: Locale) {
  return locale === "zh" ? assumptionZh[value] ?? value : value;
}

function translateRejectionReason(value: string, locale: Locale) {
  return locale === "zh" ? rejectionReasonZh[value] ?? recommendationReasonZh[value] ?? value : value;
}
