import { localizePath } from "../locale";
import type { Locale } from "../locale";

export function agentStudioCutoverHref(
  enabled: boolean,
  locale: Locale,
): string | null {
  return enabled ? localizePath("/library", locale) : null;
}
