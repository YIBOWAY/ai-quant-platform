import { splitSymbols } from "./apiClient";

export type ExperimentProvider = "sample" | "futu" | "tiingo";

export type ExperimentRunFormPayloadValues = {
  symbols: string;
  start: string;
  end: string;
  provider: ExperimentProvider;
  lookbacks: string;
  top_ns: string;
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
