"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  Beaker,
  Database,
  FlaskConical,
  Settings,
  Sun,
} from "lucide-react";
import { useLocale } from "@/components/LocaleProvider";
import { localizePath, splitLocalePath } from "@/lib/locale";
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

  const rail = [
    {
      id: "duty" as const,
      icon: Sun,
      label: "值班",
      href: hermesRouteHref("today", locale),
      current: onToday && ledger === "duty",
      onClick: onToday ? () => setLedger("duty") : undefined,
    },
    {
      id: "research" as const,
      icon: FlaskConical,
      label: "研究",
      href: hermesRouteHref("today", locale),
      current: onToday && ledger === "research",
      onClick: onToday ? () => setLedger("research") : undefined,
    },
    {
      id: "paper" as const,
      icon: Activity,
      label: "模拟",
      href: localizePath("/paper-trading", locale),
      current: path.startsWith("/paper-trading") || (onToday && ledger === "paper"),
      onClick: onToday ? () => setLedger("paper") : undefined,
    },
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
    <div className="dp" data-theme="graphite" data-hermes-desk="true">
      <nav className="dp-iconrail" aria-label="三本账">
        <div className="dp-logo" aria-hidden="true">
          H
        </div>
        {rail.map((item) =>
          item.onClick ? (
            <button
              key={item.id}
              type="button"
              className="dp-navbtn"
              data-current={item.current ? "true" : undefined}
              onClick={item.onClick}
            >
              <item.icon aria-hidden="true" />
              <span>{item.label}</span>
            </button>
          ) : (
            <Link
              key={item.id}
              className="dp-navbtn"
              href={item.href}
              data-current={item.current ? "true" : undefined}
            >
              <item.icon aria-hidden="true" />
              <span>{item.label}</span>
            </Link>
          ),
        )}
        <Link className="dp-navbtn" href={localizePath("/data-explorer", locale)}>
          <Database aria-hidden="true" />
          <span>数据</span>
        </Link>
        <Link className="dp-navbtn" href={localizePath("/factor-lab", locale)}>
          <Beaker aria-hidden="true" />
          <span>实验室</span>
        </Link>
        <div style={{ flex: 1 }} />
        <Link className="dp-navbtn" href={localizePath("/settings", locale)}>
          <Settings aria-hidden="true" />
          <span>设置</span>
        </Link>
      </nav>

      <header className="dp-topstrip">
        <div className="dp-sysline">
          <span className="dp-dot" data-tone="ok" aria-hidden="true" />
          <span>仅模拟</span>
          <span className="sep">·</span>
          <span>实盘关闭</span>
          <span className="sep">·</span>
          <span className="dp-num">live_trading=false</span>
        </div>
        <span className="dp-previewtag">Hermes · 正式账</span>
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
        <div style={{ flex: 1 }} />
        <Link className="dp-btn" href={localizePath("/brief", locale)}>
          晨报
        </Link>
        <Link className="dp-btn" href={localizePath("/paper-trading", locale)}>
          模拟深页
        </Link>
      </header>

      {onToday ? (
        children
      ) : (
        <div className="dp-main dp-scroll">{children}</div>
      )}

      <footer className="dp-footer">
        <span>Hermes 工作台 · 远程账接线 · 不是额外的今日桌面</span>
        <span className="grow" />
        <span>live_trading=false · 种子市值差不是策略盈亏</span>
      </footer>
    </div>
  );
}
