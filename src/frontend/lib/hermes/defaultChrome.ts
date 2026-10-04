export const HERMES_DEFAULT_LEDGERS = [
  { id: "duty" as const, label: "今日", labelEn: "Today" },
  { id: "research" as const, label: "研究", labelEn: "Research" },
  { id: "paper" as const, label: "模拟", labelEn: "Paper" },
] as const;

/** Operator internals stay as deep routes; they are not default desk chrome. */
export const HERMES_DEFAULT_PRODUCT_TABS = [] as const;
