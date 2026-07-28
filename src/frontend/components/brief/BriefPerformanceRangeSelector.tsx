import Link from "next/link";
import type { BriefPerformanceRange } from "@/lib/briefPerformance";
import { localizePath } from "@/lib/locale";

const ranges: BriefPerformanceRange[] = ["7d", "1m", "3m"];

export function BriefPerformanceRangeSelector({
  locale,
  selectedRange,
}: {
  locale: "en" | "zh";
  selectedRange: BriefPerformanceRange;
}) {
  const labels =
    locale === "zh"
      ? { "7d": "近 7 日", "1m": "近一月", "3m": "近三月" }
      : { "7d": "7 days", "1m": "1 month", "3m": "3 months" };

  return (
    <nav
      aria-label={locale === "zh" ? "收益曲线时间范围" : "Performance chart range"}
      className="flex flex-wrap items-center gap-1"
    >
      {ranges.map((range) => {
        const selected = range === selectedRange;
        return (
          <Link
            aria-current={selected ? "page" : undefined}
            className={
              selected
                ? "border border-editorial-accent bg-editorial-accent px-2.5 py-1.5 text-paper-ink"
                : "border border-editorial-rule px-2.5 py-1.5 text-ink-secondary transition-colors hover:border-ink hover:text-ink"
            }
            href={localizePath(`/brief?range=${range}`, locale)}
            key={range}
          >
            {labels[range]}
          </Link>
        );
      })}
    </nav>
  );
}
