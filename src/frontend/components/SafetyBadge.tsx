import { ShieldAlert } from "lucide-react";
import {
  getCachedEffectivePaperSafety,
  getCachedSettings,
} from "@/lib/serverApi";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    paperOnly: "paper-only",
    paperUnavailable: "paper mode unavailable",
    liveDisabled: "live trading disabled",
    liveEnabled: "live trading enabled",
    kill: "global kill_switch",
    accountFrozen: "paper account frozen",
    paperAuthority: "paper authority",
    epoch: "epoch",
    ready: "ready",
    blocked: "blocked",
    on: "on",
    off: "off",
    api: "api",
    unavailable: "unavailable",
    badge: "PAPER-ONLY",
    badgeUnsafe: "CHECK SAFETY",
    details: "Safety details",
  },
  zh: {
    paperOnly: "仅模拟",
    paperUnavailable: "模拟模式不可用",
    liveDisabled: "实盘交易已禁用",
    liveEnabled: "实盘交易已启用",
    kill: "全局熔断开关",
    accountFrozen: "模拟账户冻结",
    paperAuthority: "论文安全权威",
    epoch: "纪元",
    ready: "就绪",
    blocked: "受阻",
    on: "开",
    off: "关",
    api: "接口",
    unavailable: "不可用",
    badge: "仅模拟",
    badgeUnsafe: "安全待查",
    details: "安全详情",
  },
};

export async function SafetyBadge() {
  const [settings, paperSafety, locale] = await Promise.all([
    getCachedSettings(),
    getCachedEffectivePaperSafety(),
    getServerLocale(),
  ]);
  const text = copy[locale];
  const health = {
    safety: settings.apiError ? undefined : settings.safety,
    status: settings.apiError || !settings.safety ? "unavailable" : "available",
  };
  const safety = health.safety;
  const paperOnly = Boolean(safety?.dry_run && safety?.paper_trading);
  const liveDisabled = safety?.live_trading_enabled === false;
  const killSwitchOn = safety?.kill_switch === true;
  const liveStatus = safety
    ? liveDisabled
      ? text.liveDisabled
      : text.liveEnabled
    : text.unavailable;
  const killStatus = safety ? (killSwitchOn ? text.on : text.off) : text.unavailable;
  const accountFrozenStatus = paperSafety.apiError
    ? text.unavailable
    : paperSafety.canonical_account_frozen === true
      ? text.on
      : paperSafety.canonical_account_frozen === false
        ? text.off
        : text.unavailable;
  const paperAuthorityStatus = paperSafety.apiError
    ? text.unavailable
    : paperSafety.effective
      ? text.ready
      : text.blocked;
  const epochStatus =
    paperSafety.current_paper_authority_epoch === null
      ? text.unavailable
      : String(paperSafety.current_paper_authority_epoch);
  const desktopStatus = `${paperOnly ? text.paperOnly : text.paperUnavailable} · ${
    liveStatus
  } · ${text.kill} ${killStatus} · ${text.accountFrozen} ${accountFrozenStatus} · ${
    text.paperAuthority
  } ${paperAuthorityStatus} (${text.epoch} ${epochStatus}) · ${text.api} ${health.status}`;
  const mobileStatus = `${paperOnly ? text.paperOnly : text.paperUnavailable} · ${
    liveStatus
  } · ${text.paperAuthority} ${paperAuthorityStatus} · ${text.api} ${health.status}`;

  // Fail closed: anything short of "paper-only, live disabled, authority ready,
  // API reachable" reads as an attention state, never as all-clear.
  const allSafe =
    paperOnly &&
    liveDisabled &&
    !killSwitchOn &&
    paperSafety.effective === true &&
    !paperSafety.apiError &&
    health.status === "available";
  const badgeLabel = allSafe ? text.badge : text.badgeUnsafe;
  const dotClass = allSafe ? "bg-accent-success" : "bg-warning";

  const rows: Array<{ label: string; value: string }> = [
    { label: text.paperOnly, value: paperOnly ? text.on : text.off },
    { label: liveStatus, value: liveDisabled ? text.on : text.off },
    { label: text.kill, value: killStatus },
    { label: text.accountFrozen, value: accountFrozenStatus },
    {
      label: text.paperAuthority,
      value: `${paperAuthorityStatus} (${text.epoch} ${epochStatus})`,
    },
    { label: text.api, value: health.status },
  ];

  return (
    <div
      aria-label={desktopStatus}
      className="relative shrink-0"
      data-global-safety-strip
      data-testid="global-safety-strip"
      role="status"
    >
      <details className="group">
        <summary
          aria-label={text.details}
          className="app-touch-target flex cursor-pointer list-none items-center gap-2 rounded-lg border border-warning/40 bg-warning/5 px-2.5 font-mono text-[10px] font-bold uppercase tracking-widest text-warning marker:hidden"
        >
          <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${dotClass}`} />
          <ShieldAlert size={13} className="shrink-0" />
          <span>{badgeLabel}</span>
        </summary>
        <div
          className="absolute right-0 top-[calc(100%+6px)] z-50 w-[min(320px,80vw)] rounded-[var(--radius-card)] bg-[var(--color-bg-overlay)] p-3 shadow-[var(--shadow-overlay)]"
        >
          <ul className="space-y-1.5 font-mono text-[11px] leading-relaxed text-text-primary">
            {rows.map((row) => (
              <li className="flex items-baseline justify-between gap-3" key={row.label}>
                <span className="min-w-0 truncate text-text-secondary">{row.label}</span>
                <span className="shrink-0 uppercase tracking-wide">{row.value}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 border-t border-border-subtle pt-2 font-mono text-[10px] leading-relaxed text-text-secondary">
            {mobileStatus}
          </p>
        </div>
      </details>
    </div>
  );
}
