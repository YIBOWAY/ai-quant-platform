'use client';

import { Languages } from "lucide-react";
import { LOCALE_COOKIE } from "@/lib/locale";
import { useLocale } from "@/components/LocaleProvider";

export function LocaleToggle() {
  const locale = useLocale();
  const next = locale === "zh" ? "en" : "zh";

  function switchTo() {
    document.cookie = `${LOCALE_COOKIE}=${next}; path=/; max-age=31536000; samesite=lax`;
    // Drop any per-page ?lang override so the cookie choice takes effect everywhere.
    const url = new URL(window.location.href);
    url.searchParams.delete("lang");
    window.location.replace(url.toString());
  }

  return (
    <button
      aria-label={locale === "zh" ? "切换到英文" : "Switch to Chinese"}
      className="flex items-center gap-1.5 rounded border border-zinc-800 px-2.5 py-1.5 font-sans text-xs text-zinc-300 transition-colors hover:border-[#00C896] hover:text-[#00C896]"
      onClick={switchTo}
      type="button"
    >
      <Languages size={14} />
      <span>{locale === "zh" ? "EN" : "中文"}</span>
    </button>
  );
}
