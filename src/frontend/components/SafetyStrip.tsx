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
  },
};

export async function SafetyStrip() {
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

  return (
    <div
      aria-label={desktopStatus}
      className="fixed top-16 left-0 right-0 z-30 flex h-[36px] items-center justify-start overflow-hidden border-b border-amber-900/50 bg-amber-950/20 px-3 sm:justify-center lg:left-[240px]"
      data-global-safety-strip
      data-testid="global-safety-strip"
      role="status"
    >
      <div className="flex min-w-0 items-center gap-2 whitespace-nowrap font-mono text-[10px] font-bold uppercase tracking-widest text-amber-500">
        <ShieldAlert size={14} className="text-amber-500" />
        <span className="min-w-0 truncate sm:hidden">{mobileStatus}</span>
        <span className="hidden sm:inline">{desktopStatus}</span>
      </div>
    </div>
  );
}
