'use client';

import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import {
  Activity,
  Pause,
  Play,
  Plus,
  Radio,
  RefreshCw,
  Square,
  WalletCards,
} from "lucide-react";
import { Card, MetricStat, StatusPill } from "@/components/ui/primitives";
import type {
  PaperStrategyConfigMutationResponse,
  PaperStrategyConfigResponse,
  PaperStrategySignalMutationResponse,
  PaperStrategySignalResponse,
  PaperStrategySleeveDetailResponse,
  PaperStrategySleeveMode,
  PaperStrategySleeveMutationResponse,
  PaperStrategySleeveResponse,
  StrategyMetadata,
} from "@/lib/api";
import { formatMoney } from "@/lib/api";
import { ApiClientError, apiPost, splitSymbols } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";

type Locale = "en" | "zh";

type SleeveAction = "pause" | "resume" | "stop";

const copy = {
  en: {
    title: "Strategy Sleeves",
    desc: "Strategy cash and lots stay isolated inside the same paper account. Signals are generated here; fills remain manual for this slice.",
    configs: "Configs",
    sleeves: "Sleeves",
    allocated: "Allocated",
    manualCash: "Account cash",
    configTitle: "Define strategy config",
    sleeveTitle: "Open sleeve",
    activeSleeves: "Active sleeves",
    name: "Name",
    strategy: "Strategy",
    symbols: "Symbols",
    lookback: "Lookback",
    topN: "Top N",
    provider: "Provider",
    createConfig: "Create config",
    creatingConfig: "Creating...",
    configCreated: "Strategy config created",
    configFailed: (reason: string) => `Config failed${reason ? `: ${reason}` : ""}`,
    noConfig: "Create a config before opening a sleeve.",
    config: "Config",
    mode: "Mode",
    signalOnly: "Signal-only",
    allocatedMode: "Allocated cash",
    cash: "Cash",
    openSleeve: "Open sleeve",
    openingSleeve: "Opening...",
    sleeveOpened: "Sleeve opened",
    sleeveFailed: (reason: string) => `Sleeve failed${reason ? `: ${reason}` : ""}`,
    historyDays: "History days",
    generateSignal: "Generate signal",
    generatingSignal: "Generating...",
    signalOk: (status: string) => `Signal ${status}`,
    signalFailed: (reason: string) => `Signal failed${reason ? `: ${reason}` : ""}`,
    pause: "Pause",
    resume: "Resume",
    stop: "Stop",
    actionFailed: (reason: string) => `Status change failed${reason ? `: ${reason}` : ""}`,
    noSleeves: "No sleeves yet. Start with a signal-only sleeve if you want zero cash movement.",
    latestSignal: "Latest signal",
    targetWeights: "Targets",
    noSignal: "No signal generated",
    noOrders: "No proposed orders",
    blocked: "Blocked",
    warnings: "Warnings",
    modeHelp: "Allocated mode moves cash from the manual lane; signal-only does not.",
    staleConfig: "config missing",
  },
  zh: {
    title: "策略袖珍仓",
    desc: "策略现金与 lot 在同一个模拟账户内分账隔离。本切片只在这里生成信号，成交仍然不会自动发生。",
    configs: "配置",
    sleeves: "袖珍仓",
    allocated: "已划拨",
    manualCash: "账户现金",
    configTitle: "定义策略配置",
    sleeveTitle: "开设袖珍仓",
    activeSleeves: "运行中的袖珍仓",
    name: "名称",
    strategy: "策略",
    symbols: "标的",
    lookback: "回看",
    topN: "Top N",
    provider: "数据源",
    createConfig: "创建配置",
    creatingConfig: "创建中...",
    configCreated: "策略配置已创建",
    configFailed: (reason: string) => `配置创建失败${reason ? `：${reason}` : ""}`,
    noConfig: "先创建策略配置，再开设袖珍仓。",
    config: "配置",
    mode: "模式",
    signalOnly: "仅信号",
    allocatedMode: "划拨现金",
    cash: "现金",
    openSleeve: "开设袖珍仓",
    openingSleeve: "开设中...",
    sleeveOpened: "袖珍仓已开设",
    sleeveFailed: (reason: string) => `袖珍仓创建失败${reason ? `：${reason}` : ""}`,
    historyDays: "历史天数",
    generateSignal: "生成信号",
    generatingSignal: "生成中...",
    signalOk: (status: string) => `信号状态：${status}`,
    signalFailed: (reason: string) => `信号生成失败${reason ? `：${reason}` : ""}`,
    pause: "暂停",
    resume: "恢复",
    stop: "停止",
    actionFailed: (reason: string) => `状态切换失败${reason ? `：${reason}` : ""}`,
    noSleeves: "还没有袖珍仓。若不想移动现金，先从“仅信号”模式开始。",
    latestSignal: "最新信号",
    targetWeights: "目标权重",
    noSignal: "尚未生成信号",
    noOrders: "无建议订单",
    blocked: "阻塞",
    warnings: "警告",
    modeHelp: "划拨现金模式会从手动现金通道移出资金；仅信号模式不会。",
    staleConfig: "配置缺失",
  },
} as const;

const inputClass =
  "rounded-lg border border-border-subtle bg-bg-surface-muted px-3 py-2 font-data-mono text-text-primary";
const labelClass = "flex flex-col gap-1 font-body-sm text-text-primary";
const secondaryButtonClass =
  "inline-flex items-center justify-center gap-2 rounded-lg border border-border-subtle px-3 py-2 font-body-sm text-text-primary transition-colors hover:bg-bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50";

export function PaperStrategySleevesPanel({
  locale = "en",
  configs,
  sleeves,
  sleeveDetails,
  strategies,
  accountAvailableCash,
  accountDown,
}: {
  locale?: Locale;
  configs: PaperStrategyConfigResponse[];
  sleeves: PaperStrategySleeveResponse[];
  sleeveDetails: PaperStrategySleeveDetailResponse[];
  strategies: StrategyMetadata[];
  accountAvailableCash: number;
  accountDown: boolean;
}) {
  const text = copy[locale];
  const router = useRouter();
  const isHydrated = useIsHydrated();
  const strategyOptions = strategies.filter((strategy) => strategy.result_type === "backtest");
  const defaultStrategyId = strategyOptions[0]?.id ?? "cross_sectional_top_n";
  const [strategyId, setStrategyId] = useState(defaultStrategyId);
  const [configName, setConfigName] = useState(
    locale === "zh" ? "动量袖珍仓配置" : "Momentum sleeve config",
  );
  const [symbols, setSymbols] = useState("SPY,QQQ,IWM,DIA");
  const [lookback, setLookback] = useState(20);
  const [topN, setTopN] = useState(3);
  const [provider, setProvider] = useState<"futu" | "tiingo">("futu");
  const [selectedConfigId, setSelectedConfigId] = useState(configs[0]?.strategy_config_id ?? "");
  const [mode, setMode] = useState<PaperStrategySleeveMode>("signal_only");
  const [allocatedCash, setAllocatedCash] = useState(100_000);
  const [historyDays, setHistoryDays] = useState(180);

  const effectiveStrategyId = strategyId || defaultStrategyId;
  const effectiveSelectedConfigId = selectedConfigId || configs[0]?.strategy_config_id || "";
  const configById = useMemo(
    () => new Map(configs.map((config) => [config.strategy_config_id, config])),
    [configs],
  );
  const detailBySleeve = useMemo(
    () => new Map(sleeveDetails.map((detail) => [detail.sleeve.sleeve_id, detail])),
    [sleeveDetails],
  );
  const allocatedTotal = sleeves.reduce((sum, sleeve) => sum + sleeve.cash, 0);

  const createConfigMutation = useMutation({
    mutationFn: () =>
      apiPost<PaperStrategyConfigMutationResponse>("/api/paper/strategy-configs", {
        name: configName.trim() || `${effectiveStrategyId} sleeve`,
        description: "Created from the paper trading Strategy Sleeves panel.",
        strategy_id: effectiveStrategyId,
        symbols: splitSymbols(symbols),
        lookback,
        top_n: topN,
        max_weight_per_symbol: 1,
        min_order_value: 0,
        data_provider: provider,
        execution_timing: "next_open",
        rebalance_frequency: "daily",
        tags: ["paper-trading-ui"],
      }),
    onSuccess: (payload) => {
      toast.success(text.configCreated);
      setSelectedConfigId(payload.config.strategy_config_id);
      router.refresh();
    },
    onError: (error) => {
      toast.error(text.configFailed(apiErrorMessage(error)));
    },
  });

  const createSleeveMutation = useMutation({
    mutationFn: () =>
      apiPost<PaperStrategySleeveMutationResponse>("/api/paper/strategy-sleeves", {
        strategy_config_id: effectiveSelectedConfigId,
        mode,
        allocated_cash: mode === "allocated" ? allocatedCash : 0,
        metadata: { source: "paper-trading-ui" },
      }),
    onSuccess: () => {
      toast.success(text.sleeveOpened);
      router.refresh();
    },
    onError: (error) => {
      toast.error(text.sleeveFailed(apiErrorMessage(error)));
    },
  });

  const generateSignalMutation = useMutation({
    mutationFn: (sleeveId: string) =>
      apiPost<PaperStrategySignalMutationResponse>(
        `/api/paper/strategy-sleeves/${encodeURIComponent(sleeveId)}/signals`,
        { history_days: historyDays },
      ),
    onSuccess: (payload) => {
      toast.success(text.signalOk(payload.signal.status));
      router.refresh();
    },
    onError: (error) => {
      toast.error(text.signalFailed(apiErrorMessage(error)));
    },
  });

  const statusMutation = useMutation({
    mutationFn: ({ sleeveId, action }: { sleeveId: string; action: SleeveAction }) =>
      apiPost<PaperStrategySleeveMutationResponse>(
        `/api/paper/strategy-sleeves/${encodeURIComponent(sleeveId)}/${action}`,
        action === "stop" ? { reason: "stopped from paper-trading UI" } : {},
      ),
    onSuccess: () => {
      router.refresh();
    },
    onError: (error) => {
      toast.error(text.actionFailed(apiErrorMessage(error)));
    },
  });

  const canCreateConfig =
    isHydrated &&
    effectiveStrategyId.length > 0 &&
    splitSymbols(symbols).length > 0 &&
    topN > 0 &&
    lookback > 0 &&
    !createConfigMutation.isPending;
  const canCreateSleeve =
    isHydrated &&
    effectiveSelectedConfigId.length > 0 &&
    !createSleeveMutation.isPending &&
    (mode === "signal_only" || (!accountDown && allocatedCash > 0));

  return (
    <Card tone="info" padded>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 font-headline-lg text-text-primary">
            <WalletCards className="text-info" size={18} />
            {text.title}
          </h2>
          <p className="mt-1 max-w-3xl font-body-sm text-text-secondary">{text.desc}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <StatusPill label={text.configs} value={configs.length} tone="info" />
          <StatusPill label={text.sleeves} value={sleeves.length} tone="success" />
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricStat label={text.allocated} value={formatMoney(allocatedTotal)} />
        <MetricStat
          label={text.manualCash}
          value={accountDown ? "--" : formatMoney(accountAvailableCash)}
          tone={accountDown ? "warning" : "neutral"}
        />
        <MetricStat label={text.configs} value={configs.length} />
        <MetricStat
          label={text.sleeves}
          value={sleeves.filter((sleeve) => sleeve.status === "running").length}
          tone="success"
        />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <section className="rounded-lg border border-border-subtle bg-bg-surface p-4">
          <div className="mb-3 flex items-center gap-2">
            <Plus size={15} className="text-info" />
            <h3 className="font-label-caps text-text-primary">{text.configTitle}</h3>
          </div>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <label className={labelClass}>
              {text.name}
              <input className={inputClass} value={configName} onChange={(event) => setConfigName(event.target.value)} />
            </label>
            <label className={labelClass}>
              {text.strategy}
              <select className={inputClass} value={effectiveStrategyId} onChange={(event) => setStrategyId(event.target.value)}>
                {strategyOptions.map((strategy) => (
                  <option key={strategy.id} value={strategy.id}>
                    {strategy.name}
                  </option>
                ))}
              </select>
            </label>
            <label className={`${labelClass} lg:col-span-2`}>
              {text.symbols}
              <input className={inputClass} value={symbols} onChange={(event) => setSymbols(event.target.value)} />
            </label>
            <label className={labelClass}>
              {text.topN}
              <input
                className={inputClass}
                min={1}
                type="number"
                value={topN}
                onChange={(event) => setTopN(Number(event.target.value))}
              />
            </label>
            <label className={labelClass}>
              {text.lookback}
              <input
                className={inputClass}
                min={1}
                type="number"
                value={lookback}
                onChange={(event) => setLookback(Number(event.target.value))}
              />
            </label>
            <label className={labelClass}>
              {text.provider}
              <select
                className={inputClass}
                value={provider}
                onChange={(event) => setProvider(event.target.value as "futu" | "tiingo")}
              >
                <option value="futu">Futu</option>
                <option value="tiingo">Tiingo</option>
              </select>
            </label>
            <button
              className="self-end rounded-lg bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
              disabled={!canCreateConfig}
              onClick={() => createConfigMutation.mutate()}
              type="button"
            >
              {createConfigMutation.isPending ? text.creatingConfig : text.createConfig}
            </button>
          </div>
        </section>

        <section className="rounded-lg border border-border-subtle bg-bg-surface p-4">
          <div className="mb-3 flex items-center gap-2">
            <Radio size={15} className="text-accent-success" />
            <h3 className="font-label-caps text-text-primary">{text.sleeveTitle}</h3>
          </div>
          <div className="flex flex-col gap-3">
            <label className={labelClass}>
              {text.config}
              <select
                className={inputClass}
                disabled={configs.length === 0}
                value={effectiveSelectedConfigId}
                onChange={(event) => setSelectedConfigId(event.target.value)}
              >
                {configs.map((config) => (
                  <option key={`${config.strategy_config_id}-${config.version}`} value={config.strategy_config_id}>
                    {config.name} v{config.version}
                  </option>
                ))}
              </select>
            </label>
            <div className="grid grid-cols-2 gap-2">
              <label className={labelClass}>
                {text.mode}
                <select
                  className={inputClass}
                  value={mode}
                  onChange={(event) => setMode(event.target.value as PaperStrategySleeveMode)}
                >
                  <option value="signal_only">{text.signalOnly}</option>
                  <option value="allocated">{text.allocatedMode}</option>
                </select>
              </label>
              <label className={labelClass}>
                {text.cash}
                <input
                  className={inputClass}
                  disabled={mode === "signal_only"}
                  min={0}
                  type="number"
                  value={allocatedCash}
                  onChange={(event) => setAllocatedCash(Number(event.target.value))}
                />
              </label>
            </div>
            <p className="font-body-sm text-text-secondary">{configs.length ? text.modeHelp : text.noConfig}</p>
            <button
              className="rounded-lg border border-accent-success bg-accent-success/10 px-4 py-2 font-body-sm font-semibold text-accent-success disabled:cursor-not-allowed disabled:opacity-50"
              disabled={!canCreateSleeve}
              onClick={() => createSleeveMutation.mutate()}
              type="button"
            >
              {createSleeveMutation.isPending ? text.openingSleeve : text.openSleeve}
            </button>
          </div>
        </section>
      </div>

      <section className="mt-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h3 className="flex items-center gap-2 font-label-caps text-text-primary">
            <Activity size={15} className="text-info" />
            {text.activeSleeves}
          </h3>
          <label className="flex items-center gap-2 font-body-sm text-text-secondary">
            {text.historyDays}
            <input
              className="w-24 rounded-lg border border-border-subtle bg-bg-surface-muted px-2 py-1 font-data-mono text-text-primary"
              min={1}
              type="number"
              value={historyDays}
              onChange={(event) => setHistoryDays(Number(event.target.value))}
            />
          </label>
        </div>
        {sleeves.length === 0 ? (
          <p className="rounded-lg border border-border-subtle bg-bg-surface p-4 text-center font-body-sm text-text-secondary">
            {text.noSleeves}
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-3 2xl:grid-cols-2">
            {sleeves.map((sleeve) => {
              const config = configById.get(sleeve.strategy_config_id);
              const detail = detailBySleeve.get(sleeve.sleeve_id);
              const latestSignal = latestByGeneratedAt(detail?.signals ?? []);
              const isGenerating = generateSignalMutation.isPending && generateSignalMutation.variables === sleeve.sleeve_id;
              const isStatusChanging =
                statusMutation.isPending && statusMutation.variables?.sleeveId === sleeve.sleeve_id;
              return (
                <SleeveRow
                  config={config}
                  isGenerating={isGenerating}
                  isStatusChanging={isStatusChanging}
                  key={sleeve.sleeve_id}
                  latestSignal={latestSignal}
                  onGenerate={() => generateSignalMutation.mutate(sleeve.sleeve_id)}
                  onStatus={(action) => statusMutation.mutate({ sleeveId: sleeve.sleeve_id, action })}
                  sleeve={sleeve}
                  text={text}
                />
              );
            })}
          </div>
        )}
      </section>
    </Card>
  );
}

function SleeveRow({
  config,
  isGenerating,
  isStatusChanging,
  latestSignal,
  onGenerate,
  onStatus,
  sleeve,
  text,
}: {
  config?: PaperStrategyConfigResponse;
  isGenerating: boolean;
  isStatusChanging: boolean;
  latestSignal?: PaperStrategySignalResponse;
  onGenerate: () => void;
  onStatus: (action: SleeveAction) => void;
  sleeve: PaperStrategySleeveResponse;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
}) {
  const tone =
    sleeve.status === "running" ? "success" : sleeve.status === "paused" ? "warning" : "danger";
  const latestTargets = latestSignal
    ? Object.entries(latestSignal.target_weights)
        .sort(([, a], [, b]) => b - a)
        .slice(0, 4)
        .map(([symbol, weight]) => `${symbol} ${(weight * 100).toFixed(0)}%`)
        .join(" · ")
    : "";
  const proposedOrders = latestSignal?.proposed_orders.length ?? 0;

  return (
    <div className="rounded-lg border border-border-subtle bg-bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate font-data-mono text-sm font-bold text-text-primary">
              {config?.name ?? text.staleConfig}
            </span>
            <StatusPill label="" value={sleeve.status} tone={tone} />
            <StatusPill label="" value={sleeve.mode} tone={sleeve.mode === "allocated" ? "success" : "info"} />
          </div>
          <p className="mt-1 truncate font-data-mono text-[10px] text-text-secondary" title={sleeve.sleeve_id}>
            {sleeve.sleeve_id}
          </p>
        </div>
        <div className="text-right font-data-mono text-sm text-text-primary">
          {formatMoney(sleeve.cash)}
          <div className="text-[10px] uppercase text-text-secondary">{config?.strategy_id ?? "--"}</div>
        </div>
      </div>

      <div className="mt-3 rounded-lg border border-border-subtle bg-bg-surface-muted/40 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="font-label-caps text-text-secondary">{text.latestSignal}</span>
          {latestSignal ? (
            <StatusPill label="" value={latestSignal.status} tone={signalTone(latestSignal.status)} />
          ) : null}
        </div>
        {latestSignal ? (
          <div className="mt-2 space-y-1 font-data-mono text-xs text-text-secondary">
            <p>{formatShortDate(latestSignal.generated_at)}</p>
            <p>
              {text.targetWeights}: {latestTargets || "--"}
            </p>
            <p>
              {proposedOrders > 0 ? `${proposedOrders} proposed` : text.noOrders}
              {latestSignal.execution_blocked_reason ? ` · ${text.blocked}: ${latestSignal.execution_blocked_reason}` : ""}
            </p>
            {latestSignal.warnings.length ? (
              <p className="text-warning">
                {text.warnings}: {latestSignal.warnings.join(" · ")}
              </p>
            ) : null}
          </div>
        ) : (
          <p className="mt-2 font-body-sm text-text-secondary">{text.noSignal}</p>
        )}
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          className="inline-flex items-center justify-center gap-2 rounded-lg border border-info/40 bg-info/10 px-3 py-2 font-body-sm font-semibold text-info disabled:cursor-not-allowed disabled:opacity-50"
          disabled={isGenerating || sleeve.status === "stopped"}
          onClick={onGenerate}
          type="button"
        >
          <RefreshCw size={14} />
          {isGenerating ? text.generatingSignal : text.generateSignal}
        </button>
        {sleeve.status === "paused" ? (
          <button className={secondaryButtonClass} disabled={isStatusChanging} onClick={() => onStatus("resume")} type="button">
            <Play size={14} />
            {text.resume}
          </button>
        ) : (
          <button
            className={secondaryButtonClass}
            disabled={isStatusChanging || sleeve.status === "stopped"}
            onClick={() => onStatus("pause")}
            type="button"
          >
            <Pause size={14} />
            {text.pause}
          </button>
        )}
        <button
          className="inline-flex items-center justify-center gap-2 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 font-body-sm text-danger disabled:cursor-not-allowed disabled:opacity-50"
          disabled={isStatusChanging || sleeve.status === "stopped"}
          onClick={() => onStatus("stop")}
          type="button"
        >
          <Square size={14} />
          {text.stop}
        </button>
      </div>
    </div>
  );
}

function latestByGeneratedAt(signals: PaperStrategySignalResponse[]) {
  return [...signals].sort((a, b) => b.generated_at.localeCompare(a.generated_at))[0];
}

function signalTone(status: PaperStrategySignalResponse["status"]) {
  if (status === "generated") return "success";
  if (status === "data_unavailable") return "warning";
  return "danger";
}

function apiErrorMessage(error: unknown) {
  return error instanceof ApiClientError ? error.message : error instanceof Error ? error.message : "";
}

function formatShortDate(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) {
    return value;
  }
  return `${parsed.getFullYear()}-${String(parsed.getMonth() + 1).padStart(2, "0")}-${String(
    parsed.getDate(),
  ).padStart(2, "0")} ${String(parsed.getHours()).padStart(2, "0")}:${String(
    parsed.getMinutes(),
  ).padStart(2, "0")}`;
}
