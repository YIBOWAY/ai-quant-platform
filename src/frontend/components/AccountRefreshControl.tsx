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
        className="flex items-center gap-1 rounded-lg border border-border-subtle px-3 py-2 font-body-sm text-text-primary"
        onClick={() => router.refresh()}
        type="button"
      >
        <RefreshCw size={14} /> {text.refresh}
      </button>
      <button
        className={`rounded-lg border px-3 py-2 font-body-sm ${
          auto
            ? "border-accent-success bg-accent-success/10 text-accent-success"
            : "border-border-subtle text-text-secondary"
        }`}
        onClick={() => setAuto((v) => !v)}
        type="button"
      >
        {text.auto}: {auto ? text.every : text.off}
      </button>
    </div>
  );
}
