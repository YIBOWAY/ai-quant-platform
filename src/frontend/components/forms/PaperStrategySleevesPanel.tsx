'use client';

import { PaperRuntimeEvidence, paperRuntimeLabel } from "@/components/research/PaperRuntimeEvidence";

import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import {
  Activity,
  CheckCircle2,
  Pause,
  Play,
  Plus,
  Radio,
  RefreshCw,
  Send,
  Square,
  WalletCards,
} from "lucide-react";
import {
  Card,
  MetricStat,
  StatusPill,
  TerminalToolbarButton,
  ToneBadge,
} from "@/components/ui/primitives";
import type {
  PaperStrategyConfigMutationResponse,
  PaperStrategyConfigResponse,
  PaperStrategyConfigsResponse,
  PaperStrategyExecutionMutationResponse,
  PaperStrategyExecutionPlanResponse,
  PaperStrategyExecutionProcessResponse,
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
import {
  formatStrategyConfigOptionLabel,
  hasStrategyConfigNameConflict,
  suggestNextStrategyConfigName,
} from "@/lib/paperStrategySleeves";
import {
  partitionStrategySleeves,
  strategyConfigDisplayName,
  strategySleeveDisplayName,
  strategySleeveModeLabel,
  strategySleeveStatusLabel,
} from "@/lib/paperStrategyPresentation";

type Locale = "en" | "zh";

type SleeveAction = "pause" | "resume" | "stop";

const copy = {
  en: {
    title: "Strategy Sleeves",
    desc: "Strategy cash and lots stay isolated inside the same paper account. Enabled allocated sleeves can fill and record P&L while live stays off.",
    configs: "Configs",
    sleeves: "Sleeves",
    initialCash: "Official initial allocation",
    availableCash: "Official available cash",
    strategyEquity: "Strategy NAV",
    equityUnavailable: "Not calculated",
    manualCash: "Account cash",
    configTitle: "Define strategy config",
    sleeveTitle: "Open sleeve",
    labSummary:
      "Lab: manual config & sleeve opening (collapsed by default). Daily runs still bind the exact candidate source fingerprint.",
    activeSleeves: "Active sleeves",
    officialSleeves: "Official simulated strategies",
    pendingSleeves: "Pending activation recovery",
    pendingDesc: "Activation lineage exists, but book binding or activation is not complete. Excluded from official totals.",
    manualSleeves: "Manual lab sleeves",
    manualDesc: "Manually opened lab sleeves stay visible but are not official simulated strategies.",
    historicalSleeves: "Historical test sleeves",
    historicalDesc: "Stopped preview/test sleeves are kept for history and excluded from official counts.",
    technical: "Technical details",
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
    duplicateConfigName:
      "A config with this name already exists. Use a distinct name; versions keep one config identity.",
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
    createExecution: "Create plan",
    creatingExecution: "Creating plan...",
    executionCreated: (status: string) => `Execution plan ${status}`,
    executionFailed: (reason: string) => `Execution failed${reason ? `: ${reason}` : ""}`,
    processPending: "Process pending",
    processingPending: "Processing...",
    processOk: (filled: number, blocked: number) => `Processed: ${filled} filled, ${blocked} blocked`,
    latestExecution: "Latest execution",
    noExecution: "No execution plan",
    planFirst: "Create a pending plan first.",
    pause: "Pause",
    resume: "Resume",
    stop: "Stop",
    actionFailed: (reason: string) => `Status change failed${reason ? `: ${reason}` : ""}`,
    noSleeves: "No official simulated strategy. Pending, manual, and historical sleeves remain listed separately below.",
    latestSignal: "Latest signal",
    runtimeDetails: "Run details / actions",
    targetWeights: "Targets",
    proposedOrders: (count: number) => `${count} proposed orders`,
    orderCount: (count: number) => `${count} orders`,
    fillCount: (count: number) => `${count} fills`,
    noSignal: "No signal generated",
    noOrders: "No proposed orders",
    blocked: "Blocked",
    warnings: "Warnings",
    modeHelp: "Allocated mode moves cash from the manual lane; signal-only does not.",
    staleConfig: "config missing",
    historicalConfig: "Historical config: source changed, read-only; cannot open a sleeve",
    unavailableConfig: "Config unavailable: original file missing, invalid, or unreadable",
  },
  zh: {
    title: "策略仓",
    desc: "策略现金与持仓在同一个模拟账户内分账隔离。启用模拟运行的划拨仓可以成交并记录盈亏；实盘仍关闭。",
    configs: "配置",
    sleeves: "策略仓",
    initialCash: "正式策略初始投入",
    availableCash: "正式策略可用现金",
    strategyEquity: "策略净值",
    equityUnavailable: "策略净值未计算",
    manualCash: "账户现金",
    configTitle: "定义策略配置",
    sleeveTitle: "开设策略仓",
    labSummary:
      "实验室：手动配置与开仓（默认收起）。正式进入每天跑仍须绑定候选来源指纹。",
    activeSleeves: "运行中的策略仓",
    officialSleeves: "正式模拟策略",
    pendingSleeves: "待恢复启用",
    pendingDesc: "已有启用记录关联，但账本绑定或启用尚未完成；不计入正式策略数量与金额。",
    manualSleeves: "手动实验仓",
    manualDesc: "手动开设的实验仓继续可见，但不属于正式模拟策略。",
    historicalSleeves: "历史测试仓",
    historicalDesc: "已停止的预览/测试仓只保留作历史，不计入正式策略数量与金额。",
    technical: "技术信息",
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
    duplicateConfigName: "已有同名配置。请改名；同一策略参数变更应走版本，不要再建同名配置。",
    noConfig: "先创建策略配置，再开设策略仓。",
    config: "配置",
    mode: "模式",
    signalOnly: "仅信号",
    allocatedMode: "划拨现金",
    cash: "现金",
    openSleeve: "开设策略仓",
    openingSleeve: "开设中...",
    sleeveOpened: "策略仓已开设",
    sleeveFailed: (reason: string) => `策略仓创建失败${reason ? `：${reason}` : ""}`,
    historyDays: "历史天数",
    generateSignal: "生成信号",
    generatingSignal: "生成中...",
    signalOk: (status: string) => `信号状态：${status}`,
    signalFailed: (reason: string) => `信号生成失败${reason ? `：${reason}` : ""}`,
    createExecution: "创建计划",
    creatingExecution: "创建中...",
    executionCreated: (status: string) => `执行计划状态：${status}`,
    executionFailed: (reason: string) => `执行失败${reason ? `：${reason}` : ""}`,
    processPending: "处理待执行",
    processingPending: "处理中...",
    processOk: (filled: number, blocked: number) => `处理完成：${filled} 已成交，${blocked} 阻塞`,
    latestExecution: "最新执行",
    noExecution: "尚无执行计划",
    planFirst: "请先创建待执行计划。",
    pause: "暂停",
    resume: "恢复",
    stop: "停止",
    actionFailed: (reason: string) => `状态切换失败${reason ? `：${reason}` : ""}`,
    noSleeves: "暂无正式模拟策略。待恢复启用、手动实验仓和历史测试仓会在下方分别显示。",
    latestSignal: "最新信号",
    runtimeDetails: "运行详情 / 操作",
    targetWeights: "目标权重",
    proposedOrders: (count: number) => `${count} 笔建议订单`,
    orderCount: (count: number) => `${count} 笔订单`,
    fillCount: (count: number) => `${count} 笔成交`,
    noSignal: "尚未生成信号",
    noOrders: "无建议订单",
    blocked: "阻塞",
    warnings: "警告",
    modeHelp: "划拨现金模式会从手动现金通道移出资金；仅信号模式不会。",
    staleConfig: "配置缺失",
    historicalConfig: "历史配置：代码版本已变化，仅供查看，不能用来开仓",
    unavailableConfig: "配置无法读取：原件缺失、无效或不可读",
  },
} as const;

const inputClass =
  "rounded-lg border border-border-subtle bg-bg-base px-3 py-2 font-data-mono text-text-primary outline-none transition-colors focus:border-info";
const labelClass = "flex flex-col gap-1 font-body-sm text-text-primary";
const secondaryButtonClass =
  "inline-flex h-8 items-center justify-center gap-2 rounded-lg border border-border-subtle bg-bg-surface-muted px-3 font-body-sm text-text-primary transition-colors hover:bg-bg-surface disabled:cursor-not-allowed disabled:opacity-50";

export function PaperStrategySleevesPanel({
  locale = "en",
  configs,
  unavailableConfigs = [],
  sleeves,
  sleeveDetails,
  strategies,
  accountAvailableCash,
  accountDown,
}: {
  locale?: Locale;
  configs: PaperStrategyConfigResponse[];
  unavailableConfigs?: PaperStrategyConfigsResponse["unavailable_configs"];
  sleeves: PaperStrategySleeveResponse[];
  sleeveDetails: PaperStrategySleeveDetailResponse[];
  strategies: StrategyMetadata[];
  accountAvailableCash: number | null;
  accountDown: boolean;
}) {
  const text = copy[locale];
  const router = useRouter();
  const isHydrated = useIsHydrated();
  const usableConfigs = useMemo(
    () =>
      configs.filter(
        (config) =>
          config.source_status !== "historical_mismatch" &&
          config.metadata?.fossil !== true && config.metadata?.official_observation !== false,
      ),
    [configs],
  );
  const {
    official: officialSleeves,
    pending: pendingSleeves,
    manual: manualSleeves,
    historical: historicalSleeves,
    officialInitialCash,
    officialAvailableCash,
  } = useMemo(() => partitionStrategySleeves(sleeves), [sleeves]);
  // Fail-closed: a null available-cash (paper account API errored and returned
  // the $1M fallback) is treated exactly like accountDown — show "--" and block
  // cash-mode sleeve creation rather than trusting the synthetic figure.
  const cashUnavailable = accountDown || accountAvailableCash === null;
  const strategyOptions = strategies.filter((strategy) => strategy.result_type === "backtest");
  const defaultStrategyId = strategyOptions[0]?.id ?? "cross_sectional_top_n";
  const [strategyId, setStrategyId] = useState(defaultStrategyId);
  const [configName, setConfigName] = useState(
    locale === "zh" ? "动量策略仓配置" : "Momentum sleeve config",
  );
  const [symbols, setSymbols] = useState("SPY,QQQ,IWM,DIA");
  const [lookback, setLookback] = useState(20);
  const [topN, setTopN] = useState(3);
  const [provider, setProvider] = useState<"futu" | "tiingo">("futu");
  const [selectedConfigId, setSelectedConfigId] = useState(
    usableConfigs[0]?.strategy_config_id ?? "",
  );
  const [mode, setMode] = useState<PaperStrategySleeveMode>("signal_only");
  const [allocatedCash, setAllocatedCash] = useState(100_000);
  const [historyDays, setHistoryDays] = useState(180);

  const effectiveStrategyId = strategyId || defaultStrategyId;
  const effectiveSelectedConfigId =
    usableConfigs.find((config) => config.strategy_config_id === selectedConfigId)?.strategy_config_id
    ?? usableConfigs[0]?.strategy_config_id ?? "";
  const configById = useMemo(
    () => new Map(configs.map((config) => [config.strategy_config_id, config])),
    [configs],
  );
  const detailBySleeve = useMemo(
    () => new Map(sleeveDetails.map((detail) => [detail.sleeve.sleeve_id, detail])),
    [sleeveDetails],
  );
  const configNameConflict = hasStrategyConfigNameConflict(configName, configs);

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
      setConfigName(
        suggestNextStrategyConfigName(payload.config.name, [...configs, payload.config]),
      );
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

  const createExecutionMutation = useMutation({
    mutationFn: ({ sleeveId, signalId }: { sleeveId: string; signalId: string }) =>
      apiPost<PaperStrategyExecutionMutationResponse>(
        `/api/paper/strategy-sleeves/${encodeURIComponent(sleeveId)}/executions`,
        { signal_id: signalId, execution_window: "next_open" },
      ),
    onSuccess: (payload) => {
      toast.success(text.executionCreated(payload.execution.status));
      router.refresh();
    },
    onError: (error) => {
      toast.error(text.executionFailed(apiErrorMessage(error)));
    },
  });

  const processExecutionMutation = useMutation({
    mutationFn: (sleeveId: string) =>
      apiPost<PaperStrategyExecutionProcessResponse>(
        "/api/paper/strategy-sleeves/executions/process",
        { sleeve_id: sleeveId, execution_window: "next_open", limit: 10 },
      ),
    onSuccess: (payload) => {
      toast.success(text.processOk(payload.filled_count, payload.blocked_count));
      router.refresh();
    },
    onError: (error) => {
      toast.error(text.executionFailed(apiErrorMessage(error)));
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
    !configNameConflict &&
    !createConfigMutation.isPending;
  const canCreateSleeve =
    isHydrated &&
    effectiveSelectedConfigId.length > 0 &&
    !createSleeveMutation.isPending &&
    (mode === "signal_only" || (!cashUnavailable && allocatedCash > 0));

  return (
    <Card padded={false}>
      <details data-paper-strategy-sleeves="collapsed-by-default">
        <summary className="cursor-pointer list-none p-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info">
          <span className="flex flex-wrap items-start justify-between gap-3">
            <span className="min-w-0">
              <span className="flex items-center gap-2 font-headline-lg text-text-primary">
                <WalletCards className="text-info" size={18} />
                {text.title}
              </span>
              <span className="mt-1 block max-w-3xl font-body-sm text-text-secondary">
                {text.desc}
              </span>
            </span>
            <span className="flex flex-wrap gap-2">
              <StatusPill label={text.officialSleeves} value={officialSleeves.length} tone="success" />
              <StatusPill label={text.pendingSleeves} value={pendingSleeves.length} tone="warning" />
              <StatusPill label={text.manualSleeves} value={manualSleeves.length} tone="info" />
              <StatusPill label={text.historicalSleeves} value={historicalSleeves.length} tone="neutral" />
            </span>
          </span>
        </summary>

        <div className="border-t border-border-subtle p-4">
          {configs.filter((config) => config.source_status === "historical_mismatch").map((config) => (
            <p key={config.strategy_config_id} className="mb-3 rounded-lg border border-warning/30 p-3 font-body-sm text-warning">
              {strategyConfigDisplayName(config.name, locale)} · v{config.version} — {text.historicalConfig}
              <span className="mt-1 block font-mono text-xs">{config.source_error}</span>
            </p>
          ))}
          {unavailableConfigs.map((config) => (
            <p key={config.strategy_config_id} className="mb-3 rounded-lg border border-warning/30 p-3 font-body-sm text-warning">
              {text.unavailableConfig}
              <span className="mt-1 block break-all font-mono text-xs">
                {config.strategy_config_id}{config.version == null ? "" : ` · v${config.version}`} · {config.reason}
              </span>
            </p>
          ))}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <MetricStat label={text.initialCash} value={formatMoney(officialInitialCash)} />
            <MetricStat label={text.availableCash} value={formatMoney(officialAvailableCash)} />
            <MetricStat
              label={text.strategyEquity}
              value={text.equityUnavailable}
              tone="warning"
              hint={text.equityUnavailable}
            />
            <MetricStat
              label={text.manualCash}
              value={cashUnavailable ? "--" : formatMoney(accountAvailableCash)}
              tone={cashUnavailable ? "warning" : "neutral"}
            />
          </div>

      <details className="mt-4 rounded-lg border border-border-subtle bg-bg-surface">
        <summary className="cursor-pointer select-none px-4 py-3 font-body-sm text-text-secondary">
          {text.labSummary}
        </summary>
        <div className="grid grid-cols-1 gap-4 px-4 pb-4 xl:grid-cols-[1.1fr_0.9fr]">
        <section className="rounded-lg border border-border-subtle bg-bg-surface p-4">
          <div className="mb-3 flex items-center gap-2">
            <Plus size={15} className="text-info" />
            <h3 className="font-label-caps text-text-primary">{text.configTitle}</h3>
          </div>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <label className={labelClass}>
              {text.name}
              <input
                className={inputClass}
                value={configName}
                onChange={(event) => setConfigName(event.target.value)}
              />
              {configNameConflict ? (
                <span className="font-body-sm text-warning">{text.duplicateConfigName}</span>
              ) : null}
            </label>
            <label className={labelClass}>
              {text.strategy}
              <select className={inputClass} value={effectiveStrategyId} onChange={(event) => setStrategyId(event.target.value)}>
                {strategyOptions.map((strategy) => (
                  <option key={strategy.id} value={strategy.id}>
                    {locale === "zh" ? strategy.display_name_zh ?? strategy.name : strategy.name}
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
            <TerminalToolbarButton
              className="self-end"
              disabled={!canCreateConfig}
              onClick={() => createConfigMutation.mutate()}
              tone="info"
            >
              {createConfigMutation.isPending ? text.creatingConfig : text.createConfig}
            </TerminalToolbarButton>
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
                disabled={usableConfigs.length === 0}
                value={effectiveSelectedConfigId}
                onChange={(event) => setSelectedConfigId(event.target.value)}
              >
                {usableConfigs.map((config) => (
                  <option key={`${config.strategy_config_id}-${config.version}`} value={config.strategy_config_id}>
                    {formatStrategyConfigOptionLabel(config, usableConfigs).replace(
                      config.name,
                      strategyConfigDisplayName(config.name, locale),
                    )}
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
            <p className="font-body-sm text-text-secondary">{usableConfigs.length ? text.modeHelp : text.noConfig}</p>
            <TerminalToolbarButton
              className="w-full"
              disabled={!canCreateSleeve}
              onClick={() => createSleeveMutation.mutate()}
              tone="success"
            >
              {createSleeveMutation.isPending ? text.openingSleeve : text.openSleeve}
            </TerminalToolbarButton>
          </div>
        </section>
        </div>
      </details>

      <section className="mt-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h3 className="flex items-center gap-2 font-label-caps text-text-primary">
            <Activity size={15} className="text-info" />
            {text.officialSleeves}
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
        {officialSleeves.length === 0 ? (
          <p className="rounded-lg border border-border-subtle bg-bg-surface p-4 text-center font-body-sm text-text-secondary">
            {text.noSleeves}
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-3 2xl:grid-cols-2">
            {officialSleeves.map((sleeve) => {
              const config = configById.get(sleeve.strategy_config_id);
              const boundConfig =
                config?.version === sleeve.strategy_config_version ? config : undefined;
              const detail = detailBySleeve.get(sleeve.sleeve_id);
              const latestSignal = latestByGeneratedAt(detail?.signals ?? []);
              const latestExecution = latestByUpdatedAt(detail?.executions ?? []);
              const duePendingExecution = latestDuePendingExecution(detail?.executions ?? []);
              const isGenerating = generateSignalMutation.isPending && generateSignalMutation.variables === sleeve.sleeve_id;
              const isCreatingExecution =
                createExecutionMutation.isPending &&
                createExecutionMutation.variables?.sleeveId === sleeve.sleeve_id;
              const isProcessingExecution =
                processExecutionMutation.isPending &&
                processExecutionMutation.variables === sleeve.sleeve_id;
              const isStatusChanging =
                statusMutation.isPending && statusMutation.variables?.sleeveId === sleeve.sleeve_id;
              return (
                <SleeveRow
                  config={boundConfig}
                  runtime={detail?.runtime_status}
                  isCreatingExecution={isCreatingExecution}
                  isGenerating={isGenerating}
                  isProcessingExecution={isProcessingExecution}
                  isStatusChanging={isStatusChanging}
                  duePendingExecution={duePendingExecution}
                  latestExecution={latestExecution}
                  key={sleeve.sleeve_id}
                  latestSignal={latestSignal}
                  locale={locale}
                  onCreateExecution={() => {
                    if (latestSignal) {
                      createExecutionMutation.mutate({
                        sleeveId: sleeve.sleeve_id,
                        signalId: latestSignal.signal_id,
                      });
                    }
                  }}
                  onGenerate={() => generateSignalMutation.mutate(sleeve.sleeve_id)}
                  onProcessExecution={() => processExecutionMutation.mutate(sleeve.sleeve_id)}
                  onStatus={(action) => statusMutation.mutate({ sleeveId: sleeve.sleeve_id, action })}
                  sleeve={sleeve}
                  text={text}
                />
              );
            })}
          </div>
        )}
      </section>

      <AuxiliarySleeveGroup
        configs={configById}
        description={text.pendingDesc}
        fallbackName={locale === "zh" ? "待恢复启用" : "Pending activation recovery"}
        locale={locale}
        sleeves={pendingSleeves}
        text={text}
        title={text.pendingSleeves}
        tone="warning"
      />
      <AuxiliarySleeveGroup
        configs={configById}
        description={text.manualDesc}
        fallbackName={locale === "zh" ? "手动实验策略" : "Manual lab strategy"}
        locale={locale}
        sleeves={manualSleeves}
        text={text}
        title={text.manualSleeves}
        tone="info"
      />
      <AuxiliarySleeveGroup
        configs={configById}
        description={text.historicalDesc}
        fallbackName={locale === "zh" ? "历史测试策略" : "Historical test strategy"}
        locale={locale}
        sleeves={historicalSleeves}
        text={text}
        title={text.historicalSleeves}
        tone="neutral"
      />
        </div>
      </details>
    </Card>
  );
}

function AuxiliarySleeveGroup({
  configs,
  description,
  fallbackName,
  locale,
  sleeves,
  text,
  title,
  tone,
}: {
  configs: Map<string, PaperStrategyConfigResponse>;
  description: string;
  fallbackName: string;
  locale: Locale;
  sleeves: PaperStrategySleeveResponse[];
  text: (typeof copy)["en"] | (typeof copy)["zh"];
  title: string;
  tone: "warning" | "info" | "neutral";
}) {
  if (!sleeves.length) return null;
  return (
    <details className="mt-4 rounded-lg border border-border-subtle bg-bg-surface-muted/30">
      <summary className="cursor-pointer select-none px-4 py-3 font-label-caps text-text-secondary">
        {title} · {sleeves.length}
      </summary>
      <div className="border-t border-border-subtle p-4">
        <p className="mb-3 font-body-sm text-text-secondary">{description}</p>
        <div className="grid grid-cols-1 gap-2 2xl:grid-cols-2">
          {sleeves.map((sleeve) => {
            const config = configs.get(sleeve.strategy_config_id);
            const factorId = config?.factor_ids[0];
            const name = strategySleeveDisplayName(
              sleeve,
              factorId,
              locale === "zh" ? fallbackName : config?.name ?? fallbackName,
              locale,
            );
            return (
              <article
                className="rounded-lg border border-border-subtle bg-bg-surface p-3"
                key={sleeve.sleeve_id}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h4 className="font-body-sm font-semibold text-text-primary">{name}</h4>
                    <p className="mt-1 font-body-sm text-text-secondary">
                      {strategySleeveStatusLabel(sleeve.status, locale)} · {text.availableCash}{" "}
                      {formatMoney(sleeve.cash)}
                    </p>
                  </div>
                  <StatusPill
                    label=""
                    value={strategySleeveStatusLabel(sleeve.status, locale)}
                    tone={tone}
                  />
                </div>
                <details className="mt-2 font-body-sm text-text-secondary">
                  <summary className="cursor-pointer">{text.technical}</summary>
                  <p className="mt-1 break-all font-data-mono text-[10px]">{sleeve.sleeve_id}</p>
                  {factorId ? (
                    <p className="break-all font-data-mono text-[10px]">{factorId}</p>
                  ) : null}
                </details>
              </article>
            );
          })}
        </div>
      </div>
    </details>
  );
}

function SleeveRow({
  config,
  runtime,
  isCreatingExecution,
  isGenerating,
  isProcessingExecution,
  isStatusChanging,
  duePendingExecution,
  latestExecution,
  latestSignal,
  locale,
  onCreateExecution,
  onGenerate,
  onProcessExecution,
  onStatus,
  sleeve,
  text,
}: {
  config?: PaperStrategyConfigResponse;
  runtime?: PaperStrategySleeveDetailResponse["runtime_status"];
  isCreatingExecution: boolean;
  isGenerating: boolean;
  isProcessingExecution: boolean;
  isStatusChanging: boolean;
  duePendingExecution?: PaperStrategyExecutionPlanResponse;
  latestExecution?: PaperStrategyExecutionPlanResponse;
  latestSignal?: PaperStrategySignalResponse;
  locale: Locale;
  onCreateExecution: () => void;
  onGenerate: () => void;
  onProcessExecution: () => void;
  onStatus: (action: SleeveAction) => void;
  sleeve: PaperStrategySleeveResponse;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
}) {
  const tone =
    sleeve.status === "running" ? runtime?.configuration.status === "blocked" ? "warning" : "info" : sleeve.status === "paused" ? "warning" : "danger";
  const latestTargets = latestSignal
    ? Object.entries(latestSignal.target_weights)
        .sort(([, a], [, b]) => b - a)
        .slice(0, 4)
        .map(([symbol, weight]) => `${symbol} ${(weight * 100).toFixed(0)}%`)
        .join(" · ")
    : "";
  const proposedOrders = latestSignal?.proposed_orders.length ?? 0;
  const factorId = config?.factor_ids[0];
  const displayName = strategySleeveDisplayName(
    sleeve,
    factorId,
    locale === "zh" ? "正式模拟策略" : config?.name ?? text.staleConfig,
    locale,
  );
  const canCreateExecution =
    sleeve.mode === "allocated" &&
    sleeve.status === "running" &&
    latestSignal?.status === "generated" &&
    proposedOrders > 0 &&
    latestExecution?.signal_id !== latestSignal.signal_id &&
    !isCreatingExecution;
  const canProcessExecution =
    sleeve.mode === "allocated" &&
    sleeve.status === "running" &&
    duePendingExecution !== undefined &&
    !isProcessingExecution;

  return (
    <div className="rounded-lg border border-border-subtle bg-bg-surface p-4 transition-colors hover:bg-bg-surface-muted/30">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate font-data-mono text-sm font-bold text-text-primary">
              {displayName}
            </span>
            <ToneBadge tone={tone}>{sleeve.status === "running" ? paperRuntimeLabel(runtime, locale) : strategySleeveStatusLabel(sleeve.status, locale)}</ToneBadge>
            <ToneBadge tone={sleeve.mode === "allocated" ? "success" : "info"}>
              {strategySleeveModeLabel(sleeve.mode, locale)}
            </ToneBadge>
          </div>
          <p className="mt-1 break-all font-data-mono text-xs text-text-secondary">
            {locale === "zh" ? "策略仓" : "Sleeve"} · {sleeve.sleeve_id}
          </p>
          <details className="mt-1 font-body-sm text-text-secondary">
            <summary className="cursor-pointer select-none">{text.technical}</summary>
            <p className="break-all font-data-mono text-[10px]">{sleeve.sleeve_id}</p>
            {factorId ? <p className="break-all font-data-mono text-[10px]">{factorId}</p> : null}
          </details>
        </div>
        <div className="text-right font-data-mono text-sm text-text-primary">
          {formatMoney(sleeve.cash)}
          <div className="text-[10px] text-text-secondary">{text.availableCash}</div>
        </div>
      </div>

      <PaperRuntimeEvidence runtime={runtime} locale={locale}/>
      <details className="mt-3 rounded-lg border border-border-subtle bg-bg-base">
        <summary className="cursor-pointer select-none px-3 py-2 font-label-caps text-text-secondary">
          {text.runtimeDetails}
        </summary>
        <div className="border-t border-border-subtle p-3">
      <div className="rounded-lg border border-border-subtle bg-bg-surface p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="font-label-caps text-text-secondary">{text.latestSignal}</span>
          {latestSignal ? (
            <ToneBadge tone={signalTone(latestSignal.status)}>
              {signalStatusLabel(latestSignal.status, locale)}
            </ToneBadge>
          ) : null}
        </div>
        {latestSignal ? (
          <div className="mt-2 space-y-1 font-data-mono text-xs text-text-secondary">
            <p>{formatShortDate(latestSignal.generated_at)}</p>
            <p>
              {text.targetWeights}: {latestTargets || "--"}
            </p>
            <p>
              {proposedOrders > 0 ? text.proposedOrders(proposedOrders) : text.noOrders}
              {latestSignal.execution_blocked_reason
                ? ` · ${text.blocked}: ${strategyReasonLabel(latestSignal.execution_blocked_reason, locale)}`
                : ""}
            </p>
            {latestSignal.warnings.length ? (
              <p className="text-warning">
                {text.warnings}: {latestSignal.warnings.map((warning) => strategyReasonLabel(warning, locale)).join(" · ")}
              </p>
            ) : null}
          </div>
        ) : (
          <p className="mt-2 font-body-sm text-text-secondary">{text.noSignal}</p>
        )}
      </div>

      <div className="mt-3 rounded-lg border border-border-subtle bg-bg-base p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="font-label-caps text-text-secondary">{text.latestExecution}</span>
          {latestExecution ? (
            <ToneBadge tone={executionTone(latestExecution.status)}>
              {executionStatusLabel(latestExecution.status, locale)}
            </ToneBadge>
          ) : null}
        </div>
        {latestExecution ? (
          <div className="mt-2 grid grid-cols-1 gap-2 font-data-mono text-xs text-text-secondary sm:grid-cols-3">
            <span>{formatShortDate(latestExecution.updated_at)}</span>
            <span>{executionWindowLabel(latestExecution.execution_window, locale)}</span>
            <span>{latestExecution.target_date ?? "--"}</span>
            <span>{text.orderCount(latestExecution.orders.length)}</span>
            <span>{text.fillCount(latestExecution.fills.length)}</span>
            <span>
              {latestExecution.blocked_reason
                ? strategyReasonLabel(latestExecution.blocked_reason, locale)
                : "--"}
            </span>
          </div>
        ) : (
          <p className="mt-2 font-body-sm text-text-secondary">{text.noExecution}</p>
        )}
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <TerminalToolbarButton
          disabled={isGenerating || sleeve.status === "stopped"}
          onClick={onGenerate}
          tone="info"
        >
          <RefreshCw size={14} />
          {isGenerating ? text.generatingSignal : text.generateSignal}
        </TerminalToolbarButton>
        <TerminalToolbarButton
          disabled={!canCreateExecution}
          onClick={onCreateExecution}
          title={!latestSignal ? text.planFirst : undefined}
          tone="info"
        >
          <Send size={14} />
          {isCreatingExecution ? text.creatingExecution : text.createExecution}
        </TerminalToolbarButton>
        <TerminalToolbarButton
          disabled={!canProcessExecution}
          onClick={onProcessExecution}
          tone="success"
        >
          <CheckCircle2 size={14} />
          {isProcessingExecution ? text.processingPending : text.processPending}
        </TerminalToolbarButton>
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
        <TerminalToolbarButton
          disabled={isStatusChanging || sleeve.status === "stopped"}
          onClick={() => onStatus("stop")}
          tone="danger"
        >
          <Square size={14} />
          {text.stop}
        </TerminalToolbarButton>
      </div>
        </div>
      </details>
    </div>
  );
}

function latestByGeneratedAt(signals: PaperStrategySignalResponse[]) {
  return [...signals].sort((a, b) => b.generated_at.localeCompare(a.generated_at))[0];
}

function latestByUpdatedAt(executions: PaperStrategyExecutionPlanResponse[]) {
  return [...executions].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
}

function latestDuePendingExecution(executions: PaperStrategyExecutionPlanResponse[]) {
  const currentDate = localIsoDate();
  return executions
    .filter(
      (execution) =>
        execution.status === "pending" &&
        execution.execution_window === "next_open" &&
        execution.target_date === currentDate,
    )
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
}

function localIsoDate(value = new Date()) {
  const localTime = value.getTime() - value.getTimezoneOffset() * 60_000;
  return new Date(localTime).toISOString().slice(0, 10);
}

function signalTone(status: PaperStrategySignalResponse["status"]) {
  if (status === "generated") return "success";
  if (status === "data_unavailable") return "warning";
  return "danger";
}

function executionTone(status: PaperStrategyExecutionPlanResponse["status"]) {
  if (status === "filled") return "success";
  if (status === "pending") return "info";
  if (status === "blocked" || status === "failed") return "danger";
  return "warning";
}

function signalStatusLabel(
  status: PaperStrategySignalResponse["status"],
  locale: Locale,
) {
  const labels = {
    en: { generated: "Generated", data_unavailable: "Data unavailable", invalid: "Invalid" },
    zh: { generated: "已生成", data_unavailable: "数据不可用", invalid: "无效" },
  } as const;
  return labels[locale][status];
}

function executionStatusLabel(
  status: PaperStrategyExecutionPlanResponse["status"],
  locale: Locale,
) {
  const labels: Record<Locale, Record<PaperStrategyExecutionPlanResponse["status"], string>> = {
    en: {
      pending: "Pending",
      filled: "Filled",
      partially_filled: "Partially filled",
      skipped: "Skipped",
      blocked: "Blocked",
      missed_window: "Missed window",
      failed: "Failed",
      cancelled: "Cancelled",
    },
    zh: {
      pending: "等待定时处理",
      filled: "已成交",
      partially_filled: "部分成交",
      skipped: "已跳过",
      blocked: "已阻塞",
      missed_window: "已错过窗口",
      failed: "失败",
      cancelled: "已取消",
    },
  };
  return labels[locale][status];
}

function executionWindowLabel(window: string, locale: Locale) {
  if (window === "next_open") {
    return locale === "zh" ? "下一交易日开盘" : "Next market open";
  }
  return locale === "zh" ? "执行窗口待确认" : window;
}

function strategyReasonLabel(reason: string, locale: Locale) {
  if (locale === "en") return reason;
  const labels: Record<string, string> = {
    signal_data_unavailable: "信号数据不可用",
    data_unavailable: "数据不可用",
    paper_execution_disabled: "模拟执行当前关闭",
    sleeve_not_running: "策略仓未处于运行状态",
    no_target_weights: "没有可执行的目标权重",
    no_proposed_orders: "没有建议订单",
    pending_next_open: "等待下一交易日开盘处理",
  };
  return labels[reason] ?? "存在技术原因，请展开技术信息核对。";
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
