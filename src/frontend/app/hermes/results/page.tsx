import Link from "next/link";
import { FocusedArtifactCard } from "@/components/hermes/artifacts";
import { Card } from "@/components/ui/primitives";
import { getHermesArtifacts } from "@/lib/api";
import { localizePath } from "@/lib/locale";
import { getServerLocale } from "@/lib/serverLocale";

/** Existing platform result surfaces — unified Hermes dynamic routes stay off. */
const CANONICAL_RESULT_LINKS = [
  { path: "/factor-lab", zh: "因子实验室", en: "Factor Lab" },
  { path: "/backtest", zh: "回测", en: "Backtest" },
  { path: "/experiments", zh: "实验", en: "Experiments" },
  { path: "/agent-studio", zh: "智能体工作室", en: "Agent Studio" },
  { path: "/paper-trading", zh: "模拟交易", en: "Paper trading" },
] as const;

/**
 * F2 Results: read-only 9H artifact index.
 * Links only to existing canonical platform routes; no /hermes/results/* detail.
 */
export default async function HermesResultsPage() {
  const locale = await getServerLocale();
  const artifacts = await getHermesArtifacts();
  const isZh = locale === "zh";
  const conclusions = artifacts.items.filter(
    (item) => item.kind !== "automation_status",
  );

  return (
    <section
      aria-labelledby="hermes-results-title"
      className="space-y-4"
      data-hermes-results
    >
      <header className="space-y-2">
        <p className="font-label-caps uppercase text-text-secondary">
          {isZh ? "结果" : "Results"}
        </p>
        <h1 className="font-headline-lg text-text-primary" id="hermes-results-title">
          {isZh ? "结果" : "Results"}
        </h1>
        <p className="font-body-sm text-text-secondary">
          {isZh
            ? "统一动态路由尚未启用；深链仅指向既有平台页面。"
            : "Unified dynamic routes stay off; deep links use existing platform pages only."}
        </p>
      </header>

      <Card className="border-info/30 bg-info/5" tone="info">
        <p className="font-body-sm font-semibold text-text-primary">
          {isZh ? "只读结果索引" : "Read-only result index"}
        </p>
        <p className="mt-1 font-body-sm text-text-secondary">
          {isZh
            ? "以下为当前 9H 研究产物与既有平台入口，不含统一 Hermes 详情页。"
            : "Current 9H research artifacts and existing platform entry points — no unified Hermes detail pages."}
        </p>
      </Card>

      <section aria-labelledby="hermes-results-canonical-title" className="space-y-2">
        <h2
          className="font-label-caps text-text-secondary"
          id="hermes-results-canonical-title"
        >
          {isZh ? "既有平台入口" : "Canonical platform entry points"}
        </h2>
        <ul className="flex flex-wrap gap-2">
          {CANONICAL_RESULT_LINKS.map((entry) => (
            <li key={entry.path}>
              <Link
                className="app-touch-target inline-flex items-center rounded-lg border border-border-subtle px-3 font-body-sm text-info underline-offset-2 hover:bg-bg-surface-muted hover:underline"
                href={localizePath(entry.path, locale)}
              >
                {isZh ? entry.zh : entry.en}
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="hermes-results-feed-title" className="space-y-3">
        <h2 className="font-label-caps text-text-secondary" id="hermes-results-feed-title">
          {isZh ? "9H 研究产物" : "9H research artifacts"}
        </h2>
        {conclusions.length === 0 ? (
          <Card className="bg-[var(--color-stream-surface)]">
            <p className="font-body-sm text-text-secondary">
              {isZh ? "当前没有可展示的研究结论产物。" : "No research conclusion artifacts."}
            </p>
          </Card>
        ) : (
          <ul className="space-y-3">
            {conclusions.map((artifact) => (
              <li key={artifact.id}>
                <FocusedArtifactCard artifact={artifact} locale={locale} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </section>
  );
}
