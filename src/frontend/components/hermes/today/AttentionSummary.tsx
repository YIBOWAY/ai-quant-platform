import Link from "next/link";
import { Card } from "@/components/ui/primitives";
import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import { hermesRouteHref } from "@/lib/hermes/routes";
import type { HermesAttentionItem } from "@/lib/hermes/types";
import type { Locale } from "@/lib/locale";

export type AttentionSummaryProps = {
  items: HermesAttentionItem[];
  locale: Locale;
};

const PRIMARY_KINDS = new Set<HermesAttentionItem["kind"]>([
  "approval",
  "failure",
  "stale",
  "offline",
]);

function localizedTitle(item: HermesAttentionItem, locale: Locale): string {
  const copy = hermesWorkbenchCopy(locale);
  if (item.kind === "approval") return copy.labels.researchApproval;
  if (item.kind === "offline") return copy.states.offline;
  if (item.kind === "stale") {
    return locale === "zh" ? "自动化任务已过期" : "Automation job stale";
  }
  if (item.kind === "failure") {
    return locale === "zh" ? "自动化任务失败" : "Automation job failed";
  }
  return item.title;
}

/**
 * Surfaces only approval / failure / stale / offline attention.
 * Degraded non-actionable items stay out of the primary attention strip.
 */
export function AttentionSummary({ items, locale }: AttentionSummaryProps) {
  const copy = hermesWorkbenchCopy(locale);
  const primary = items.filter((item) => PRIMARY_KINDS.has(item.kind));

  if (primary.length === 0) {
    return null;
  }

  return (
    <section aria-labelledby="hermes-attention-title" data-hermes-attention>
      <h2 className="font-label-caps text-text-secondary" id="hermes-attention-title">
        {copy.labels.attention}
      </h2>
      <ul className="mt-2 space-y-2">
        {primary.map((item) => {
          const title = localizedTitle(item, locale);
          const href =
            item.href ??
            (item.kind === "approval"
              ? hermesRouteHref("approvals", locale)
              : item.kind === "failure" || item.kind === "stale"
                ? hermesRouteHref("tasks", locale)
                : undefined);

          return (
            <li key={item.id}>
              <Card
                className="border-[var(--color-hermes-attention)]/40 bg-[var(--color-hermes-attention)]/5"
                tone="warning"
              >
                <article data-hermes-attention-kind={item.kind} data-hermes-attention-id={item.id}>
                  <h3 className="font-body-sm font-semibold text-text-primary">{title}</h3>
                  <p className="mt-1 break-words font-data-mono text-xs text-text-secondary">
                    {item.id}
                  </p>
                  <p className="mt-2 font-body-sm text-text-secondary">{item.summary}</p>
                  {href ? (
                    <p className="mt-3">
                      <Link
                        className="app-touch-target inline-flex items-center font-body-sm text-info underline-offset-2 hover:underline"
                        href={href}
                      >
                        {item.kind === "approval"
                          ? locale === "zh"
                            ? "打开审批页"
                            : "Open approvals"
                          : locale === "zh"
                            ? "打开任务页"
                            : "Open tasks"}
                      </Link>
                    </p>
                  ) : null}
                </article>
              </Card>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
