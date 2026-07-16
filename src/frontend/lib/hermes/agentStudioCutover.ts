import { hermesRouteHref } from "./routes";
import type { Locale } from "../locale";

export function agentStudioCutoverHref(
  enabled: boolean,
  locale: Locale,
): string | null {
  return enabled ? hermesRouteHref("approvals", locale) : null;
}
