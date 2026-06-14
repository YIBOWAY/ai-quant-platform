'use client';

import { HelpCircle } from "lucide-react";
import { useId, useState } from "react";

type Locale = "en" | "zh";

type GlossaryEntry = {
  en: string;
  zh: string;
};

// Plain-language explanations for option / quant jargon so a zero-experience
// user can understand each term on hover or focus. Keep entries short.
export const GLOSSARY: Record<string, GlossaryEntry> = {
  thetaBurn: {
    en: "Theta burn is how much value the option loses per day just from time passing, even if the stock does not move. Higher means time is working against you faster.",
    zh: "Theta 损耗 = 仅仅因为时间流逝，期权每天损失的价值（即使股价不动）。数值越大，时间对你越不利。",
  },
  ivCrush: {
    en: "IV crush is the loss you take if implied volatility drops (common right after earnings). It estimates how much the option falls just from volatility cooling off.",
    zh: "IV 崩塌 = 隐含波动率下降（常见于财报后）时你会承受的亏损。它估算仅因为波动率回落、期权会跌多少。",
  },
  ivRank: {
    en: "IV rank shows where today's implied volatility sits versus its own past year (0% = cheapest, 100% = most expensive). High IV rank means options are relatively pricey.",
    zh: "IV 排名 = 当前隐含波动率在过去一年里的相对位置（0% 最便宜，100% 最贵）。排名高说明期权相对偏贵。",
  },
  breakEven: {
    en: "Break-even is the underlying price at expiration where the trade neither makes nor loses money.",
    zh: "盈亏平衡价 = 到期时，这笔交易不赚不亏所对应的正股价格。",
  },
  delta: {
    en: "Delta estimates how much the option price moves for a $1 move in the stock. It is also a rough probability of finishing in-the-money.",
    zh: "Delta = 正股每涨跌 1 美元，期权价格大约变动多少；也可粗略看作到期价内的概率。",
  },
  rewardRisk: {
    en: "Reward/risk compares the most you could gain to the most you could lose. Higher is more favourable, but does not account for probability.",
    zh: "盈亏比 = 最大可能盈利 ÷ 最大可能亏损。数值越大越有利，但没有考虑发生概率。",
  },
  apr: {
    en: "Annualized premium is a simplified estimate of the yield if the same premium repeated for a year. It is a screening number, not a guaranteed return.",
    zh: "年化权利金 = 把同样的权利金按一年重复折算出的简化收益率。它只是筛选指标，不代表确定收益。",
  },
  spread: {
    en: "Bid-ask spread is the gap between the buy and sell price. A wide spread means worse liquidity and higher trading cost.",
    zh: "买卖价差 = 买价与卖价之间的差距。价差越宽，流动性越差、交易成本越高。",
  },
  openInterest: {
    en: "Open interest is the number of contracts currently held open. Higher usually means better liquidity and easier fills.",
    zh: "未平仓量 = 当前仍未平仓的合约数量。数值越高通常流动性越好、越容易成交。",
  },
  marketRegime: {
    en: "Market regime classifies recent volatility (Normal / Elevated / Panic) from VIX history and adjusts seller scores accordingly.",
    zh: "市场状态 = 根据 VIX 历史把近期波动分类（Normal / Elevated / Panic），并据此调整卖方评分。",
  },
  hvIv: {
    en: "HV/IV compares recent realized volatility to implied volatility. Lower values mean implied volatility is rich versus how the stock actually moved.",
    zh: "HV/IV = 近期已实现波动率 ÷ 隐含波动率。数值越低，说明隐含波动率相对真实波动更充足（更值得卖出）。",
  },
  requiredMove: {
    en: "Required move is how far the underlying must travel by expiration for the trade to reach break-even.",
    zh: "所需涨跌幅 = 到期前正股需要移动多少，交易才能达到盈亏平衡。",
  },
  netDebit: {
    en: "Net debit is the upfront cost paid to open the position. For long-premium trades this is also your maximum loss.",
    zh: "净支出 = 开仓时先付出的成本。对买方策略来说，这通常也是你的最大亏损。",
  },
  rankIc: {
    en: "Rank IC is the rank correlation between today's factor values and the next period's returns. Positive and stable means the factor ordered stocks usefully; near 0 means no predictive power.",
    zh: "Rank IC = 今天的因子值排序与下一期收益排序的相关性。持续为正说明因子的排序有预测力；接近 0 说明没有用。",
  },
  icDecay: {
    en: "IC decay compares the factor's rank IC at a 5-bar horizon minus the 1-bar horizon. A strongly negative value means the signal fades quickly after one bar.",
    zh: "IC 衰减 = 5 期 Rank IC 减去 1 期 Rank IC。负得越多，说明信号在一期之后衰减得越快。",
  },
  quantileSpread: {
    en: "Quantile spread is the average next-period return of the top factor bucket minus the bottom bucket (5 buckets). Wider positive spread = the factor separates winners from losers better.",
    zh: "分位价差 = 按因子分 5 组后，最高组与最低组的下一期平均收益之差。正向越大，说明因子区分强弱的能力越好。",
  },
  turnover: {
    en: "Turnover measures how much the factor's top-half selection changes between rebalances. Higher turnover means more trading and more cost to harvest the signal.",
    zh: "换手率 = 相邻两次调仓之间，因子前一半选股集合的变化比例。换手越高，落地该信号的交易成本越高。",
  },
  coverage: {
    en: "Coverage is the share of symbol-days where the factor produced a usable value. Low coverage means the metrics are computed on thin data.",
    zh: "覆盖率 = 因子能算出有效值的样本占比。覆盖率低说明指标建立在很少的数据上，可信度打折。",
  },
  lookback: {
    en: "Lookback is how many past bars the factor reads to compute today's value.",
    zh: "回看窗口 = 计算今天的因子值需要读取多少根历史 K 线。",
  },
  zScoreTiming: {
    en: "The timing test trades one symbol long whenever the factor's z-score (vs its own history) is positive, flipped by factor direction. It is a sanity check, not a strategy.",
    zh: "择时测试 = 当因子相对自身历史的 z 分数为正时做多该标的（按因子方向翻转）。它是体检，不是策略。",
  },
  walkForward: {
    en: "Walk-forward splits history into rolling train/validation folds. More folds passing means the factor held up out-of-sample, not just in one lucky window.",
    zh: "滚动验证 = 把历史切成多段训练/验证窗口。通过的折数越多，说明因子不是只在某一段行情里碰巧有效。",
  },
  leakage: {
    en: "The leakage audit checks the factor only uses information available at the time (no future data). A failed audit means the backtest numbers cannot be trusted.",
    zh: "泄漏检查 = 校验因子只用了当时可得的信息（没偷看未来数据）。检查不通过，回测数字就不可信。",
  },
  sharpe: {
    en: "Sharpe ratio is the annualized return divided by annualized volatility. Above 1 is decent for a single signal; sample-data Sharpes can be absurdly high and mean nothing.",
    zh: "夏普比率 = 年化收益 ÷ 年化波动。单一信号超过 1 已经不错；sample 演示数据跑出的超高夏普没有意义。",
  },
  maxDrawdown: {
    en: "Max drawdown is the worst peak-to-trough equity loss over the period — the pain you would have had to sit through.",
    zh: "最大回撤 = 区间内净值从最高点到最低点的最大跌幅，代表你需要承受的最痛阶段。",
  },
  winRate: {
    en: "Win rate is the share of trades that closed profitable. High win rate with a poor Sharpe usually means small wins and large losses.",
    zh: "胜率 = 盈利交易占全部交易的比例。胜率高但夏普差，通常是小赚大亏。",
  },
  priceKind: {
    en: "Price source per fill: futu_snapshot = live Futu quote at order time; last_close = the most recent real daily close (used when OpenD is offline). Demo prices are never used for the account.",
    zh: "成交价来源：futu_snapshot = 下单时的 Futu 实时快照；last_close = 最近一根真实日收盘价（OpenD 离线时回退）。账户绝不使用演示价格。",
  },
};

export type GlossaryKey = keyof typeof GLOSSARY;

export function InfoTip({
  term,
  locale = "en",
  className = "",
}: {
  term: GlossaryKey;
  locale?: Locale;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const entry = GLOSSARY[term];
  if (!entry) {
    return null;
  }
  const text = entry[locale];
  const label = locale === "zh" ? "查看说明" : "What is this?";

  return (
    <span className={`relative inline-flex items-center ${className}`}>
      <button
        aria-describedby={open ? id : undefined}
        aria-label={label}
        className="inline-flex cursor-help text-text-secondary transition-colors hover:text-info focus:text-info focus:outline-none"
        onBlur={() => setOpen(false)}
        onClick={() => setOpen((value) => !value)}
        onFocus={() => setOpen(true)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        type="button"
      >
        <HelpCircle size={13} />
      </button>
      {open ? (
        <span
          className="absolute bottom-full left-1/2 z-50 mb-1 w-64 -translate-x-1/2 rounded-lg border border-border-subtle bg-bg-surface p-2 font-body-sm normal-case leading-relaxed text-text-primary shadow-lg"
          id={id}
          role="tooltip"
        >
          {text}
        </span>
      ) : null}
    </span>
  );
}
