import type { Locale } from "@/lib/locale";
import { artifactCopy } from "./copy";

export function TechnicalDetails({
  locale,
  children,
  open = false,
  summary,
  id,
}: {
  locale: Locale;
  children: React.ReactNode;
  open?: boolean;
  summary?: string;
  /** Optional anchor id (e.g. status-line "system status" link target). */
  id?: string;
}) {
  const text = artifactCopy(locale);
  return (
    <details
      className="mt-3 rounded-lg border border-border-subtle bg-bg-base px-3 py-2 [overflow-anchor:none]"
      id={id}
      open={open}
    >
      <summary className="app-touch-target flex cursor-pointer list-none items-center font-body-sm font-semibold text-text-secondary">
        {summary ?? text.technicalDetails}
      </summary>
      <div className="mt-2 space-y-2 [overflow-anchor:none]">{children}</div>
    </details>
  );
}
