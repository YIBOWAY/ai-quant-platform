import { splitSymbols } from "./apiClient";

export type ExperimentProvider = "sample" | "futu" | "tiingo";

export type ExperimentRunFormPayloadValues = {
  symbols: string;
  start: string;
  end: string;
  provider: ExperimentProvider;
  lookbacks: string;
  top_ns: string;
  walk_forward_enabled: boolean;
  walk_forward_train_bars: number;
  walk_forward_validation_bars: number;
  walk_forward_step_bars: number;
  initial_cash: number;
  commission_bps: number;
  slippage_bps: number;
};

export function buildExperimentRunPayload(values: ExperimentRunFormPayloadValues) {
  return {
    symbols: splitSymbols(values.symbols),
    start: values.start,
    end: values.end,
    provider: values.provider,
    lookbacks: splitPositiveInts(values.lookbacks),
    top_ns: splitPositiveInts(values.top_ns),
    walk_forward: {
      enabled: values.walk_forward_enabled,
      train_bars: values.walk_forward_train_bars,
      validation_bars: values.walk_forward_validation_bars,
      step_bars: values.walk_forward_step_bars,
    },
    initial_cash: values.initial_cash,
    commission_bps: values.commission_bps,
    slippage_bps: values.slippage_bps,
  };
}

export function providerFromExperimentSource(source: string | null | undefined): ExperimentProvider {
  const normalized = (source ?? "").toLowerCase();
  if (normalized.startsWith("tiingo")) {
    return "tiingo";
  }
  if (normalized.startsWith("futu")) {
    return "futu";
  }
  return "sample";
}

function splitPositiveInts(value: string) {
  return value
    .split(",")
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isInteger(item) && item > 0);
}
