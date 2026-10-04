"use client";

import { Sparkles } from "lucide-react";
import {
  useRef,
  useState,
  useEffect,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { ComposerSubmitController } from "@/components/hermes/ComposerSubmitController";
import { HermesCapabilityNotice } from "@/components/hermes/shell/HermesCapabilityNotice";
import { WorkbenchTranscriptPanel } from "@/components/hermes/transcript/WorkbenchTranscriptPanel";
import { apiRequest, apiRequestOnce } from "@/lib/apiClient";
import { useOptionalActiveHermesSession } from "@/lib/hermes/activeSession";
import {
  activityStageLabel,
  activityToolLabel,
  activityTransportLabel,
  isInFlightCommandState,
  selectChatCommand,
  type WorkspaceRunActivity,
} from "@/lib/hermes/commandActivity";
import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import {
  ownerGetJson,
  PLATFORM_WORKSPACE_ID,
} from "@/lib/hermes/workspaceClient";
import { useWorkspaceFollow } from "@/lib/hermes/workspaceFollowContext";
import { localizePath } from "@/lib/locale";
import { useHermesDesk } from "./HermesDeskContext";
import {
  PlatformResearchResultCard,
  selectPlatformResearchResult,
} from "./PlatformResearchResultCard";

type RemoteBook = {
  requests?: unknown[];
};

type HermesSessionSummary = {
  id: string;
  title?: string | null;
  preview?: string | null;
  message_count?: number | null;
};

type HermesSessions = {
  read_status: "available" | "unavailable";
  sessions: HermesSessionSummary[];
};

const MIN_RAIL_WIDTH = 320;
const MAX_RAIL_WIDTH = 860;
const DEFAULT_RAIL_WIDTH = 620;
const RAIL_KEYBOARD_STEP = 32;

function clampRailWidth(value: number, maximum = MAX_RAIL_WIDTH): number {
  return Math.min(MAX_RAIL_WIDTH, maximum, Math.max(MIN_RAIL_WIDTH, value));
}

/**
 * One conversation column: transcript + a single free-text composer.
 * This is the only chat surface on /hermes. The page-bottom dock stays off.
 */
export function HermesDeskChatRail() {
  const { chatOpen, chatRailOpen, setChatRailOpen, isMobile, locale, deliveryState } =
    useHermesDesk();
  const copy = hermesWorkbenchCopy(locale);
  const isZh = locale === "zh";
  const session = useOptionalActiveHermesSession();
  const [railWidth, setRailWidth] = useState(DEFAULT_RAIL_WIDTH);
  const [railMaximum, setRailMaximum] = useState(MAX_RAIL_WIDTH);
  useEffect(() => {
    const sync = () => {
      const maximum = Math.max(MIN_RAIL_WIDTH, Math.min(MAX_RAIL_WIDTH, window.innerWidth * 0.53));
      setRailMaximum(maximum);
      setRailWidth((width) => clampRailWidth(width, maximum));
    };
    sync();
    window.addEventListener("resize", sync);
    return () => window.removeEventListener("resize", sync);
  }, []);
  const activeHermesSessionId = session?.hermesSessionId ?? null;
  const { state: followState } = useWorkspaceFollow();
  const currentCommand = selectChatCommand(
    followState.commands,
    activeHermesSessionId,
  );
  const activityActive = Boolean(
    currentCommand && isInFlightCommandState(currentCommand.state),
  );
  const activityQuery = useQuery({
    queryKey: ["hermes-run-activity", currentCommand?.command_id],
    queryFn: ({ signal }) =>
      ownerGetJson<WorkspaceRunActivity>(
        `/api/workspace/${encodeURIComponent(PLATFORM_WORKSPACE_ID)}/commands/${encodeURIComponent(currentCommand!.command_id)}/activity`,
        signal,
      ),
    enabled: Boolean(
      currentCommand?.command_id &&
        currentCommand.hermes_run_id &&
        activityActive &&
        (!isMobile || chatRailOpen),
    ),
    refetchInterval: (query) =>
      (query.state.data as WorkspaceRunActivity | undefined)?.terminal ? false : 2_000,
    retry: false,
  });
  const remoteBookQuery = useQuery({
    queryKey: ["assistant-remote-book"],
    queryFn: () => apiRequestOnce<RemoteBook>("/api/assistant/remote/book"),
    enabled: Boolean(activeHermesSessionId),
    refetchInterval: 15_000,
    retry: false,
  });
  const sessionsQuery = useQuery({
    queryKey: ["hermes-sessions", 12],
    queryFn: () =>
      apiRequest<HermesSessions>("/api/hermes/sessions?limit=12&offset=0"),
    refetchInterval: 30_000,
  });
  const connectionState = chatOpen ? "ready" : sessionsQuery.isError ? "unavailable" : sessionsQuery.data?.read_status === "available" ? "read_only" : sessionsQuery.isPending ? "loading" : "unavailable";
  const platformResearchResult = selectPlatformResearchResult(
    remoteBookQuery.data?.requests ?? [],
    activeHermesSessionId,
  );
  const activity = activityQuery.data;
  const activityStage = activityStageLabel(
    activity?.stage,
    currentCommand?.state,
    isZh,
  );
  const activityTime = activity?.last_activity_at
    ? new Date(activity.last_activity_at * 1_000)
    : currentCommand?.updated_at
      ? new Date(currentCommand.updated_at)
      : null;
  const activityTimeValid = activityTime && !Number.isNaN(activityTime.getTime());
  const activityTimeLabel = activityTimeValid
    ? activityTime.toLocaleTimeString(isZh ? "zh-CN" : "en-US", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : null;
  const hasThread = Boolean(
    session?.hermesSessionId || session?.pendingUserText,
  );
  const railRef = useRef<HTMLElement>(null);
  const dragRef = useRef<{ clientX: number; width: number } | null>(null);
  const pendingRailWidthRef = useRef(railWidth);
  const mobileDrawerOpen = isMobile && chatRailOpen;
  const mobileDrawerClosed = isMobile && !chatRailOpen;
  const recentSessions = (sessionsQuery.data?.sessions ?? []).filter(
    (item) =>
      Boolean(item.title?.trim() || item.preview?.trim()) ||
      (item.message_count ?? 0) > 0,
  );
  const showActivity = Boolean(
    currentCommand &&
      (activityActive || currentCommand.state !== "succeeded"),
  );

  const onResizePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (isMobile) return;
    dragRef.current = {
      clientX: event.clientX,
      width: railRef.current?.getBoundingClientRect().width ?? railWidth,
    };
    pendingRailWidthRef.current = dragRef.current.width;
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onResizePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragRef.current || isMobile) return;
    const width = clampRailWidth(
      dragRef.current.width + event.clientX - dragRef.current.clientX,
      railMaximum,
    );
    pendingRailWidthRef.current = width;
    railRef.current?.style.setProperty("--dp-rail-chat", `${width}px`);
    event.currentTarget.setAttribute("aria-valuenow", String(Math.round(width)));
  };

  const stopResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (dragRef.current) {
      setRailWidth(pendingRailWidthRef.current);
    }
    dragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const onResizeKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const width = railRef.current?.getBoundingClientRect().width ?? railWidth;
    const maximum = clampRailWidth(window.innerWidth * 0.53);
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      setRailWidth(clampRailWidth(width - RAIL_KEYBOARD_STEP, maximum));
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      setRailWidth(clampRailWidth(width + RAIL_KEYBOARD_STEP, maximum));
    } else if (event.key === "Home") {
      event.preventDefault();
      setRailWidth(MIN_RAIL_WIDTH);
    } else if (event.key === "End") {
      event.preventDefault();
      setRailWidth(maximum);
    }
  };

  const onDrawerKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (!mobileDrawerOpen) return;
    if (event.key === "Escape") {
      event.preventDefault();
      setChatRailOpen(false);
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(
      railRef.current?.querySelectorAll<HTMLElement>(
        'a[href],button:not([disabled]),input:not([disabled]),textarea:not([disabled]),summary,[tabindex]:not([tabindex="-1"])',
      ) ?? [],
    ).filter((item) => item.getClientRects().length > 0);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <aside
      aria-hidden={mobileDrawerClosed ? true : undefined}
      aria-label={isZh ? "对话" : "Chat"}
      aria-modal={mobileDrawerOpen ? true : undefined}
      className="dp-rail"
      data-open={chatRailOpen ? "true" : "false"}
      id="hermes-chat-rail"
      inert={mobileDrawerClosed ? true : undefined}
      onKeyDown={onDrawerKeyDown}
      ref={railRef}
      role={mobileDrawerOpen ? "dialog" : undefined}
      style={
        isMobile
          ? undefined
          : ({ "--dp-rail-chat": `${railWidth}px` } as CSSProperties)
      }
    >
      <div
        aria-label={isZh ? "调整对话栏宽度" : "Resize chat panel"}
        aria-orientation="vertical"
        aria-valuemax={Math.round(railMaximum)}
        aria-valuemin={MIN_RAIL_WIDTH}
        aria-valuenow={Math.round(railWidth)}
        className="dp-rail-resizer"
        onKeyDown={onResizeKeyDown}
        onPointerCancel={stopResize}
        onPointerDown={onResizePointerDown}
        onPointerMove={onResizePointerMove}
        onPointerUp={stopResize}
        role="separator"
        tabIndex={isMobile ? -1 : 0}
      >
        <span aria-hidden="true" />
      </div>
      <div className="dp-rail-head">
        <span className="title">Hermes</span>
        <span className="dp-live" data-hermes-chat-connection={connectionState} data-tone={connectionState === "unavailable" ? "warn" : undefined}>
          <span
            className="dp-dot"
            data-tone={connectionState === "ready" || connectionState === "read_only" ? "ok" : "warn"}
            aria-hidden="true"
          />
          {connectionState === "ready"
            ? isZh
              ? "本机已连接"
              : "Local connection ready"
            : connectionState === "read_only" ? (isZh ? "已连接 · 只读" : "Connected · read-only")
              : connectionState === "loading" ? (isZh ? "正在读取连接状态…" : "Reading connection status…")
                : isZh ? "连接暂不可用" : "Connection unavailable"}
        </span>
        <button
          aria-label={isZh ? "关闭对话" : "Close chat"}
          className="dp-chat-close"
          onClick={() => setChatRailOpen(false)}
          type="button"
        >
          {isZh ? "关闭" : "Close"}
        </button>
      </div>

      <details className="border-b border-[var(--dp-line)] px-4 py-2" data-hermes-recent-sessions>
        <summary className="app-touch-target flex cursor-pointer items-center font-label-caps text-[11px] text-[var(--dp-text-dim)]">
          {isZh ? "最近会话" : "Recent chats"}
        </summary>
        {sessionsQuery.isError || sessionsQuery.data?.read_status === "unavailable" ? (
          <p className="py-2 text-xs text-[var(--dp-text-dim)]" role="status">
            {isZh ? "会话列表暂不可用" : "Session list unavailable"}
          </p>
        ) : recentSessions.length ? (
          <ul className="mt-2 space-y-1" data-hermes-session-list>
            {recentSessions.map((session) => (
              <li
                data-hermes-session-message-count={session.message_count ?? 0}
                key={session.id}
              >
                <a
                  className="app-touch-target flex items-center truncate text-xs text-[var(--dp-text)] hover:underline"
                  href={localizePath(
                    `/hermes?hermes_session_id=${encodeURIComponent(session.id)}`,
                    locale,
                  )}
                >
                  {session.title?.trim() ||
                    session.preview?.trim() ||
                    (isZh ? "未命名新对话" : "Untitled conversation")}
                  <span className="ml-2 text-[var(--dp-text-dim)]">
                    {session.message_count ?? 0}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        ) : (
          <p className="py-2 text-xs text-[var(--dp-text-dim)]">
            {isZh ? "暂无保存会话" : "No saved chats"}
          </p>
        )}
      </details>

      <div
        className="dp-transcript dp-scroll"
        data-page-scroll-region
        data-hermes-transcript-scroll=""
        data-hermes-desk-transcript
      >
        {hasThread ? (
          <WorkbenchTranscriptPanel locale={locale} />
        ) : (
          <div className="dp-welcome" data-role="hermes">
            <span className="dp-welcome-mark" aria-hidden="true">H</span>
            <h1>{isZh ? "从一个想法开始。" : "Start with an idea."}</h1>
            <p>
              {isZh
                ? "把论文链接、策略描述或市场问题发给本机 Hermes。一起看规则、跑回测，再跟踪模拟表现。"
                : "Send your local Hermes a paper, a strategy, or a market question. Explore the rules, backtest, and track paper performance."}
            </p>
            <dl className="dp-welcome-examples">
              <div><dt>{isZh ? "研究" : "Research"}</dt><dd>{isZh ? "这篇论文里的因子，能用我的数据复现吗？" : "Can we reproduce this paper's factor with my data?"}</dd></div>
              <div><dt>{isZh ? "盯盘" : "Watch"}</dt><dd>{isZh ? "今天有哪些变化值得关注？" : "What market changes deserve attention today?"}</dd></div>
              <div><dt>{isZh ? "复盘" : "Review"}</dt><dd>{isZh ? "我的模拟策略最近表现怎么样？" : "How have my paper strategies performed?"}</dd></div>
            </dl>
            <p className="dp-welcome-note">{isZh ? "规则不完整时会追问。研究与模拟运行的进度，会留在这段对话里。" : "Hermes asks when rules are incomplete. Research and simulation updates stay in this conversation."}</p>
          </div>
        )}
        {showActivity && currentCommand ? (
          <div
            className="dp-agent-progress"
            data-active={activityActive ? "true" : "false"}
            data-hermes-run-activity
          >
            <span aria-hidden="true" className="dp-agent-progress-avatar">
              <Sparkles size={14} />
            </span>
            <div className="dp-agent-progress-copy">
              <div aria-atomic="true" aria-live="polite" role="status">
                <p className="dp-agent-progress-title">{activityStage}</p>
                {activityActive ? (
                  <p className="dp-agent-progress-meta">
                    {activityTransportLabel(
                      followState.transport,
                      followState.error,
                      isZh,
                    )}
                    {activityQuery.isError
                      ? isZh
                        ? " · 进度详情暂不可用"
                        : " · Progress details unavailable"
                      : ""}
                  </p>
                ) : null}
              </div>
              {activityActive ? (
                <div
                  aria-label={isZh ? "Hermes 处理进度" : "Hermes progress"}
                  aria-valuetext={activityStage}
                  className="dp-agent-progress-track"
                  role="progressbar"
                >
                  <span className="dp-agent-progress-bar" />
                </div>
              ) : null}
              <div className="dp-agent-progress-foot">
                {activity?.tool_state && activity.tool_state !== "active" ? (
                  <span data-hermes-tool-activity>
                    {activityToolLabel(activity, isZh)}
                  </span>
                ) : null}
                {activityTimeLabel && activityTime ? (
                  <span>
                    {isZh ? "最后活动 " : "Last activity "}
                    <time dateTime={activityTime.toISOString()}>
                      {activityTimeLabel}
                    </time>
                  </span>
                ) : null}
              </div>
            </div>
          </div>
        ) : null}
        {platformResearchResult ? (
          <PlatformResearchResultCard locale={locale} result={platformResearchResult} />
        ) : null}
        {remoteBookQuery.isError ? (
          <div
            className="dp-msg"
            data-platform-research-unavailable
            role="status"
          >
            <div className="head">
              <span className="who">Platform</span>
            </div>
            <div className="body">
              {isZh
                ? "研究候选账暂时不可用。这不是“仍在运行”；原始 Hermes 对话仍可查看。"
                : "The research book is unavailable. This is not a running-state placeholder; the native Hermes transcript remains visible."}
            </div>
          </div>
        ) : null}
      </div>

      <div className="dp-composer" data-hermes-desk-composer>
        {chatOpen ? (
          <ComposerSubmitController
            allowSubmit
            compact
            disabled={false}
            emptySessionText={
              isZh
                ? "直接发送即可。第一条消息会自动开对话。"
                : "Just send. The first message opens the conversation."
            }
            label={copy.composer.label}
            locale={locale}
            networkSubmit
            newSessionCreatingText={
              isZh
                ? "正在开新对话…"
                : "Creating a new conversation…"
            }
            newSessionLabel={isZh ? "新对话" : "New chat"}
            newSessionReadyText={
              isZh ? "新对话已就绪。" : "New conversation ready."
            }
            placeholder={
              isZh ? "粘贴论文链接，描述策略，或问一个市场问题…" : "Paste a paper, describe a strategy, or ask about the market…"
            }
            readOnlySessionText={
              isZh
                ? "这轮只能看。要点「新对话」另开一轮。"
                : "This thread is read-only. Start a new chat to continue."
            }
            retryLabel={copy.composer.retrySame}
            sendLabel={copy.composer.sendEnabled}
            sessionCheckingText={
              isZh ? "正在接上对话…" : "Connecting to the conversation…"
            }
            sessionValidationUnavailableText={
              isZh
                ? "这轮对话暂时写不进去。可以开一轮新的，或看一下本机后端。"
                : "This thread cannot accept writes. Start a new chat or check the local backend."
            }
            unavailableHint={copy.composer.unavailable}
          />
        ) : (
          <HermesCapabilityNotice
            deliveryState={deliveryState}
            locale={locale}
            readState={connectionState === "read_only" ? "available" : connectionState === "loading" ? "loading" : "unavailable"}
          />
        )}
      </div>
    </aside>
  );
}
