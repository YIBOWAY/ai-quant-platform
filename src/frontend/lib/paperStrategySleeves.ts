import type { PaperStrategyConfigResponse } from "./api";

function normalizeConfigName(name: string) {
  return name.trim().replace(/\s+/g, " ").toLocaleLowerCase();
}

function shortConfigId(strategyConfigId: string) {
  return strategyConfigId.replace(/^strategy-config-/, "").slice(0, 6);
}

function baseConfigOptionLabel(config: PaperStrategyConfigResponse) {
  return `${config.name} v${config.version}`;
}

export function formatStrategyConfigOptionLabel(
  config: PaperStrategyConfigResponse,
  configs: PaperStrategyConfigResponse[],
) {
  const baseLabel = baseConfigOptionLabel(config);
  const duplicateCount = configs.filter(
    (candidate) => baseConfigOptionLabel(candidate) === baseLabel,
  ).length;
  return duplicateCount > 1
    ? `${baseLabel} · ${shortConfigId(config.strategy_config_id)}`
    : baseLabel;
}

export function hasStrategyConfigNameConflict(
  name: string,
  configs: PaperStrategyConfigResponse[],
) {
  const normalizedName = normalizeConfigName(name);
  if (!normalizedName) {
    return false;
  }
  return configs.some(
    (config) => !config.archived && normalizeConfigName(config.name) === normalizedName,
  );
}

export function suggestNextStrategyConfigName(
  baseName: string,
  configs: PaperStrategyConfigResponse[],
) {
  const stem = baseName.trim() || "Strategy sleeve config";
  const existingNames = new Set(
    configs
      .filter((config) => !config.archived)
      .map((config) => normalizeConfigName(config.name)),
  );
  if (!existingNames.has(normalizeConfigName(stem))) {
    return stem;
  }
  for (let index = 2; index < 1000; index += 1) {
    const candidate = `${stem} ${index}`;
    if (!existingNames.has(normalizeConfigName(candidate))) {
      return candidate;
    }
  }
  return `${stem} ${Date.now()}`;
}
