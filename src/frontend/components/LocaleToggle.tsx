'use client';

import { usePathname, useSearchParams } from "next/navigation";
import { useLocale } from "@/components/LocaleProvider";
import { LOCALE_COOKIE, localizePath, type Locale } from "@/lib/locale";

export function LocaleToggle() {
  const locale = useLocale();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  function item(target: Locale, label: string) {
    const active = locale === target;
    const path = localizePath(pathname, target);
    const query = searchParams.toString();
    const href = query ? `${path}?${query}` : path;
    return (
      <a
        aria-label={target === "zh" ? "切换到中文" : "切换到英文"}
        className={`app-touch-target inline-flex items-center justify-center whitespace-nowrap rounded-md px-2.5 leading-none transition-colors ${
          active
            ? "bg-info/15 text-text-primary ring-1 ring-inset ring-info/45 shadow-[inset_0_-1px_0_rgba(94,162,255,0.45)]"
            : "text-text-secondary hover:bg-bg-surface hover:text-text-primary"
        }`}
        href={href}
        onClick={(event) => {
          event.preventDefault();
          document.cookie = `${LOCALE_COOKIE}=${target}; path=/; max-age=31536000; samesite=lax`;
          const hash = window.location.hash;
          window.location.assign(`${href}${hash}`);
        }}
      >
        {label}
      </a>
    );
  }

  return (
    <div className="inline-flex min-w-max shrink-0 gap-0.5 rounded-lg border border-border-subtle bg-bg-base p-0.5 font-data-mono text-xs shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]">
      {item("en", "EN")}
      {item("zh", "中文")}
    </div>
  );
}

/** Fixed-size non-interactive placeholder for Suspense while searchParams resolve. */
export function LocaleToggleFallback() {
  return (
    <div
      aria-hidden="true"
      className="inline-flex min-w-max shrink-0 gap-0.5 rounded-lg border border-border-subtle bg-bg-base p-0.5 font-data-mono text-xs shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]"
    >
      <span className="app-touch-target inline-flex items-center justify-center whitespace-nowrap rounded-md px-2.5 leading-none text-text-secondary opacity-50">
        EN
      </span>
      <span className="app-touch-target inline-flex items-center justify-center whitespace-nowrap rounded-md px-2.5 leading-none text-text-secondary opacity-50">
        中文
      </span>
    </div>
  );
}
