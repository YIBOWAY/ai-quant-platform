'use client';

import { usePathname } from "next/navigation";
import { useLocale } from "@/components/LocaleProvider";
import { LOCALE_COOKIE, localizePath, type Locale } from "@/lib/locale";

export function LocaleToggle() {
  const locale = useLocale();
  const pathname = usePathname();

  function item(target: Locale, label: string) {
    const active = locale === target;
    const href = localizePath(pathname, target);
    return (
      <a
        aria-label={target === "zh" ? "切换到中文" : "切换到英文"}
        className={`inline-flex min-w-10 items-center justify-center whitespace-nowrap rounded-md px-2.5 py-1 leading-none transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info ${
          active
            ? "bg-info/15 text-text-primary ring-1 ring-inset ring-info/45 shadow-[inset_0_-1px_0_rgba(94,162,255,0.45)]"
            : "text-text-secondary hover:bg-bg-surface hover:text-text-primary"
        }`}
        href={href}
        onClick={(event) => {
          event.preventDefault();
          document.cookie = `${LOCALE_COOKIE}=${target}; path=/; max-age=31536000; samesite=lax`;
          window.location.assign(href);
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
