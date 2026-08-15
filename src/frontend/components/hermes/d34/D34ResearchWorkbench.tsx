"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import type { components } from "@/lib/api.generated";
import {
  ownerGetJson,
  ownerPostJson,
  WorkspaceClientError,
} from "@/lib/hermes/workspaceClient";
import type { Locale } from "@/lib/locale";
import { OwnerSessionBootstrapPanel } from "../OwnerSessionBootstrapPanel";

type Mandate = components["schemas"]["D34MandateResponse"];
type MandateList = components["schemas"]["D34MandateListResponse"];
type JobList = components["schemas"]["D34ExperimentJobListResponse"];
type ArtifactList = components["schemas"]["D34ArtifactListResponse"];
type Canary = components["schemas"]["D34CanaryResponse"];
type CanaryList = components["schemas"]["D34CanaryListResponse"];
type Safety = components["schemas"]["EffectiveD34SafetyResponse"];
type SleeveDetail = components["schemas"]["StrategySleeveDetailResponse"];

type Snapshot = {
  safety: Safety;
  mandates: Mandate[];
  jobs: JobList["items"];
  artifacts: ArtifactList["items"];
  canaries: Canary[];
  sleeveDetails: Record<string, SleeveDetail | null>;
};

function short(value: string, size = 10) {
  return value.length > size * 2 ? `${value.slice(0, size)}…${value.slice(-size)}` : value;
}

function formatTime(value: string, locale: Locale) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return value;
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

function formatMoney(value: string | number, signed = false) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return String(value);
  const absolute = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(amount));
  if (!signed) return `$${absolute}`;
  return `${amount >= 0 ? "+" : "-"}$${absolute}`;
}

function formatQuantity(value: number) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 }).format(value);
}

function statusLabel(value: string, isZh: boolean): string {
  if (!isZh) return value;
  const labels: Record<string, string> = {
    active: "进行中",
    running: "运行中",
    succeeded: "已完成",
    qualified: "已合格",
    canary_active: "金丝雀生效",
    paused: "已暂停",
    queued: "排队",
    leased: "占用中",
    outcome_unknown: "结果未知",
    rejected: "已拒绝",
    cancelled: "已取消",
  };
  return labels[value] ?? value;
}

function StatusPill({ value, isZh }: { value: string; isZh: boolean }) {
  const positive = ["active", "running", "succeeded", "qualified", "canary_active"].includes(
    value,
  );
  const warning = ["paused", "queued", "leased", "outcome_unknown"].includes(value);
  return (
    <span
      className={`rounded-full px-2 py-1 font-data-mono text-[11px] ${
        positive
          ? "bg-accent-success/10 text-accent-success"
          : warning
            ? "bg-warning/10 text-warning"
            : "bg-danger/10 text-danger"
      }`}
    >
      {statusLabel(value, isZh)}
    </span>
  );
}

export function D34ResearchWorkbench({ locale }: { locale: Locale }) {
  const isZh = locale === "zh";
  const [ownerReady, setOwnerReady] = useState(false);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [universe, setUniverse] = useState("SPY, QQQ, IWM, DIA");
  const [budget, setBudget] = useState("100.00");
  const [objective, setObjective] = useState("");
  const [hangIfPass, setHangIfPass] = useState(false);
  const [consoleOpen, setConsoleOpen] = useState<boolean | undefined>(undefined);
  const [lastAsk, setLastAsk] = useState<{
    job_key?: string | null;
    status?: string;
    code?: string;
  } | null>(null);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const [safety, mandates, jobs, artifacts, canaries] = await Promise.all([
        ownerGetJson<Safety>("/api/safety/effective/v2?workspace_id=default", signal),
        ownerGetJson<MandateList>("/api/hermes/mandates?workspace_id=default", signal),
        ownerGetJson<JobList>("/api/hermes/research/jobs?workspace_id=default", signal),
        ownerGetJson<ArtifactList>("/api/hermes/d34/artifacts?workspace_id=default", signal),
        ownerGetJson<CanaryList>("/api/hermes/canaries?workspace_id=default", signal),
      ]);
      const sleeveResults = await Promise.allSettled(
        canaries.items.map((canary) =>
          ownerGetJson<SleeveDetail>(
            `/api/paper/strategy-sleeves/${encodeURIComponent(canary.sleeve_id)}`,
            signal,
          ),
        ),
      );
      const sleeveDetails = Object.fromEntries(
        canaries.items.map((canary, index) => {
          const result = sleeveResults[index];
          return [canary.sleeve_id, result?.status === "fulfilled" ? result.value : null];
        }),
      );
      if (signal?.aborted) return;
      setSnapshot({
        safety,
        mandates: mandates.items,
        jobs: jobs.items,
        artifacts: artifacts.items,
        canaries: canaries.items,
        sleeveDetails,
      });
    } catch (cause) {
      if (signal?.aborted) return;
      const detail =
        cause instanceof WorkspaceClientError
          ? `${cause.code ? `[${cause.code}] ` : ""}${cause.message}`
          : cause instanceof Error
            ? cause.message
            : "D-34 workbench unavailable";
      setError(detail);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!ownerReady) return;
    const controller = new AbortController();
    queueMicrotask(() => {
      if (!controller.signal.aborted) void refresh(controller.signal);
    });
    return () => controller.abort();
  }, [ownerReady, refresh]);

  const mutate = useCallback(
    async (key: string, path: string, body: unknown) => {
      setBusy(key);
      setError(null);
      try {
        await ownerPostJson(path, body);
        await refresh();
      } catch (cause) {
        setError(
          cause instanceof WorkspaceClientError
            ? `${cause.code ? `[${cause.code}] ` : ""}${cause.message}`
            : cause instanceof Error
              ? cause.message
              : "D-34 mutation failed",
        );
      } finally {
        setBusy(null);
      }
    },
    [refresh],
  );

  const activeMandate = useMemo(
    () => snapshot?.mandates.find((item) => item.status === "active" || item.status === "paused"),
    [snapshot],
  );
  const [nowMs] = useState(() => Date.now());
  const askReady = useMemo(() => {
    if (
      activeMandate?.status !== "active" ||
      activeMandate.paper_execution_allowed !== true
    ) {
      return false;
    }
    const expiresAt = Date.parse(activeMandate.expires_at);
    return Number.isFinite(expiresAt) && expiresAt > nowMs;
  }, [activeMandate, nowMs]);
  const trimmedObjective = objective.trim();
  const askAllowed = askReady && trimmedObjective.length >= 8 && trimmedObjective.length <= 4000;
  const exceptions = useMemo(
    () =>
      snapshot?.jobs.filter((job) =>
        ["rejected", "outcome_unknown", "cancelled"].includes(job.state),
      ) ?? [],
    [snapshot],
  );

  async function createMandate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const symbols = universe
      .split(",")
      .map((value) => value.trim().toUpperCase())
      .filter(Boolean);
    await mutate("create-mandate", "/api/hermes/mandates", {
      workspace_id: "default",
      duration_days: 30,
      universe: symbols,
      hypotheses_per_cycle: 1,
      max_iterations: 3,
      max_experiments_per_iteration: 3,
      max_concurrent_jobs: 1,
      llm_budget_usd: budget,
      llm_warning_fraction: "0.80",
      paper_execution_allowed: true,
    });
  }

  const card = "rounded-[var(--radius-card)] border border-border-subtle bg-bg-surface p-4";
  const button =
    "app-touch-target rounded-[var(--radius-card)] border border-border-subtle bg-bg-base px-3 py-2 text-sm text-text-primary hover:border-border-strong focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info disabled:cursor-not-allowed disabled:opacity-50";

  return (
    <section aria-labelledby="d34-workbench-title" className="flex flex-col gap-4">
      <OwnerSessionBootstrapPanel
        locale={locale}
        onBootstrapSuccess={() => void refresh()}
        onReadinessChange={setOwnerReady}
      />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-label-caps text-text-secondary">
            {isZh ? "D-34 · 双引擎纸面研究" : "D-34 · on-demand paper research"}
          </p>
          <h2 className="mt-1 font-headline-lg text-text-primary" id="d34-workbench-title">
            {isZh ? "按需双引擎纸面研究" : "On-demand dual-engine paper research"}
          </h2>
          <p className="mt-2 max-w-3xl text-sm text-text-secondary">
            {isZh
              ? "你提出研究需求后才会入队。双引擎通过只进已验证候选，不等于挂上。要进每天跑，须另说挂上，或这次写明过了就挂。试运行仓是小额模拟观察，live 始终关闭。"
              : "Nothing is queued until you ask. Dual-engine pass becomes a verified candidate, not a hung sleeve. Daily book needs an explicit hang, or this ask must say hang-if-pass. Live stays off."}
          </p>
        </div>
        <button
          className={button}
          disabled={!ownerReady || loading}
          onClick={() => void refresh()}
          type="button"
        >
          {loading ? (isZh ? "刷新中…" : "Refreshing…") : isZh ? "刷新状态" : "Refresh"}
        </button>
      </div>

      {error ? (
        <p className="rounded-[var(--radius-card)] border border-danger/30 bg-danger/10 p-3 text-sm text-danger" role="alert">
          {error}
        </p>
      ) : null}

      {snapshot ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <div className={card}>
              <p className="font-label-caps text-text-secondary">
                {isZh ? "纸面权限" : "paper authority"}
              </p>
              <p className="mt-2 text-2xl font-semibold text-text-primary">
                {snapshot.safety.paper_execution_enabled
                  ? isZh
                    ? "就绪"
                    : "READY"
                  : isZh
                    ? "受阻"
                    : "BLOCKED"}
              </p>
              <p className="mt-1 text-xs text-text-secondary">
                {isZh ? "实盘" : "live"} = {String(snapshot.safety.live_execution_enabled)}
              </p>
            </div>
            <div className={card}>
              <p className="font-label-caps text-text-secondary">
                {isZh ? "研究任务" : "research jobs"}
              </p>
              <p className="mt-2 text-2xl font-semibold text-text-primary">
                {snapshot.safety.d34.running_jobs} / {snapshot.safety.d34.queued_jobs}
              </p>
              <p className="mt-1 text-xs text-text-secondary">
                {isZh ? "运行中 / 排队" : "running / queued"}
              </p>
            </div>
            <div className={card}>
              <p className="font-label-caps text-text-secondary">
                {isZh ? "LLM 预算" : "LLM budget"}
              </p>
              <p className="mt-2 text-2xl font-semibold text-text-primary">
                {snapshot.safety.budget.remaining_usd == null
                  ? "—"
                  : formatMoney(snapshot.safety.budget.remaining_usd)}
              </p>
              <p className="mt-1 text-xs text-text-secondary">
                {isZh ? "本授权剩余" : "remaining this Mandate"}
              </p>
            </div>
            <div className={card}>
              <p className="font-label-caps text-text-secondary">
                {isZh ? "纸面试运行仓" : "paper trial sleeves"}
              </p>
              <p className="mt-2 text-2xl font-semibold text-text-primary">
                {snapshot.safety.canaries.active_count}
              </p>
              <p className="mt-1 text-xs text-text-secondary">
                {formatMoney(snapshot.safety.canaries.allocated_cash)}{" "}
                {isZh ? "已划拨" : "allocated"}
              </p>
            </div>
          </div>

          <div className={card} data-testid="d34-soak-progress">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="font-headline-sm text-text-primary">
                  {isZh ? "运行验收进度" : "Runtime acceptance progress"}
                </h3>
                <p className="mt-1 text-sm text-text-secondary">
                  {isZh
                    ? "只统计完整 job→Artifact→canary 周期和上海时区真实观察日；临时探针不计入。"
                    : "Counts only complete job→Artifact→canary cycles and durable Shanghai observation days; temporary probes do not count."}
                </p>
              </div>
              <span
                className={`rounded-full px-2 py-1 font-data-mono text-[11px] ${
                  snapshot.safety.soak.time_gate_ready
                    ? "bg-accent-success/10 text-accent-success"
                    : "bg-warning/10 text-warning"
                }`}
              >
                {snapshot.safety.soak.time_gate_ready
                  ? isZh
                    ? "时间门已达标"
                    : "TIME GATE READY"
                  : isZh
                    ? "运行时间门未达标"
                    : "TIME GATE PENDING"}
              </span>
            </div>
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <p className="rounded-[var(--radius-card)] bg-bg-base p-3 text-sm text-text-primary">
                {isZh ? "完整研究周期" : "Complete research cycles"}{" "}
                <span className="font-data-mono">
                  {snapshot.safety.soak.completed_cycles} / {snapshot.safety.soak.required_completed_cycles}
                </span>
              </p>
              <p className="rounded-[var(--radius-card)] bg-bg-base p-3 text-sm text-text-primary">
                {isZh ? "Canary 观察日" : "Canary observation days"}{" "}
                <span className="font-data-mono">
                  {snapshot.safety.soak.canary_observation_days} / {snapshot.safety.soak.required_canary_observation_days}
                </span>
              </p>
              <p
                className="rounded-[var(--radius-card)] bg-bg-base p-3 text-sm text-text-primary"
                data-testid="d34-research-routing"
              >
                {isZh ? "当前研究入口" : "Current research entry"}{" "}
                <span className="font-data-mono">
                  {snapshot.safety.research_routing.default_research_entry.toUpperCase()}
                </span>
                <span className="mt-1 block text-xs text-text-secondary">
                  {snapshot.safety.research_routing.d33_maintenance_enabled
                    ? isZh
                      ? "D-33 旧 sleeve 维护运行中"
                      : "D-33 legacy sleeve maintenance stays active"
                    : isZh
                      ? "D-33 维护未启用"
                      : "D-33 maintenance is disabled"}
                </span>
              </p>
            </div>
            {snapshot.safety.soak.time_gate_ready &&
            snapshot.safety.research_routing.requested_default === "d33" ? (
              <p className="mt-3 text-xs text-warning">
                {isZh
                  ? "时间门已达标，等待最终零重复 / 零 live eligibility 验收 receipt。"
                  : "Time gate is ready; final zero-duplicate / zero-live-eligibility receipt is still pending."}
              </p>
            ) : null}
          </div>

          {activeMandate ? (
            <div className={card}>
              <h3 className="font-headline-sm text-text-primary">
                {isZh ? "提出研究" : "Ask for research"}
              </h3>
              <p className="mt-1 text-sm text-text-secondary">
                {isZh
                  ? "派研究默认只到已验证候选。要进每天跑，须另说「挂上」，或这次写明「过了就挂」。"
                  : "Dispatch stops at a verified candidate. Daily book needs a separate hang, or this ask must say hang-if-pass."}
              </p>
              {askReady ? (
                <form
                  className="mt-3 space-y-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (!askAllowed) return;
                    void (async () => {
                      setBusy("ask-research");
                      setError(null);
                      try {
                        const result = await ownerPostJson<{
                          job_key?: string | null;
                          status?: string;
                          code?: string;
                        }>("/api/hermes/research/requests", {
                          workspace_id: "default",
                          objective: trimmedObjective,
                          hang_if_pass: hangIfPass,
                        });
                        setLastAsk({
                          job_key: result.job_key,
                          status: result.status,
                          code: result.code,
                        });
                        setObjective("");
                        setHangIfPass(false);
                        await refresh();
                      } catch (cause) {
                        setError(
                          cause instanceof WorkspaceClientError
                            ? `${cause.code ? `[${cause.code}] ` : ""}${cause.message}`
                            : cause instanceof Error
                              ? cause.message
                              : "D-34 mutation failed",
                        );
                      } finally {
                        setBusy(null);
                      }
                    })();
                  }}
                >
                  <label className="block text-sm text-text-secondary">
                    {isZh ? "研究需求（你不提就不跑）" : "Research ask (nothing runs until you ask)"}
                    <textarea
                      className="app-touch-target mt-1 min-h-20 w-full rounded-[var(--radius-card)] border border-border-subtle bg-bg-base px-3 py-2 text-text-primary"
                      maxLength={4000}
                      minLength={8}
                      name="objective"
                      onChange={(event) => setObjective(event.target.value)}
                      placeholder={
                        isZh
                          ? "例如：找一个二十日反转，并说明为什么比上次好"
                          : "e.g. Find a 20-day reversal and say why it beats the last receipt"
                      }
                      required
                      value={objective}
                    />
                  </label>
                  <label className="flex items-start gap-2 text-sm text-text-secondary">
                    <input
                      checked={hangIfPass}
                      onChange={(event) => setHangIfPass(event.target.checked)}
                      type="checkbox"
                    />
                    <span>
                      {isZh ? "过了就挂（仅本次）" : "Hang if it passes (this ask only)"}
                    </span>
                  </label>
                  <button className={button} disabled={busy !== null || !askAllowed} type="submit">
                    {isZh ? "派研究" : "Dispatch research"}
                  </button>
                </form>
              ) : (
                <p className="mt-3 text-sm text-warning">
                  {isZh
                    ? "先恢复或续期进行中的 Mandate，才能提出研究。"
                    : "Resume or renew the active Mandate before asking for research."}
                </p>
              )}
              {lastAsk?.job_key ? (
                <p className="mt-3 font-data-mono text-xs text-text-secondary">
                  {lastAsk.status ?? "queued"} · {lastAsk.code ?? "d34_research_requested"} ·{" "}
                  {lastAsk.job_key}
                </p>
              ) : null}
            </div>
          ) : (
            <div className={card}>
              <h3 className="font-headline-sm text-text-primary">
                {isZh ? "先建研究信封" : "Create the research envelope"}
              </h3>
              <p className="mt-1 text-sm text-text-secondary">
                {isZh
                  ? "没有 Mandate 就不会入队。先建 30 天纸面信封，再提出研究。"
                  : "Nothing queues without a Mandate. Create the 30-day paper envelope, then ask."}
              </p>
              <form className="mt-3 space-y-3" onSubmit={createMandate}>
                <label className="block text-sm text-text-secondary">
                  Universe
                  <input
                    className="app-touch-target mt-1 w-full rounded-[var(--radius-card)] border border-border-subtle bg-bg-base px-3 py-2 text-text-primary"
                    onChange={(event) => setUniverse(event.target.value)}
                    required
                    value={universe}
                  />
                </label>
                <label className="block text-sm text-text-secondary">
                  {isZh ? "LLM 预算（美元）" : "LLM budget (USD)"}
                  <input
                    className="app-touch-target mt-1 w-full rounded-[var(--radius-card)] border border-border-subtle bg-bg-base px-3 py-2 text-text-primary"
                    min="1"
                    onChange={(event) => setBudget(event.target.value)}
                    required
                    step="0.01"
                    type="number"
                    value={budget}
                  />
                </label>
                <button className={button} disabled={busy !== null} type="submit">
                  {isZh ? "创建 30 天 Mandate 并允许 paper" : "Create 30-day paper Mandate"}
                </button>
              </form>
            </div>
          )}

          <details
            className="group rounded-[var(--radius-card)] border border-border-subtle bg-bg-surface"
            onToggle={(event) => setConsoleOpen(event.currentTarget.open)}
            open={consoleOpen ?? exceptions.length > 0}
          >
            <summary className="app-touch-target cursor-pointer list-none px-4 py-3 font-body-sm text-text-primary marker:hidden">
              {isZh
                ? exceptions.length
                  ? `展开操作台 · ${exceptions.length} 条异常待处理`
                  : "展开操作台（限额、授权、任务、金丝雀）"
                : exceptions.length
                  ? `Open console · ${exceptions.length} exceptions`
                  : "Open operator console (limits, mandate, jobs, canaries)"}
            </summary>
            <div className="flex flex-col gap-4 border-t border-border-subtle p-4">
          <div className={card}>
            <h3 className="font-headline-sm text-text-primary">
              {isZh ? "纸面风险限额" : "Paper risk limits"}
            </h3>
            <div className="mt-3 grid gap-2 text-sm text-text-secondary sm:grid-cols-2 xl:grid-cols-4">
              <p>
                {isZh ? "单 sleeve" : "Per sleeve"}{" "}
                {(snapshot.safety.risk.max_sleeve_nav_fraction * 100).toFixed(2)}% · {formatMoney(snapshot.safety.risk.max_sleeve_cash)}
              </p>
              <p>
                {isZh ? "自动合计" : "Automatic total"}{" "}
                {(snapshot.safety.risk.max_total_nav_fraction * 100).toFixed(2)}%
              </p>
              <p>
                {isZh ? "单标的合计" : "Per symbol total"}{" "}
                {(snapshot.safety.risk.max_symbol_nav_fraction * 100).toFixed(2)}%
              </p>
              <p>
                {isZh ? "日亏 / 回撤" : "Daily loss / drawdown"}{" "}
                {(snapshot.safety.risk.max_daily_loss * 100).toFixed(2)}% / {(snapshot.safety.risk.max_drawdown * 100).toFixed(2)}%
              </p>
            </div>
          </div>

          <div className={`${card} border-danger/30`}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="font-headline-sm text-text-primary">
                  {isZh ? "紧急停止" : "Emergency stop"}
                </h3>
                <p className="mt-1 text-sm text-text-secondary">
                  {isZh
                    ? "立即阻止新研究与新 paper 订单；不会伪造平仓。"
                    : "Immediately blocks new research and paper orders; it never fabricates a flatten."}
                </p>
              </div>
              <button
                className={`${button} border-danger/40 text-danger`}
                disabled={busy !== null}
                onClick={() =>
                  void mutate("emergency", "/api/safety/emergency-stop", {
                    workspace_id: "default",
                    enabled: !snapshot.safety.emergency_stop.active,
                    reason: snapshot.safety.emergency_stop.active
                      ? "owner resumed D-34 from local workbench"
                      : "owner emergency stop from local workbench",
                  })
                }
                type="button"
              >
                {snapshot.safety.emergency_stop.active
                  ? isZh
                    ? "解除 emergency stop"
                    : "Release emergency stop"
                  : isZh
                    ? "立即停止"
                    : "Stop now"}
              </button>
            </div>
            {snapshot.safety.blockers.length ? (
              <p className="mt-3 font-data-mono text-xs text-danger">
                {snapshot.safety.blockers.join(" · ")}
              </p>
            ) : null}
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <div className={card}>
              <div className="flex items-center justify-between gap-3">
                <h3 className="font-headline-sm text-text-primary">
                  {isZh ? "研究授权" : "Mandate"}
                </h3>
                {activeMandate ? <StatusPill isZh={isZh} value={activeMandate.status} /> : null}
              </div>
              {activeMandate ? (
                <div className="mt-3 space-y-3 text-sm">
                  <p className="text-text-primary">{activeMandate.universe.join(" · ")}</p>
                  <p className="text-text-secondary">
                    {isZh ? "到期" : "expires"}: {formatTime(activeMandate.expires_at, locale)} · $
                    {activeMandate.llm_budget_usd}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <button
                      className={button}
                      disabled={busy !== null}
                      onClick={() =>
                        void mutate(
                          "renew",
                          `/api/hermes/mandates/${activeMandate.mandate_id}/renew`,
                          {
                            duration_days: 30,
                            expected_version: activeMandate.version,
                            reason: "owner renewed 30-day cycle from local workbench",
                          },
                        )
                      }
                      type="button"
                    >
                      {isZh ? "续期 30 天" : "Renew 30 days"}
                    </button>
                    <button
                      className={button}
                      disabled={busy !== null}
                      onClick={() =>
                        void mutate(
                          activeMandate.status === "active" ? "pause" : "resume",
                          `/api/hermes/mandates/${activeMandate.mandate_id}/${
                            activeMandate.status === "active" ? "pause" : "resume"
                          }`,
                          {
                            expected_version: activeMandate.version,
                            reason: "owner changed Mandate state from local workbench",
                          },
                        )
                      }
                      type="button"
                    >
                      {activeMandate.status === "active"
                        ? isZh
                          ? "暂停"
                          : "Pause"
                        : isZh
                          ? "恢复"
                          : "Resume"}
                    </button>
                    <button
                      className={`${button} text-danger`}
                      disabled={busy !== null}
                      onClick={() =>
                        void mutate(
                          "revoke",
                          `/api/hermes/mandates/${activeMandate.mandate_id}/revoke`,
                          {
                            expected_version: activeMandate.version,
                            reason: "owner revoked Mandate from local workbench",
                          },
                        )
                      }
                      type="button"
                    >
                      {isZh ? "撤销" : "Revoke"}
                    </button>
                  </div>
                </div>
              ) : (
                <p className="mt-3 text-sm text-text-secondary">
                  {isZh
                    ? "创建 Mandate 的入口在上方，不藏在操作台里。"
                    : "Create the Mandate in the card above, not inside this console."}
                </p>
              )}
            </div>

            <div className={card}>
              <h3 className="font-headline-sm text-text-primary">
                {isZh ? "异常箱" : "Exception inbox"}
              </h3>
              {exceptions.length || snapshot.safety.blockers.length ? (
                <ul className="mt-3 space-y-2 text-sm">
                  {snapshot.safety.blockers.map((blocker) => (
                    <li className="font-data-mono text-danger" key={blocker}>
                      safety · {blocker}
                    </li>
                  ))}
                  {exceptions.slice(0, 8).map((job) => (
                    <li className="flex items-center justify-between gap-2" key={job.job_id}>
                      <span className="font-data-mono text-xs text-text-secondary" title={job.job_id}>
                        {short(job.job_id)} · {job.outcome_code ?? "no outcome"}
                      </span>
                      <StatusPill isZh={isZh} value={job.state} />
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-3 text-sm text-text-secondary">
                  {isZh ? "当前没有需要处理的异常。" : "No current exceptions."}
                </p>
              )}
            </div>
          </div>

          <div className={card}>
            <h3 className="font-headline-sm text-text-primary">
              {isZh ? "研究任务" : "Research jobs"}
            </h3>
            <div className="mt-3 grid gap-2">
              {snapshot.jobs.slice(0, 8).map((job) => (
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-card)] bg-bg-base p-3" key={job.job_id}>
                  <div>
                    <p className="font-data-mono text-xs text-text-primary" title={job.job_id}>
                      {short(job.job_id)}
                    </p>
                    <p className="mt-1 text-xs text-text-secondary">
                      {job.job_key} · attempts {job.attempt_count}/{job.max_attempts} · {formatMoney(job.budget_spent_usd)}
                    </p>
                  </div>
                  <StatusPill isZh={isZh} value={job.state} />
                </div>
              ))}
              {!snapshot.jobs.length ? (
                <p className="text-sm text-text-secondary">
                  {isZh ? "还没有研究任务。" : "No jobs yet."}
                </p>
              ) : null}
            </div>
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <div className={card}>
              <h3 className="font-headline-sm text-text-primary">
                {isZh ? "产物登记" : "Artifact Registry"}
              </h3>
              <div className="mt-3 space-y-2">
                {snapshot.artifacts.slice(0, 8).map((artifact) => (
                  <div className="rounded-[var(--radius-card)] bg-bg-base p-3" key={artifact.artifact_id}>
                    <div className="flex items-center justify-between gap-2">
                      <p className="font-data-mono text-xs text-text-primary" title={artifact.artifact_id}>
                        {short(artifact.artifact_id)}
                      </p>
                      <StatusPill isZh={isZh} value={artifact.status} />
                    </div>
                    <p className="mt-2 font-data-mono text-[11px] text-text-secondary" title={artifact.comparison_digest}>
                      comparison {short(artifact.comparison_digest)} · {artifact.qualification_scope}
                    </p>
                    {artifact.comparison ? (
                      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 font-data-mono text-[11px] text-text-secondary">
                        <span>corr {artifact.comparison.daily_return_correlation.toFixed(4)}</span>
                        <span>NAV Δ {artifact.comparison.terminal_nav_difference_bps.toFixed(2)} bps</span>
                        <span>
                          weight Δ {artifact.comparison.max_symbol_weight_difference_bps.toFixed(2)} bps
                        </span>
                        {artifact.comparison.reason_codes.map((reason) => (
                          <span className="text-danger" key={reason}>{reason}</span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ))}
                {!snapshot.artifacts.length ? <p className="text-sm text-text-secondary">No artifacts yet.</p> : null}
              </div>
            </div>

            <div className={card}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="font-headline-sm text-text-primary">
                  {isZh ? "纸面试运行仓" : "Paper trial sleeves"}
                </h3>
                <button
                  className={`${button} text-danger`}
                  disabled={busy !== null || !snapshot.canaries.some((item) => ["running", "paused", "provisioning"].includes(item.status))}
                  onClick={() =>
                    void mutate("rollback", "/api/hermes/d34/rollback", {
                      workspace_id: "default",
                      reason: "owner rolled D-34 back to D-33 hold mode",
                    })
                  }
                  type="button"
                >
                  {isZh ? "回退全部（保留持仓）" : "Rollback all (hold)"}
                </button>
              </div>
              <div className="mt-3 space-y-2">
                {snapshot.canaries.slice(0, 8).map((canary) => (
                  <div className="rounded-[var(--radius-card)] bg-bg-base p-3" key={canary.canary_id}>
                    <div className="flex items-center justify-between gap-2">
                      <p className="font-data-mono text-xs text-text-primary" title={canary.canary_id}>
                        {short(canary.canary_id)} · ${canary.allocated_cash}
                      </p>
                      <StatusPill isZh={isZh} value={canary.status} />
                    </div>
                    <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-text-secondary">
                      <span>P&amp;L {formatMoney(canary.daily_pnl, true)}</span>
                      <span>{isZh ? "回撤" : "drawdown"} {(Number(canary.drawdown_fraction) * 100).toFixed(2)}%</span>
                      <span>NAV {(Number(canary.nav_fraction) * 100).toFixed(2)}%</span>
                      {snapshot.sleeveDetails[canary.sleeve_id] ? (
                        <span>{isZh ? "现金" : "cash"} {formatMoney(snapshot.sleeveDetails[canary.sleeve_id]!.sleeve.cash)}</span>
                      ) : null}
                    </div>
                    {snapshot.sleeveDetails[canary.sleeve_id]?.lots.length ? (
                      <ul className="mt-2 space-y-1 font-data-mono text-[11px] text-text-secondary">
                        {snapshot.sleeveDetails[canary.sleeve_id]!.lots.map((lot) => (
                          <li key={lot.lot_id}>
                            {lot.symbol} · {formatQuantity(lot.quantity)} @ {formatMoney(lot.avg_cost)}
                          </li>
                        ))}
                      </ul>
                    ) : snapshot.sleeveDetails[canary.sleeve_id] === null ? (
                      <p className="mt-2 text-xs text-warning">
                        {isZh ? "sleeve 详情暂不可用" : "Sleeve detail unavailable"}
                      </p>
                    ) : (
                      <p className="mt-2 text-xs text-text-secondary">
                        {isZh ? "当前仅现金，无持仓" : "Cash only; no open positions"}
                      </p>
                    )}
                    {canary.status === "running" || canary.status === "paused" ? (
                      <div className="mt-2 flex flex-wrap gap-2">
                        {canary.status === "running" ? (
                          <button
                            className={button}
                            disabled={busy !== null}
                            onClick={() =>
                              void mutate(
                                `pause-${canary.canary_id}`,
                                `/api/hermes/canaries/${canary.canary_id}/pause`,
                                {
                                  expected_version: canary.version,
                                  reason: "owner paused canary from local workbench",
                                },
                              )
                            }
                            type="button"
                          >
                            {isZh ? "暂停" : "Pause"}
                          </button>
                        ) : null}
                        <button
                          className={`${button} text-danger`}
                          disabled={busy !== null}
                          onClick={() =>
                            void mutate(
                              `demote-${canary.canary_id}`,
                              `/api/hermes/canaries/${canary.canary_id}/demote`,
                              {
                                expected_version: canary.version,
                                reason: "owner demoted canary to hold from local workbench",
                              },
                            )
                          }
                          type="button"
                        >
                          {isZh ? "降级并持有" : "demote · hold"}
                        </button>
                      </div>
                    ) : null}
                  </div>
                ))}
                {!snapshot.canaries.length ? (
                  <p className="text-sm text-text-secondary">
                    {isZh ? "还没有金丝雀。" : "No canaries yet."}
                  </p>
                ) : null}
              </div>
            </div>
          </div>
            </div>
          </details>
        </>
      ) : ownerReady && !loading ? (
        <p className="text-sm text-text-secondary">
          {isZh ? "D-34 数据暂不可用。" : "D-34 data is unavailable."}
        </p>
      ) : null}
    </section>
  );
}
