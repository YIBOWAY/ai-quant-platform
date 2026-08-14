"use client";

/**
 * Desk preview — 一次性视觉打样路由（现行计划 §9）。
 * 蓝图：2026-08-14 拍板的「桌面 blotter + 右栏 Hermes 会话」示意图。
 * 全部数据为预览态假数据；会话未接线；命令按钮只弹预览提示。
 */

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import {
  Activity,
  Beaker,
  Braces,
  Check,
  ChevronDown,
  Database,
  FileText,
  FlaskConical,
  Paperclip,
  PanelRightClose,
  PanelRightOpen,
  Send,
  Settings,
  Sun,
  Tag,
  Wrench,
  X,
} from "lucide-react";
import "./desk-preview.css";
import {
  CHAT_OPENING,
  LEDGER_EVENTS,
  PREVIEW_REPLY,
  STRATEGIES,
  type ChatMessage,
  type Strategy,
} from "./preview-data";

/* ------------------------------------------------------------------ utils */

type ThemeId = "warm" | "graphite" | "amber";

const THEMES: { id: ThemeId; label: string }[] = [
  { id: "graphite", label: "石墨" },
  { id: "warm", label: "暖岩" },
  { id: "amber", label: "琥珀" },
];

const DEFAULT_THEME: ThemeId = "graphite";

const THEME_KEY = "dp-theme";
const THEME_EVENT = "dp-theme-change";

function subscribeTheme(cb: () => void) {
  window.addEventListener(THEME_EVENT, cb);
  return () => window.removeEventListener(THEME_EVENT, cb);
}

function readTheme(): ThemeId {
  const v = window.localStorage.getItem(THEME_KEY) as ThemeId | null;
  return v && THEMES.some((t) => t.id === v) ? v : DEFAULT_THEME;
}

const serverTheme = (): ThemeId => DEFAULT_THEME;

function nowHHMM(): string {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function fmtUsd(v: number): string {
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}$${Math.abs(v).toFixed(2)}`;
}

function fmtPct(v: number): string {
  const sign = v > 0 ? "▲" : v < 0 ? "▼" : "";
  return `${sign}${Math.abs(v).toFixed(2)}%`;
}

/* -------------------------------------------------------------- sparkline */

function Sparkline({ days }: { days: number[] }) {
  if (days.length === 0) {
    return <span className="dp-spark-empty">— 暂无观察日</span>;
  }
  const w = 76;
  const h = 22;
  const pad = 2;
  // 累计收益路径：从 0 开始逐日累加
  const cum: number[] = [0];
  for (const d of days) cum.push(cum[cum.length - 1] + d);
  const min = Math.min(...cum);
  const max = Math.max(...cum);
  const span = Math.max(max - min, 0.0001);
  const stepX = (w - pad * 2) / (cum.length - 1);
  const y = (v: number) => pad + (max - v) * ((h - pad * 2) / span);
  const pts = cum.map((v, i) => `${(pad + i * stepX).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const net = cum[cum.length - 1];
  const zeroY = y(0);
  return (
    <svg className="dp-spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <line className="axis" x1={pad} y1={zeroY} x2={w - pad} y2={zeroY} strokeDasharray="2 3" strokeWidth="0.75" />
      <polyline className={net >= 0 ? "up" : "down"} points={pts} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

/* ---------------------------------------------------------------- receipt */

function ReceiptIcon({ kind }: { kind: "tool" | "dispatch" | "doc" }) {
  if (kind === "tool") return <Wrench aria-hidden="true" />;
  if (kind === "dispatch") return <Send aria-hidden="true" />;
  return <FileText aria-hidden="true" />;
}

function Message({ msg }: { msg: ChatMessage }) {
  return (
    <div className="dp-msg" data-role={msg.role}>
      <div className="head">
        <span className="who">{msg.role === "hermes" ? "Hermes" : "你"}</span>
        <span className="t dp-num">{msg.time}</span>
      </div>
      {msg.attachment ? (
        <span className="dp-attach">
          <FileText aria-hidden="true" />
          <span>{msg.attachment.name}</span>
          <span className="size dp-num">{msg.attachment.size}</span>
        </span>
      ) : null}
      {msg.receipts?.map((r, i) => (
        <div className="dp-receipt" key={i}>
          <ReceiptIcon kind={r.icon} />
          <div>
            <div className="rt">{r.title}</div>
            {r.sub ? <div className="rs">{r.sub}</div> : null}
          </div>
          <span className="state">
            <Check size={11} aria-hidden="true" />
            {r.status}
          </span>
        </div>
      ))}
      {msg.text ? <div className="body">{msg.text}</div> : null}
    </div>
  );
}

/* ------------------------------------------------------------------- page */

export default function DeskPreview() {
  const theme = useSyncExternalStore(subscribeTheme, readTheme, serverTheme);
  const [railOpen, setRailOpen] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>("sleeve-c42a91e");
  const [expandedId, setExpandedId] = useState<string | null>("sleeve-c42a91e");
  const [chip, setChip] = useState<Strategy | null>(STRATEGIES[0]);
  const [messages, setMessages] = useState<ChatMessage[]>(CHAT_OPENING);
  const [draft, setDraft] = useState("");
  const [toast, setToast] = useState<string | null>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const pickTheme = useCallback((t: ThemeId) => {
    window.localStorage.setItem(THEME_KEY, t);
    window.dispatchEvent(new Event(THEME_EVENT));
  }, []);

  const flash = useCallback((text: string) => {
    setToast(text);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 3200);
  }, []);

  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight });
  }, [messages, railOpen]);

  const selectRow = useCallback((s: Strategy) => {
    setSelectedId(s.id);
    setChip(s);
  }, []);

  const toggleExpand = useCallback((s: Strategy, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedId((cur) => (cur === s.id ? null : s.id));
  }, []);

  const sendDraft = useCallback(() => {
    const text = draft.trim();
    if (!text) return;
    const userMsg: ChatMessage = { id: `u-${Date.now()}`, role: "user", time: nowHHMM(), text };
    setMessages((m) => [...m, userMsg]);
    setDraft("");
    setTimeout(() => {
      const ctx = chip ? `（已附上下文：${chip.name}）` : "";
      setMessages((m) => [
        ...m,
        { id: `h-${Date.now()}`, role: "hermes", time: nowHHMM(), text: `${ctx}${PREVIEW_REPLY}` },
      ]);
    }, 550);
  }, [draft, chip]);

  const hungCount = STRATEGIES.filter((s) => s.status === "hung").length;
  const candidateCount = STRATEGIES.filter((s) => s.status === "candidate").length;

  return (
    <div className="dp" data-theme={theme}>
      {/* ---------------------------------------------------- icon rail */}
      <nav className="dp-iconrail" aria-label="主导航（预览态）">
        <div className="dp-logo" aria-hidden="true">
          H
        </div>
        {[
          { icon: Sun, label: "今日", current: true },
          { icon: FlaskConical, label: "研究" },
          { icon: Activity, label: "模拟" },
          { icon: Database, label: "数据" },
          { icon: Beaker, label: "实验室" },
        ].map(({ icon: Icon, label, current }) => (
          <button key={label} type="button" className="dp-navbtn" data-current={current ? "true" : undefined}>
            <Icon aria-hidden="true" />
            <span>{label}</span>
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <button type="button" className="dp-navbtn">
          <Settings aria-hidden="true" />
          <span>设置</span>
        </button>
      </nav>

      {/* ---------------------------------------------------- top strip */}
      <header className="dp-topstrip">
        <div className="dp-sysline">
          <span className="dp-dot" data-tone="ok" aria-hidden="true" />
          <span>仅模拟</span>
          <span className="sep">·</span>
          <span>实盘关闭</span>
          <span className="sep">·</span>
          <span className="dp-num">数据截至 08-14 09:31</span>
        </div>
        <span className="dp-previewtag">预览数据 · 非真实账户</span>
        <div style={{ flex: 1 }} />
        <span className="dp-kbd">⌘K</span>
        <button
          type="button"
          className="dp-btn"
          onClick={() => flash("预览态 · 派研究未接线：正式版从这里入队研究任务，默认停在已验证候选。")}
        >
          <FlaskConical aria-hidden="true" />
          派研究
        </button>
        <button
          type="button"
          className="dp-btn"
          data-variant="accent"
          onClick={() => flash("预览态 · 挂上未接线：正式版这里打开挂上确认，必须绑候选 digest。")}
        >
          <Tag aria-hidden="true" />
          挂上
        </button>
        <div className="dp-themeswitch" role="group" aria-label="主题切换">
          {THEMES.map((t) => (
            <button key={t.id} type="button" data-on={theme === t.id ? "true" : "false"} onClick={() => pickTheme(t.id)}>
              {t.label}
            </button>
          ))}
        </div>
        {!railOpen ? (
          <button type="button" className="dp-iconbtn" aria-label="展开 Hermes 会话栏" onClick={() => setRailOpen(true)}>
            <PanelRightOpen aria-hidden="true" />
          </button>
        ) : null}
      </header>

      {/* ---------------------------------------------------- main column */}
      <main className="dp-main dp-scroll">
        <section className="dp-hero">
          <div className="dp-hero-kicker">
            <span className="dp-caps">今日 · 2026-08-14 周五</span>
            <span className="dp-caps" style={{ color: "var(--dp-up)" }}>
              值班正常
            </span>
          </div>
          <h1 className="dp-hero-title">
            今早有 1 件事需要你：<span className="accent">20 日均线反转</span>
            已通过双引擎，等你决定挂不挂。
          </h1>
          <div className="dp-hero-sub">
            <span>
              昨夜观察日 <span className="dp-num">2</span> 条已挂策略完成
            </span>
            <span className="dp-delta dp-num" data-dir="up">
              横截面动量 {fmtPct(0.31)}
            </span>
            <span className="dp-delta dp-num" data-dir="down">
              均值回归 {fmtPct(-0.04)}
            </span>
            <span>数据源昨夜中断 47 分钟，已恢复</span>
            <a href="/zh/brief">
              查看晨报全文 <span aria-hidden="true">→</span>
            </a>
          </div>
        </section>

        {/* ------------------------------------------------------ blotter */}
        <div className="dp-sechead">
          <h2>策略状态</h2>
          <span className="count dp-num">
            已挂上 {hungCount} · 候选 {candidateCount} · 暂停 1
          </span>
        </div>
        <div className="dp-blotter">
          <table>
            <thead>
              <tr>
                <th style={{ width: 96 }}>状态</th>
                <th>策略</th>
                <th style={{ minWidth: 240 }}>一句话概括</th>
                <th style={{ width: 96 }}>近 7 观察日</th>
                <th>今日</th>
                <th className="num" style={{ width: 150 }}>
                  当日结果
                </th>
                <th style={{ width: 36 }} aria-label="展开" />
              </tr>
            </thead>
            <tbody>
              {STRATEGIES.map((s) => {
                const selected = selectedId === s.id;
                const expanded = expandedId === s.id;
                return (
                  <FragmentRow
                    key={s.id}
                    s={s}
                    selected={selected}
                    expanded={expanded}
                    onSelect={() => selectRow(s)}
                    onToggle={(e) => toggleExpand(s, e)}
                    onHang={(e) => {
                      e.stopPropagation();
                      flash("预览态 · 挂上未接线：正式版这里出确认卡，展示候选 digest 与宇宙。");
                    }}
                  />
                );
              })}
            </tbody>
          </table>
        </div>

        {/* ---------------------------------------------------- event log */}
        <div className="dp-sechead">
          <h2>最新事件</h2>
          <span className="count dp-num">{LEDGER_EVENTS.length} 条 · 值班账</span>
        </div>
        <div className="dp-eventlog">
          <table>
            <tbody>
              {LEDGER_EVENTS.map((e, i) => (
                <tr key={i}>
                  <td className="dp-num" style={{ width: 92, color: "var(--dp-text-faint)", fontSize: 11 }}>
                    {e.time}
                  </td>
                  <td style={{ width: 56 }}>
                    <span className="dp-lvl" data-lvl={e.level}>
                      {e.level}
                    </span>
                  </td>
                  <td style={{ width: 132, color: "var(--dp-text-dim)", fontSize: 11.5 }}>{e.source}</td>
                  <td style={{ whiteSpace: "normal" }}>{e.text}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>

      {/* ---------------------------------------------------- chat rail */}
      <aside className="dp-rail" data-open={railOpen ? "true" : "false"} aria-label="Hermes 会话（预览态）">
        {railOpen ? (
          <>
            <div className="dp-rail-head">
              <span className="title">Hermes</span>
              <span className="dp-live">
                <span className="dp-dot" data-tone="ok" aria-hidden="true" />
                已连接
              </span>
              <span className="meta">local-2026-08-14</span>
              <div style={{ flex: 1 }} />
              <button type="button" className="dp-iconbtn" aria-label="收起会话栏" onClick={() => setRailOpen(false)}>
                <PanelRightClose aria-hidden="true" />
              </button>
            </div>
            <div className="dp-transcript dp-scroll" ref={transcriptRef}>
              {messages.map((m) => (
                <Message key={m.id} msg={m} />
              ))}
            </div>
            {chip ? (
              <div className="dp-chipline">
                <span className="dp-chip">
                  <span>下一轮附加</span>
                  <span className="name">{chip.name}</span>
                  <button type="button" aria-label="移除上下文" onClick={() => setChip(null)}>
                    <X aria-hidden="true" />
                  </button>
                </span>
              </div>
            ) : null}
            <div className="dp-composer">
              <div className="dp-composer-box">
                <textarea
                  rows={2}
                  placeholder="向 Hermes 发送消息…（自由输入，模型自选工具）"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                      e.preventDefault();
                      sendDraft();
                    }
                  }}
                />
                <div className="dp-composer-tools">
                  <button type="button" className="dp-iconbtn" aria-label="附件（预览态）">
                    <Paperclip aria-hidden="true" />
                  </button>
                  <button type="button" className="dp-iconbtn" aria-label="结构化输入（预览态）">
                    <Braces aria-hidden="true" />
                  </button>
                  <button type="button" className="dp-send" aria-label="发送" disabled={!draft.trim()} onClick={sendDraft}>
                    <Send aria-hidden="true" />
                  </button>
                </div>
              </div>
              <div className="dp-composer-hint">
                <span>⌘⏎ 发送</span>
                <span>·</span>
                <span>本地 owner 会话 · 公开 composer 关</span>
              </div>
            </div>
          </>
        ) : (
          <div className="dp-rail-collapsed">
            <button type="button" className="dp-iconbtn" aria-label="展开 Hermes 会话栏" onClick={() => setRailOpen(true)}>
              <PanelRightOpen aria-hidden="true" />
            </button>
          </div>
        )}
      </aside>

      {/* ---------------------------------------------------- footer */}
      <footer className="dp-footer">
        <span>预览数据 · 假观察日仅供视觉打样</span>
        <span className="grow" />
        <span>live_trading=false · kill_switch=true（冻实盘）</span>
        <span>UTC+8</span>
      </footer>

      {toast ? (
        <div className="dp-toast" role="status">
          {toast}
        </div>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------- table rows */

function FragmentRow({
  s,
  selected,
  expanded,
  onSelect,
  onToggle,
  onHang,
}: {
  s: Strategy;
  selected: boolean;
  expanded: boolean;
  onSelect: () => void;
  onToggle: (e: React.MouseEvent) => void;
  onHang: (e: React.MouseEvent) => void;
}) {
  const dim = s.status === "paused";
  return (
    <>
      <tr className="dp-row" data-selected={selected ? "true" : "false"} data-dim={dim ? "true" : undefined} onClick={onSelect}>
        <td>
          <span className="dp-status" data-kind={s.status}>
            {s.status === "hung" ? "已挂上" : s.status === "candidate" ? "未挂上" : "已暂停"}
          </span>
        </td>
        <td>
          <div className="dp-strat-name">{s.name}</div>
          <div className="dp-strat-sub">
            {s.universe} · {s.statusNote}
          </div>
        </td>
        <td className="wrap">
          <div className="dp-summary">{s.summary}</div>
        </td>
        <td>
          <Sparkline days={s.obsDays} />
        </td>
        <td style={{ color: "var(--dp-text-dim)", fontSize: 12 }}>
          {s.status === "candidate" ? (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
              {s.todayNote}
              <button type="button" className="dp-hangbtn" onClick={onHang}>
                <Tag size={11} aria-hidden="true" />
                挂上
              </button>
            </span>
          ) : (
            s.todayNote
          )}
        </td>
        <td className="num">
          {s.todayPnlUsd == null ? (
            <span className="dp-delta dp-num" data-dir="flat">
              —
            </span>
          ) : (
            <span className="dp-delta dp-num" data-dir={s.todayPnlUsd > 0 ? "up" : s.todayPnlUsd < 0 ? "down" : "flat"}>
              {fmtUsd(s.todayPnlUsd)}
              <span className="pct">{fmtPct(s.todayPnlPct ?? 0)}</span>
            </span>
          )}
        </td>
        <td>
          <button
            type="button"
            className="dp-iconbtn"
            aria-label={expanded ? "收起事件" : "展开事件"}
            aria-expanded={expanded}
            onClick={onToggle}
            style={{ width: 24, height: 24 }}
          >
            <ChevronDown
              aria-hidden="true"
              style={{
                transform: expanded ? "rotate(180deg)" : "none",
                transitionProperty: "transform",
                transitionDuration: "140ms",
                transitionTimingFunction: "ease-out",
              }}
            />
          </button>
        </td>
      </tr>
      {expanded ? (
        <tr className="dp-rowdetail">
          <td colSpan={7}>
            <div className="dp-eventstrip">
              {s.events.map((ev, i) => (
                <span className="ev" key={i}>
                  <span className="t dp-num">{ev.time}</span>
                  <span className="l">{ev.label}</span>
                  {ev.detail ? <span className="d">{ev.detail}</span> : null}
                </span>
              ))}
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}
