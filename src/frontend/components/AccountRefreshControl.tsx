'use client';

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw } from "lucide-react";

type Locale = "en" | "zh";

const copy = {
  en: { refresh: "Refresh", auto: "Auto", off: "off", every: "every 30s" },
  zh: { refresh: "刷新", auto: "自动", off: "关", every: "每 30 秒" },
} as const;

/**
 * Optional auto-refresh for the account-driven Position Map (redesign stage 5).
 * The page is a server component; this client control re-fetches it via
 * router.refresh(), either on demand or on a 30s interval. Read-only.
 */
export function AccountRefreshControl({ locale = "en" }: { locale?: Locale }) {
  const router = useRouter();
  const [auto, setAuto] = useState(false);
  const text = copy[locale];

  useEffect(() => {
    if (!auto) return;
    const id = window.setInterval(() => router.refresh(), 30_000);
    return () => window.clearInterval(id);
  }, [auto, router]);

  return (
    <div className="flex items-center gap-2">
      <button
        className="flex items-center gap-1 rounded-full border border-border-subtle bg-bg-surface-muted px-3 py-1.5 font-body-sm text-text-primary transition-colors hover:border-text-secondary/50 hover:bg-bg-surface"
        onClick={() => router.refresh()}
        type="button"
      >
        <RefreshCw size={14} /> {text.refresh}
      </button>
      <button
        className={`rounded-full border px-3 py-1.5 font-body-sm transition-colors ${
          auto
            ? "border-border-subtle bg-bg-surface-muted text-text-primary"
            : "border-border-subtle bg-bg-surface-muted text-text-secondary hover:border-text-secondary/50 hover:bg-bg-surface"
        }`}
        onClick={() => setAuto((v) => !v)}
        type="button"
      >
        {text.auto}: {auto ? text.every : text.off}
      </button>
    </div>
  );
}
