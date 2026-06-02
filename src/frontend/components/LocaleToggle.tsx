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
        className={`inline-flex min-w-8 items-center justify-center whitespace-nowrap px-2.5 py-1 leading-none transition-colors ${
          active
            ? "bg-[#00C896] text-bg-base"
            : "text-zinc-400 hover:bg-zinc-900 hover:text-[#00C896]"
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
    <div className="inline-flex min-w-max shrink-0 overflow-hidden rounded border border-zinc-800 font-sans text-xs">
      {item("en", "EN")}
      {item("zh", "中文")}
    </div>
  );
}
