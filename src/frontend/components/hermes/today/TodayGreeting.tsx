import Link from "next/link";
import { Sunrise } from "lucide-react";
import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import type { HermesTodayOverviewModel } from "@/lib/hermes/types";
import { localizePath, type Locale } from "@/lib/locale";

export type TodayGreetingProps = {
  model: HermesTodayOverviewModel;
  locale: Locale;
};

function formatTodayDate(locale: Locale): string {
  try {
    return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
      month: "long",
      day: "numeric",
      weekday: "short",
      timeZone: "Asia/Shanghai",
    }).format(new Date());
  } catch {
    return "";
  }
}

/**
 * UI-1 Direction A page head: greeting + derived one-line summary
 * (state × attention count), plus the morning-brief entry.
 */
export function TodayGreeting({ model, locale }: TodayGreetingProps) {
  const copy = hermesWorkbenchCopy(locale);
  const summary = copy.today.summary;
  const greeting = copy.today.greeting[model.greetingSlot];
  const attentionCount = model.attention.length;
  const dateLine = formatTodayDate(locale);

  let summaryLine: React.ReactNode;
  if (model.state === "offline") {
    summaryLine = <strong className="font-semibold text-danger">{summary.offline}</strong>;
  } else if (model.state === "degraded") {
    const separator = locale === "zh" ? "，" : " — ";
    summaryLine = (
      <>
        <strong className="font-semibold text-warning">{summary.degradedPrefix}</strong>
        {attentionCount > 0 ? `${separator}${summary.attentionClause(attentionCount)}` : ""}
      </>
    );
  } else if (model.state === "empty") {
    summaryLine = summary.empty;
  } else if (attentionCount > 0) {
    summaryLine = (
      <>
        {locale === "zh" ? "系统正常，" : "Systems normal — "}
        <strong className="font-semibold text-warning">
          {summary.attentionClause(attentionCount)}
        </strong>
      </>
    );
  } else {
    summaryLine = summary.allClear;
  }

  return (
    <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1
          className="font-headline-lg text-text-primary"
          id="hermes-today-title"
        >
          {greeting}
        </h1>
        <p className="mt-1 font-body-sm text-text-secondary">
          {dateLine ? `${dateLine} · ` : ""}
          {summaryLine}
        </p>
      </div>
      <Link
        aria-label={copy.labels.openMorningBriefAria}
        className="app-touch-target inline-flex shrink-0 items-center gap-2 self-start rounded-lg border border-border-subtle px-3 font-body-sm text-text-secondary transition-colors hover:bg-bg-surface-muted hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info sm:self-auto"
        data-testid="hermes-today-brief-entry"
        href={localizePath("/brief", locale)}
        prefetch={false}
      >
        <Sunrise aria-hidden size={16} />
        <span>{copy.labels.openMorningBrief}</span>
        <span aria-hidden className="text-text-secondary/80">
          ›
        </span>
      </Link>
    </header>
  );
}
