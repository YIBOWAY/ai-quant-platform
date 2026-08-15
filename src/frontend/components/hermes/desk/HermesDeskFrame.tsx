"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLocale } from "@/components/LocaleProvider";
import { splitLocalePath } from "@/lib/locale";
import { hermesRouteHref } from "@/lib/hermes/routes";
import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import { useHermesDesk } from "./HermesDeskContext";
import "./hermes-desk.css";

export function HermesDeskFrame({ children }: { children: ReactNode }) {
  const { ledger, setLedger } = useHermesDesk();
  const locale = useLocale();
  const pathname = usePathname();
  const path = splitLocalePath(pathname).pathname;
  const onToday = path === "/hermes";
  const copy = hermesWorkbenchCopy(locale);

  const ledgers = [
    { id: "duty" as const, label: "值班" },
    { id: "research" as const, label: "研究" },
    { id: "paper" as const, label: "模拟" },
  ];

  const sub = [
    { href: hermesRouteHref("today", locale), label: copy.nav.today, current: onToday },
    {
      href: hermesRouteHref("sessions", locale),
      label: copy.nav.sessions,
      current: path.startsWith("/hermes/sessions"),
    },
    {
      href: hermesRouteHref("tasks", locale),
      label: copy.nav.tasks,
      current: path.startsWith("/hermes/tasks"),
    },
    {
      href: hermesRouteHref("approvals", locale),
      label: copy.nav.approvals,
      current: path.startsWith("/hermes/approvals"),
    },
    {
      href: hermesRouteHref("results", locale),
      label: copy.nav.results,
      current: path.startsWith("/hermes/results"),
    },
  ];

  return (
    <div className="dp" data-theme="graphite" data-hermes-desk="true" data-embedded="true">
      <header className="dp-topstrip">
        <div className="dp-sysline">
          <span className="dp-dot" data-tone="ok" aria-hidden="true" />
          <span>仅模拟</span>
          <span className="sep">·</span>
          <span>实盘关闭</span>
          <span className="sep">·</span>
          <span className="dp-num">live_trading=false</span>
        </div>
        {onToday ? (
          <div className="dp-subnav" role="tablist" aria-label="三本账">
            {ledgers.map((item) => (
              <button
                key={item.id}
                type="button"
                data-current={ledger === item.id ? "true" : undefined}
                onClick={() => setLedger(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>
        ) : null}
        <nav className="dp-subnav" aria-label={copy.nav.landmark}>
          {sub.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              data-current={item.current ? "true" : undefined}
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </header>

      {onToday ? children : <div className="dp-main dp-scroll">{children}</div>}

      <footer className="dp-footer">
        <span>Hermes 工作台 · 远程账接线</span>
        <span className="grow" />
        <span>live_trading=false · 种子市值差不是策略盈亏</span>
      </footer>
    </div>
  );
}
