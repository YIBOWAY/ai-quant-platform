"use client";

import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { splitLocalePath } from "@/lib/locale";
import { HERMES_DEFAULT_LEDGERS } from "@/lib/hermes/defaultChrome";
import { useHermesDesk } from "./HermesDeskContext";
import "./hermes-desk.css";

export function HermesDeskFrame({ children }: { children: ReactNode }) {
  const { ledger, setLedger, locale, chatRailOpen, setChatRailOpen, isMobile } =
    useHermesDesk();
  const pathname = usePathname();
  const path = splitLocalePath(pathname).pathname;
  const onToday = path === "/hermes";
  const chatToggleRef = useRef<HTMLButtonElement>(null);
  const wasMobileChatOpen = useRef(false);
  const mobileDrawerOpen = onToday && isMobile && chatRailOpen;

  useEffect(() => {
    if (!onToday && chatRailOpen) setChatRailOpen(false);
  }, [chatRailOpen, onToday, setChatRailOpen]);

  useEffect(() => {
    let focusFrame = 0;
    if (mobileDrawerOpen) {
      focusFrame = window.requestAnimationFrame(() => {
        const closeButton = document.querySelector<HTMLButtonElement>(
          "#hermes-chat-rail .dp-chat-close",
        );
        closeButton?.focus();
      });
    } else if (onToday && isMobile && wasMobileChatOpen.current) {
      chatToggleRef.current?.focus();
    }
    wasMobileChatOpen.current = mobileDrawerOpen;
    return () => {
      window.cancelAnimationFrame(focusFrame);
    };
  }, [isMobile, mobileDrawerOpen, onToday]);

  const onLedgerKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const current = HERMES_DEFAULT_LEDGERS.findIndex((item) => item.id === ledger);
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? HERMES_DEFAULT_LEDGERS.length - 1
          : (current + (event.key === "ArrowRight" ? 1 : -1) + HERMES_DEFAULT_LEDGERS.length) %
            HERMES_DEFAULT_LEDGERS.length;
    const target = HERMES_DEFAULT_LEDGERS[next];
    setLedger(target.id);
    document.getElementById(`hermes-ledger-tab-${target.id}`)?.focus();
  };

  return (
    <div
      className="dp"
      data-theme="graphite"
      data-surface="hermes"
      data-hermes-desk="true"
      data-embedded="true"
      data-chat-workspace={onToday ? "true" : undefined}
    >
      {/* The top strip stays interactive while the drawer is open: on a phone
          its "返回今日" toggle sits above the overlay and is the way out. */}
      <header className="dp-topstrip">
        <div className="dp-sysline">
          <span>{locale === "zh" ? "个人量化工作台" : "Personal quant workspace"}</span>
        </div>
        {onToday ? (
          <div
            className="dp-subnav"
            role="tablist"
            aria-label={locale === "zh" ? "研究与运行" : "Research & simulation"}
          >
            {HERMES_DEFAULT_LEDGERS.map((item) => (
              <button
                aria-controls="hermes-ledger-panel"
                aria-selected={ledger === item.id}
                id={`hermes-ledger-tab-${item.id}`}
                key={item.id}
                role="tab"
                tabIndex={ledger === item.id ? 0 : -1}
                type="button"
                data-current={ledger === item.id ? "true" : undefined}
                onClick={() => setLedger(item.id)}
                onKeyDown={onLedgerKeyDown}
              >
                {locale === "zh" ? item.label : item.labelEn}
              </button>
            ))}
          </div>
        ) : null}
        {onToday ? (
          <button
            aria-controls="hermes-chat-rail"
            aria-expanded={chatRailOpen}
            className="dp-chat-toggle"
            onClick={() => setChatRailOpen(!chatRailOpen)}
            ref={chatToggleRef}
            type="button"
          >
            {chatRailOpen
              ? locale === "zh"
                ? "返回今日"
                : "Back to Today"
              : locale === "zh"
                ? "打开对话"
                : "Open chat"}
          </button>
        ) : null}
      </header>

      {onToday ? children : <div className="dp-main dp-scroll">{children}</div>}

      <footer
        aria-hidden={mobileDrawerOpen ? true : undefined}
        className="dp-footer"
        inert={mobileDrawerOpen ? true : undefined}
      >
        <span>
          {locale === "zh" ? "本机 Hermes · 模拟研究" : "Local Hermes · Paper research"}
        </span>
        <span className="grow" />
        <span>
          {locale === "zh"
            ? "实盘交易关闭"
            : "Live trading off"}
        </span>
      </footer>
    </div>
  );
}
