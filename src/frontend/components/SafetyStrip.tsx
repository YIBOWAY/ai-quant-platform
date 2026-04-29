import { ShieldAlert } from "lucide-react";
import { getHealth } from "@/lib/api";

export async function SafetyStrip() {
  const health = await getHealth();
  const safety = health.safety;
  const connected = health.status === "ok";

  return (
    <div className="fixed top-16 left-[240px] right-0 z-30 flex items-center justify-center px-4 h-[36px] border-b border-amber-900/50 bg-amber-950/20">
      <div className="flex items-center gap-2 text-amber-500 font-mono text-[10px] uppercase tracking-widest font-bold">
        <ShieldAlert size={14} className="text-amber-500" />
        <span>
          {connected ? "API CONNECTED" : "API OFFLINE"} / PAPER-ONLY / LIVE TRADING{" "}
          {safety?.live_trading_enabled ? "ENABLED" : "DISABLED"} / KILL SWITCH{" "}
          {safety?.kill_switch ? "ON" : "OFF"}
        </span>
      </div>
    </div>
  );
}
