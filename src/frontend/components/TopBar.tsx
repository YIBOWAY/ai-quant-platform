'use client';

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bell, Terminal, Power, Search } from "lucide-react";

export function TopBar() {
  const pathname = usePathname();

  const topNavItems = [
    { name: "Market Data", href: "/data-explorer" },
    { name: "Order Book", href: "/order-book" },
    { name: "Position Map", href: "/position-map" },
  ];

  return (
    <header className="fixed top-0 left-[240px] right-0 z-40 px-6 flex items-center justify-between h-16 border-b border-zinc-800 bg-zinc-950/80 backdrop-blur-md">
      <div className="flex items-center gap-8 h-full w-full">
        <div className="relative hidden md:flex items-center">
          <Search className="absolute left-3 text-zinc-500" size={16} />
          <input
            className="bg-zinc-900 border border-zinc-800 text-text-primary rounded pl-9 pr-4 py-1.5 text-sm w-64 focus:outline-none focus:border-info focus:ring-1 focus:ring-info placeholder-zinc-500 font-sans"
            placeholder="Search factors, symbols..."
            type="text"
          />
        </div>
        <nav className="flex items-center gap-6 h-full flex-1">
          {topNavItems.map((item) => {
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`transition-colors font-sans text-sm cursor-pointer h-full flex items-center border-b-2 ${
                  isActive
                    ? "text-[#00C896] border-[#00C896]"
                    : "text-zinc-400 hover:text-zinc-100 border-transparent"
                }`}
              >
                {item.name}
              </Link>
            );
          })}
        </nav>
      </div>

      <div className="flex items-center gap-4">
        <button className="px-4 py-1.5 bg-[#00C896]/10 border border-[#00C896]/30 text-[#00C896] rounded hover:bg-[#00C896]/20 transition-colors font-label-caps uppercase text-xs font-bold whitespace-nowrap">
          Deploy Alpha
        </button>
        <div className="flex items-center gap-2 border-l border-zinc-800 pl-4 text-zinc-400">
          <button className="hover:text-[#00C896] transition-colors cursor-pointer w-8 h-8 flex items-center justify-center rounded hover:bg-zinc-900">
            <Bell size={18} />
          </button>
          <button className="hover:text-[#00C896] transition-colors cursor-pointer w-8 h-8 flex items-center justify-center rounded hover:bg-zinc-900">
            <Terminal size={18} />
          </button>
          <button className="hover:text-[#00C896] transition-colors cursor-pointer w-8 h-8 flex items-center justify-center rounded hover:bg-zinc-900">
            <Power size={18} />
          </button>
        </div>
      </div>
    </header>
  );
}
