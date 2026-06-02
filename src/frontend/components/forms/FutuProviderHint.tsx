import type { Locale } from "@/lib/locale";

/**
 * Shared treatment for the `futu` provider option across run forms.
 *
 * When Futu OpenD is not reachable (from `/api/health` `futu_opend.reachable`),
 * picking `futu` makes the backend wait on the provider until the 180s client
 * timeout — which reads as a frozen UI to a beginner. We disable the option and
 * show a short hint so the user picks `sample`/`tiingo` instead.
 */

const hintCopy = {
  en: "Futu OpenD not detected — start OpenD or use sample / tiingo.",
  zh: "未检测到 Futu OpenD —— 请启动 OpenD，或改用 sample / tiingo。",
} as const;

export function futuOptionLabel(reachable: boolean, locale: Locale): string {
  if (reachable) {
    return "futu";
  }
  return locale === "zh" ? "futu（OpenD 未检测到）" : "futu (OpenD not detected)";
}

export function FutuUnavailableHint({
  reachable,
  locale,
}: {
  reachable: boolean;
  locale: Locale;
}) {
  if (reachable) {
    return null;
  }
  return (
    <span className="font-body-sm text-warning">{hintCopy[locale]}</span>
  );
}
