'use client';

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Zap,
  LineChart,
  FlaskConical,
  Wallet,
  Settings,
  Database,
  BookOpen,
  Map,
  FileText,
  HelpCircle,
  User,
  Plus
} from "lucide-react";

export function Sidebar() {
  const pathname = usePathname();

  const navItems = [
    { name: "Dashboard", href: "/", icon: LayoutDashboard },
    { name: "Data Explorer", href: "/data-explorer", icon: Database },
    { name: "Factor Lab", href: "/factor-lab", icon: FlaskConical },
    { name: "Backtester", href: "/backtest", icon: LineChart },
    { name: "Experiments", href: "/experiments", icon: FlaskConical },
    { name: "Paper Trading", href: "/paper-trading", icon: Wallet },
    { name: "Agent Studio", href: "/agent-studio", icon: Zap },
    { name: "Order Book", href: "/order-book", icon: BookOpen },
    { name: "Position Map", href: "/position-map", icon: Map },
    { name: "Settings", href: "/settings", icon: Settings },
  ];

  return (
    <nav className="fixed left-0 top-0 flex flex-col h-full w-[240px] border-r border-zinc-800 bg-zinc-950 z-50">
      <div className="p-6 border-b border-zinc-800">
        <div className="font-mono font-black text-lg tracking-tighter text-[#00C896] uppercase mb-1">
          QUANTUM_CORE
        </div>
        <div className="font-sans text-xs tracking-tight text-text-secondary">
          Local Instance v2.4
        </div>
      </div>

      <div className="p-4 border-b border-zinc-800">
        <button className="w-full py-2 border border-[#00C896] text-[#00C896] rounded font-label-caps hover:bg-[#00C896]/10 transition-colors flex items-center justify-center gap-2">
          <Plus size={16} />
          <span>New Strategy</span>
        </button>
      </div>

      <div className="flex-1 py-4 overflow-y-auto">
        <ul className="space-y-1 px-3">
          {navItems.map((item) => {
            const isActive = pathname === item.href;
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={`flex items-center gap-3 px-3 py-2 rounded font-sans text-xs tracking-tight transition-colors ${
                    isActive
                      ? "bg-zinc-900 text-[#00C896] border-l-2 border-[#00C896] font-semibold"
                      : "text-zinc-500 hover:bg-zinc-900 hover:text-zinc-200 border-l-2 border-transparent"
                  }`}
                >
                  <item.icon size={18} />
                  <span>{item.name}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </div>

      <div className="px-3 py-4 border-t border-zinc-800">
        <ul className="space-y-1">
          <li>
            <Link
              href="#"
              className="flex items-center gap-3 px-3 py-1.5 rounded text-zinc-500 hover:bg-zinc-900 hover:text-zinc-200 transition-colors font-sans text-xs tracking-tight"
            >
              <FileText size={16} />
              <span>Docs</span>
            </Link>
          </li>
          <li>
            <Link
              href="#"
              className="flex items-center gap-3 px-3 py-1.5 rounded text-zinc-500 hover:bg-zinc-900 hover:text-zinc-200 transition-colors font-sans text-xs tracking-tight"
            >
              <HelpCircle size={16} />
              <span>Support</span>
            </Link>
          </li>
        </ul>
      </div>

      <div className="p-4 border-t border-zinc-800 flex items-center gap-3">
        <div className="w-8 h-8 rounded-full bg-surface-muted border border-border-subtle overflow-hidden flex items-center justify-center">
          <User size={18} className="text-text-secondary" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-sans text-xs font-medium text-text-primary truncate">
            Quant Researcher
          </div>
          <div className="font-sans text-[10px] text-text-secondary truncate">
            ID: QR-9921
          </div>
        </div>
      </div>
    </nav>
  );
}
