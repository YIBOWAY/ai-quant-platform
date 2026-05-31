export type Locale = "en" | "zh";

export const LOCALE_COOKIE = "qs_lang";

export function resolveLocale(value: string | string[] | undefined | null): Locale {
  const raw = Array.isArray(value) ? value[0] : value;
  return raw === "zh" ? "zh" : "en";
}
