import Link from "next/link";
import { localizePath } from "@/lib/locale";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    eyebrow: "Paper Replication",
    title: "Short-Term Reversals and Longer-Term Momentum",
    intro: "Frontend-readable notes for the local reproduction of DOI 10.1093/rfs/hhaf057.",
    pipelineTitle: "What The Platform Runs",
    pipeline: [
      "1. Pull read-only daily OHLCV data from Futu, Tiingo, or sample.",
      "2. Convert daily closes into month-end closes.",
      "3. Drop observations priced below US$1 at the prior month-end.",
      "4. Rank the prior 1-month return for short-term reversal.",
      "5. Rank the t-12 through t-2 return for longer-term momentum.",
      "6. Form default decile long-short portfolios and hold for one month.",
    ],
    scopeTitle: "Current Scope",
    scopeBody:
      "The workbench implements the core monthly portfolio construction. It does not yet reproduce the full global country tables, earnings-announcement tests, institutional ownership tests, or retail order-imbalance tests from the paper.",
    runTitle: "Where To Run It",
    runBody:
      "Use the workbench for interactive runs. Keep Futu selected for local real data; use sample only for stable smoke tests.",
    openWorkbench: "Open workbench",
    repoDocTitle: "Repository Doc",
  },
  zh: {
    eyebrow: "论文复现",
    title: "短期反转与长期动量",
    intro: "DOI 10.1093/rfs/hhaf057 本地复现的前端速读笔记。",
    pipelineTitle: "平台执行的流程",
    pipeline: [
      "1. 从 Futu、Tiingo 或 sample 拉取只读日线 OHLCV 数据。",
      "2. 把日收盘价转换为月末收盘价。",
      "3. 剔除上一月末价格低于 1 美元的样本。",
      "4. 按上一个月收益排序，构造短期反转信号。",
      "5. 按 t-12 至 t-2 的收益排序，构造长期动量信号。",
      "6. 构建默认十分位多空组合，持有一个月。",
    ],
    scopeTitle: "当前覆盖范围",
    scopeBody:
      "工作台实现了核心的月度组合构建，尚未复现论文中的全球分国家表格、财报公告检验、机构持仓检验和散户订单失衡检验。",
    runTitle: "在哪里运行",
    runBody:
      "请在复现工作台中交互式运行。本地真实数据请保持选择 Futu；sample 仅用于稳定的冒烟测试。",
    openWorkbench: "打开工作台",
    repoDocTitle: "仓库文档",
  },
} as const;

export default async function ReversalMomentumDocPage() {
  const locale = await getServerLocale();
  const text = copy[locale];

  return (
    <div className="h-full overflow-y-auto bg-bg-base p-6">
      <div className="mx-auto max-w-5xl">
        <div className="mb-6 border-b border-border-subtle pb-4">
          <div className="font-label-caps text-text-secondary">{text.eyebrow}</div>
          <h1 className="mt-2 font-headline-xl text-text-primary">{text.title}</h1>
          <p className="mt-2 max-w-3xl font-body-sm text-text-secondary">{text.intro}</p>
        </div>

        <div className="grid gap-4">
          <section className="rounded-lg border border-border-subtle bg-bg-surface p-4">
            <h2 className="font-label-caps text-text-primary">{text.pipelineTitle}</h2>
            <ol className="mt-3 grid gap-2 font-body-sm text-text-secondary">
              {text.pipeline.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          </section>

          <section className="rounded-lg border border-border-subtle bg-bg-surface p-4">
            <h2 className="font-label-caps text-text-primary">{text.scopeTitle}</h2>
            <p className="mt-3 font-body-sm text-text-secondary">{text.scopeBody}</p>
          </section>

          <section className="rounded-lg border border-border-subtle bg-bg-surface p-4">
            <h2 className="font-label-caps text-text-primary">{text.runTitle}</h2>
            <p className="mt-3 font-body-sm text-text-secondary">{text.runBody}</p>
            <Link
              className="mt-4 inline-flex rounded-lg border border-accent-success/40 px-4 py-2 font-body-sm font-semibold text-accent-success transition-colors hover:bg-accent-success/10"
              href={localizePath("/strategies", locale)}
            >
              {text.openWorkbench}
            </Link>
          </section>

          <section className="rounded-lg border border-border-subtle bg-bg-surface p-4">
            <h2 className="font-label-caps text-text-primary">{text.repoDocTitle}</h2>
            <p className="mt-3 font-data-mono text-text-secondary">
              docs/replications/reversal_momentum_replication.md
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
