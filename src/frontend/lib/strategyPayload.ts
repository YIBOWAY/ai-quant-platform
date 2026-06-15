export function buildStrategyPayload(
  fields: Record<string, Record<string, unknown>>,
  values: Record<string, unknown>,
) {
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

export function asStringArray(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map(String).filter(Boolean);
  }
  if (typeof value === "string") {
    return value.split(",").map((item) => item.trim()).filter(Boolean);
  }
  return [];
}
