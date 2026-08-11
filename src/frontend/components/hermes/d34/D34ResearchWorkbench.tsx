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

type Snapshot = {
  safety: Safety;
  mandates: Mandate[];
  jobs: JobList["items"];
  artifacts: ArtifactList["items"];
  canaries: Canary[];
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

function StatusPill({ value }: { value: string }) {
  const positive = ["active", "running", "succeeded", "qualified", "canary_active"].includes(
    value,
  );
  const warning = ["paused", "queued", "leased", "outcome_unknown"].includes(value);
  return (
    <span
      className={`rounded-full px-2 py-1 font-data-mono text-[11px] ${
        positive
          ? "bg-success/10 text-success"
          : warning
            ? "bg-warning/10 text-warning"
            : "bg-danger/10 text-danger"
      }`}
    >
      {value}
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
      setSnapshot({
        safety,
        mandates: mandates.items,
        jobs: jobs.items,
        artifacts: artifacts.items,
        canaries: canaries.items,
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
          <p className="font-label-caps text-text-secondary">D-34 · autonomous paper research</p>
          <h2 className="mt-1 font-headline-lg text-text-primary" id="d34-workbench-title">
            {isZh ? "Mandate 驱动的双引擎研究" : "Mandate-driven dual-engine research"}
          </h2>
          <p className="mt-2 max-w-3xl text-sm text-text-secondary">
            {isZh
              ? "论文假设与 Qlib 迭代在 Docker 中运行，Platform 独立重放；通过确定性政策后只进入低额度 paper canary。live 始终关闭。"
              : "RD-Agent/Qlib research runs in Docker and Platform independently replays execution. Qualified artifacts can enter low-allocation paper canaries only; live stays off."}
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
              <p className="font-label-caps text-text-secondary">paper authority</p>
              <p className="mt-2 text-2xl font-semibold text-text-primary">
                {snapshot.safety.paper_execution_enabled ? "READY" : "BLOCKED"}
              </p>
              <p className="mt-1 text-xs text-text-secondary">
                live = {String(snapshot.safety.live_execution_enabled)}
              </p>
            </div>
            <div className={card}>
              <p className="font-label-caps text-text-secondary">research jobs</p>
              <p className="mt-2 text-2xl font-semibold text-text-primary">
                {snapshot.safety.d34.running_jobs} / {snapshot.safety.d34.queued_jobs}
              </p>
              <p className="mt-1 text-xs text-text-secondary">
                {isZh ? "运行中 / 排队" : "running / queued"}
              </p>
            </div>
            <div className={card}>
              <p className="font-label-caps text-text-secondary">LLM budget</p>
              <p className="mt-2 text-2xl font-semibold text-text-primary">
                ${snapshot.safety.budget.remaining_usd ?? "—"}
              </p>
              <p className="mt-1 text-xs text-text-secondary">
                {isZh ? "本 Mandate 剩余" : "remaining this Mandate"}
              </p>
            </div>
            <div className={card}>
              <p className="font-label-caps text-text-secondary">paper canaries</p>
              <p className="mt-2 text-2xl font-semibold text-text-primary">
                {snapshot.safety.canaries.active_count}
              </p>
              <p className="mt-1 text-xs text-text-secondary">
                ${snapshot.safety.canaries.allocated_cash} allocated
              </p>
            </div>
          </div>

          <div className={`${card} border-danger/30`}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="font-headline-sm text-text-primary">Emergency stop</h3>
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
                <h3 className="font-headline-sm text-text-primary">Mandate</h3>
                {activeMandate ? <StatusPill value={activeMandate.status} /> : null}
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
                      <StatusPill value={job.state} />
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
            <h3 className="font-headline-sm text-text-primary">Research jobs</h3>
            <div className="mt-3 grid gap-2">
              {snapshot.jobs.slice(0, 8).map((job) => (
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-card)] bg-bg-base p-3" key={job.job_id}>
                  <div>
                    <p className="font-data-mono text-xs text-text-primary" title={job.job_id}>
                      {short(job.job_id)}
                    </p>
                    <p className="mt-1 text-xs text-text-secondary">
                      {job.job_key} · attempts {job.attempt_count}/{job.max_attempts} · ${job.budget_spent_usd}
                    </p>
                  </div>
                  <StatusPill value={job.state} />
                </div>
              ))}
              {!snapshot.jobs.length ? <p className="text-sm text-text-secondary">No jobs yet.</p> : null}
            </div>
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <div className={card}>
              <h3 className="font-headline-sm text-text-primary">Artifact Registry</h3>
              <div className="mt-3 space-y-2">
                {snapshot.artifacts.slice(0, 8).map((artifact) => (
                  <div className="rounded-[var(--radius-card)] bg-bg-base p-3" key={artifact.artifact_id}>
                    <div className="flex items-center justify-between gap-2">
                      <p className="font-data-mono text-xs text-text-primary" title={artifact.artifact_id}>
                        {short(artifact.artifact_id)}
                      </p>
                      <StatusPill value={artifact.status} />
                    </div>
                    <p className="mt-2 font-data-mono text-[11px] text-text-secondary" title={artifact.comparison_digest}>
                      comparison {short(artifact.comparison_digest)} · {artifact.qualification_scope}
                    </p>
                  </div>
                ))}
                {!snapshot.artifacts.length ? <p className="text-sm text-text-secondary">No artifacts yet.</p> : null}
              </div>
            </div>

            <div className={card}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="font-headline-sm text-text-primary">Paper canaries</h3>
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
                      <StatusPill value={canary.status} />
                    </div>
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
                          demote · hold
                        </button>
                      </div>
                    ) : null}
                  </div>
                ))}
                {!snapshot.canaries.length ? <p className="text-sm text-text-secondary">No canaries yet.</p> : null}
              </div>
            </div>
          </div>
        </>
      ) : ownerReady && !loading ? (
        <p className="text-sm text-text-secondary">D-34 data is unavailable.</p>
      ) : null}
    </section>
  );
}
