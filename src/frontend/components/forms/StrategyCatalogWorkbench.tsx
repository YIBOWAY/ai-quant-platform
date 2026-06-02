'use client';

import Link from "next/link";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { DataPreviewTable } from "@/components/DataPreviewTable";
import type {
  FactorMetadata,
  PreviewRecord,
  StrategyMetadata,
  UniverseDefinition,
} from "@/lib/api";
import { ApiClientError, apiPost } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";
import { localizePath, type Locale } from "@/lib/locale";
import { FutuUnavailableHint, futuOptionLabel } from "./FutuProviderHint";

type StrategyCatalogWorkbenchProps = {
  strategies: StrategyMetadata[];
  universes: UniverseDefinition[];
  factors: FactorMetadata[];
  locale: Locale;
  futuReachable?: boolean;
};

const copy = {
  en: {
    title: "Strategy Catalog",
    subtitle: "Registered research strategies. Adding a backend strategy adds a catalog entry here.",
    source: "Paper source",
    parameters: "Parameters",
    run: "Run Strategy",
    running: "Running...",
    result: "Result",
    openBacktest: "Open backtest",
    noResult: "Run a strategy to see the response.",
    provider: "Provider",
    weights: "Weights",
    strategy: "Strategy",
    runsInBacktester: "Also available in the dedicated Backtester",
    catalogOnly: "Replication · runs from this catalog only",
  },
  zh: {
    title: "策略目录",
    subtitle: "后端已登记的研究策略。新增后端策略后，这里会自动出现目录项。",
    source: "论文出处",
    parameters: "参数",
    run: "运行策略",
    running: "运行中...",
    result: "结果",
    openBacktest: "打开回测",
    noResult: "运行策略后会显示结果。",
    provider: "数据源",
    weights: "权重",
    strategy: "策略",
    runsInBacktester: "同时可在独立的回测器中运行",
    catalogOnly: "研报复现 · 仅在本目录运行",
  },
} as const;

const fieldLabels = {
  en: {
    universe_id: "Universe",
    factor_ids: "Factors",
    weights: "Weights",
    top_n: "Top N",
    benchmark_symbol: "Benchmark",
    start: "Start Date",
    end: "End Date",
    provider: "Provider",
    symbols: "Symbols",
    initial_cash: "Initial Cash",
  },
  zh: {
    universe_id: "股票池",
    factor_ids: "因子",
    weights: "权重",
    top_n: "Top N",
    benchmark_symbol: "基准",
    start: "开始日期",
    end: "结束日期",
    provider: "数据源",
    symbols: "标的",
    initial_cash: "初始资金",
  },
} as const;

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };

export function StrategyCatalogWorkbench({
  strategies,
  universes,
  factors,
  locale,
  futuReachable = true,
}: StrategyCatalogWorkbenchProps) {
  const text = copy[locale];
  const isHydrated = useIsHydrated();
  const activeStrategies = strategies.length ? strategies : fallbackStrategies();
  const [strategyId, setStrategyId] = useState(activeStrategies[0]?.id ?? "");
  const strategy = activeStrategies.find((item) => item.id === strategyId) ?? activeStrategies[0];
  const [values, setValues] = useState<Record<string, unknown>>(strategy?.default_payload ?? {});
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const fields = useMemo(
    () => strategy?.parameter_schema?.fields ?? {},
    [strategy],
  );

  function chooseStrategy(nextId: string) {
    const nextStrategy = activeStrategies.find((item) => item.id === nextId);
    setStrategyId(nextId);
    setValues(nextStrategy?.default_payload ?? {});
    setResult(null);
    setError(null);
  }

  async function submit() {
    if (!strategy) {
      return;
    }
    setPending(true);
    setError(null);
    try {
      const payload = buildPayload(fields, values);
      // Backtest-engine strategies dispatch on strategy_id; the schema fields
      // do not include it, so inject it for backtest result types. Replication
      // endpoints have their own contract and ignore it.
      if (strategy.result_type === "backtest") {
        payload.strategy_id = strategy.id;
      }
      const response = await apiPost<Record<string, unknown>>(strategy.run_endpoint, payload);
      setResult(response);
      toast.success(`${strategy.name} finished`);
    } catch (requestError) {
      setError(
        requestError instanceof ApiClientError
          ? requestError.message
          : requestError instanceof Error
            ? requestError.message
            : "Request failed",
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="flex h-full min-h-0 bg-base">
      <aside className="flex h-full w-[360px] shrink-0 flex-col overflow-y-auto border-r border-border-subtle bg-bg-surface p-4">
        <h2 className="font-headline-lg text-text-primary">{text.title}</h2>
        <p className="mt-2 font-body-sm text-text-secondary">{text.subtitle}</p>

        <label className="mt-5 flex flex-col gap-1 font-body-sm text-text-primary">
          {text.strategy}
          <select
            className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary"
            disabled={!isHydrated || pending}
            onChange={(event) => chooseStrategy(event.target.value)}
            value={strategy?.id ?? ""}
          >
            {activeStrategies.map((item) => (
              <option key={item.id} value={item.id} style={optionStyle}>
                {item.name}
              </option>
            ))}
          </select>
        </label>

        {strategy ? (
          <section className="mt-4 rounded border border-border-subtle bg-surface-muted p-3">
            <div className="font-label-caps text-text-secondary">{text.source}</div>
            <p className="mt-2 font-body-sm text-text-primary">
              {strategy.paper_source ?? strategy.description}
            </p>
            <div
              className={`mt-3 inline-flex rounded border px-2 py-1 font-data-mono text-[10px] uppercase ${
                strategy.result_type === "backtest"
                  ? "border-accent-success/40 bg-accent-success/10 text-accent-success"
                  : "border-info/40 bg-info/10 text-info"
              }`}
            >
              {strategy.result_type === "backtest" ? text.runsInBacktester : text.catalogOnly}
            </div>
          </section>
        ) : null}

        <section className="mt-4 flex flex-col gap-3 rounded border border-border-subtle bg-surface-muted p-3">
          <div className="font-label-caps text-text-secondary">{text.parameters}</div>
          {Object.entries(fields).map(([fieldName, schema]) => (
            <FieldRenderer
              factors={factors}
              fieldName={fieldName}
              key={fieldName}
              schema={schema}
              disabled={!isHydrated || pending}
              setValues={setValues}
              locale={locale}
              universes={universes}
              values={values}
              futuReachable={futuReachable}
            />
          ))}
          {error ? <p className="font-body-sm text-danger">{error}</p> : null}
          <button
            className="rounded bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!isHydrated || pending}
            onClick={() => void submit()}
            type="button"
          >
            {pending ? text.running : text.run}
          </button>
        </section>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
        <section className="rounded border border-border-subtle bg-bg-surface p-4">
          <h1 className="font-headline-lg text-text-primary">{strategy?.name ?? text.title}</h1>
          <p className="mt-2 max-w-3xl font-body-sm text-text-secondary">
            {strategy?.description}
          </p>
          {result?.run_id ? (
            <Link
              className="mt-4 inline-flex rounded border border-border-subtle px-3 py-2 font-body-sm text-info"
              href={localizePath(`/backtest/${String(result.run_id)}`, locale)}
            >
              {text.openBacktest}
            </Link>
          ) : null}
        </section>

        {result ? (
          <DataPreviewTable
            columns={["key", "value"]}
            description={strategy?.run_endpoint ?? ""}
            emptyDescription={text.noResult}
            emptyTitle={text.result}
            rows={flattenResult(result)}
            title={text.result}
          />
        ) : (
          <div className="rounded border border-border-subtle bg-bg-surface p-6 font-body-sm text-text-secondary">
            {text.noResult}
          </div>
        )}
      </section>
    </main>
  );
}

function FieldRenderer({
  factors,
  fieldName,
  schema,
  disabled,
  setValues,
  locale,
  universes,
  values,
  futuReachable = true,
}: {
  factors: FactorMetadata[];
  fieldName: string;
  schema: Record<string, unknown>;
  disabled: boolean;
  setValues: (updater: (current: Record<string, unknown>) => Record<string, unknown>) => void;
  locale: Locale;
  universes: UniverseDefinition[];
  values: Record<string, unknown>;
  futuReachable?: boolean;
}) {
  const type = String(schema.type ?? "text");
  if (type === "universe") {
    return (
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {label(fieldName, locale)}
        <select
          className="rounded border border-border-subtle bg-base px-3 py-2 font-data-mono text-text-primary"
          disabled={disabled}
          onChange={(event) => update(fieldName, event.target.value, setValues)}
          value={String(values[fieldName] ?? schema.default ?? universes[0]?.id ?? "etf")}
        >
          {universes.map((universe) => (
            <option key={universe.id} value={universe.id} style={optionStyle}>
              {universe.name}
            </option>
          ))}
        </select>
      </label>
    );
  }
  if (type === "provider") {
    return (
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {label(fieldName, locale)}
        <select
          className="rounded border border-border-subtle bg-base px-3 py-2 font-data-mono text-text-primary"
          disabled={disabled}
          onChange={(event) => update(fieldName, event.target.value, setValues)}
          value={String(values[fieldName] ?? schema.default ?? "futu")}
        >
          {["futu", "sample", "tiingo"].map((provider) => (
            <option
              key={provider}
              value={provider}
              style={optionStyle}
              disabled={provider === "futu" && !futuReachable}
            >
              {provider === "futu" ? futuOptionLabel(futuReachable, locale) : provider}
            </option>
          ))}
        </select>
        <FutuUnavailableHint reachable={futuReachable} locale={locale} />
      </label>
    );
  }
  if (type === "factor_multi_select") {
    const selected = asStringArray(values[fieldName] ?? schema.default);
    return (
      <div className="flex flex-col gap-2 font-body-sm text-text-primary">
        <div className="font-label-caps text-text-secondary">{label(fieldName, locale)}</div>
        {factors.map((factor) => (
          <label className="inline-flex items-center gap-2" key={factor.factor_id}>
            <input
              checked={selected.includes(factor.factor_id)}
              disabled={disabled}
              onChange={(event) => {
                const next = event.target.checked
                  ? [...selected, factor.factor_id]
                  : selected.filter((item) => item !== factor.factor_id);
                update(fieldName, next, setValues);
              }}
              type="checkbox"
            />
            {factor.factor_name}
          </label>
        ))}
      </div>
    );
  }
  if (type === "factor_weight_map") {
    const selected = asStringArray(values.factor_ids);
    const weights = (values[fieldName] as Record<string, unknown> | undefined) ?? {};
    return (
      <div className="flex flex-col gap-2 font-body-sm text-text-primary">
        <div className="font-label-caps text-text-secondary">{label(fieldName, locale)}</div>
        {selected.map((factorId) => (
          <label className="grid grid-cols-[1fr_96px] items-center gap-2" key={factorId}>
            <span>{factorId}</span>
            <input
              className="rounded border border-border-subtle bg-base px-2 py-1 font-data-mono text-text-primary"
              disabled={disabled}
              onChange={(event) =>
                update(fieldName, { ...weights, [factorId]: Number(event.target.value) }, setValues)
              }
              step="0.1"
              type="number"
              value={String(weights[factorId] ?? 1)}
            />
          </label>
        ))}
      </div>
    );
  }
  if (type === "symbol_list") {
    return (
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {label(fieldName, locale)}
        <textarea
          className="min-h-24 rounded border border-border-subtle bg-base px-3 py-2 font-data-mono text-text-primary"
          disabled={disabled}
          onChange={(event) => update(fieldName, event.target.value, setValues)}
          value={asStringArray(values[fieldName] ?? schema.default).join(",")}
        />
      </label>
    );
  }
  const inputType = type === "date" ? "date" : type === "number" || type === "integer" || type === "integer_or_null" ? "number" : "text";
  return (
    <label className="flex flex-col gap-1 font-body-sm text-text-primary">
      {label(fieldName, locale)}
      <input
        className="rounded border border-border-subtle bg-base px-3 py-2 font-data-mono text-text-primary"
        disabled={disabled}
        onChange={(event) => update(fieldName, event.target.value, setValues)}
        step={inputType === "number" ? "0.1" : undefined}
        type={inputType}
        value={String(values[fieldName] ?? schema.default ?? "")}
      />
    </label>
  );
}

function update(
  fieldName: string,
  value: unknown,
  setValues: (updater: (current: Record<string, unknown>) => Record<string, unknown>) => void,
) {
  setValues((current) => ({ ...current, [fieldName]: value }));
}

function buildPayload(fields: Record<string, Record<string, unknown>>, values: Record<string, unknown>) {
  const payload: Record<string, unknown> = {};
  for (const [fieldName, schema] of Object.entries(fields)) {
    const type = String(schema.type ?? "text");
    const raw = values[fieldName] ?? schema.default;
    if (type === "symbol_list") {
      payload[fieldName] = asStringArray(raw);
    } else if (type === "integer" || type === "number") {
      payload[fieldName] = Number(raw);
    } else if (type === "integer_or_null") {
      payload[fieldName] = raw === "" || raw === null || raw === undefined ? null : Number(raw);
    } else if (type === "factor_weight_map") {
      payload[fieldName] = raw ?? {};
    } else {
      payload[fieldName] = raw;
    }
  }
  return payload;
}

function asStringArray(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map(String).filter(Boolean);
  }
  if (typeof value === "string") {
    return value.split(",").map((item) => item.trim()).filter(Boolean);
  }
  return [];
}

function flattenResult(result: Record<string, unknown>): PreviewRecord[] {
  return Object.entries(result)
    .filter(([key]) => key !== "safety")
    .slice(0, 20)
    .map(([key, value]) => ({
      key,
      value: typeof value === "object" ? JSON.stringify(value) : String(value),
    }));
}

function label(fieldName: string, locale: Locale) {
  return (
    fieldLabels[locale][fieldName as keyof typeof fieldLabels.en] ??
    fieldName.replaceAll("_", " ")
  );
}

function fallbackStrategies(): StrategyMetadata[] {
  return [
    {
      id: "cross_sectional_top_n",
      name: "Cross-Sectional Top-N",
      description: "",
      paper_source: null,
      run_endpoint: "/api/backtests/run",
      result_type: "backtest",
      parameter_schema: { fields: {} },
      default_payload: {},
    },
  ];
}
