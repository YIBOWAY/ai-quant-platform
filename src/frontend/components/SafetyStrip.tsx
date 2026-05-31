import { ShieldAlert } from "lucide-react";
import { getHealth } from "@/lib/api";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    paperOnly: "paper-only",
    paperUnavailable: "paper mode unavailable",
    liveDisabled: "live trading disabled",
    liveEnabled: "live trading enabled",
    kill: "kill_switch",
    on: "on",
    off: "off",
    api: "api",
  },
  zh: {
    paperOnly: "仅模拟",
    paperUnavailable: "模拟模式不可用",
    liveDisabled: "实盘交易已禁用",
    liveEnabled: "实盘交易已启用",
    kill: "熔断开关",
    on: "开",
    off: "关",
    api: "接口",
  },
};

export async function SafetyStrip() {
  const [health, locale] = await Promise.all([getHealth(), getServerLocale()]);
  const text = copy[locale];
  const safety = health.safety;
  const paperOnly = Boolean(safety?.dry_run && safety?.paper_trading);
  const liveDisabled = safety?.live_trading_enabled === false;
  const killSwitchOn = safety?.kill_switch === true;

  return (
    <div className="fixed top-16 left-[240px] right-0 z-30 flex items-center justify-center px-4 h-[36px] border-b border-amber-900/50 bg-amber-950/20">
      <div className="flex items-center gap-2 text-amber-500 font-mono text-[10px] uppercase tracking-widest font-bold">
        <ShieldAlert size={14} className="text-amber-500" />
        <span>
          {paperOnly ? text.paperOnly : text.paperUnavailable} ·{" "}
          {liveDisabled ? text.liveDisabled : text.liveEnabled} · {text.kill}{" "}
          {killSwitchOn ? text.on : text.off} · {text.api} {health.status}
        </span>
      </div>
    </div>
  );
}
