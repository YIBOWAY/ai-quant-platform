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
          className="absolute bottom-full left-1/2 z-50 mb-1 w-64 -translate-x-1/2 rounded border border-border-subtle bg-bg-surface p-2 font-body-sm normal-case leading-relaxed text-text-primary shadow-lg"
          id={id}
          role="tooltip"
        >
          {text}
        </span>
      ) : null}
    </span>
  );
}
