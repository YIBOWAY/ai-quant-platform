import { hermesHomeHref } from "@/lib/hermes/routes";
import { isUsableHermesApiSessionId } from "@/lib/hermes/transcriptHelpers";
import type { Locale } from "@/lib/locale";

/**
 * One ready-child handoff for both consumers of active session state:
 * transcript and composer bind before navigation, while the query parameter
 * makes the same binding recoverable after reload.
 */
export function activateReadyHermesFork(options: {
  hermesSessionId: string;
  locale: Locale;
  bindHermesSession: (hermesSessionId: string) => void;
  navigate: (href: string) => void;
}): string {
  if (!isUsableHermesApiSessionId(options.hermesSessionId)) {
    throw new Error("ready fork is missing a usable Hermes child session id");
  }
  const hermesSessionId = options.hermesSessionId.trim();
  const href = hermesHomeHref(options.locale, {
    hermes_session_id: hermesSessionId,
  });
  options.bindHermesSession(hermesSessionId);
  options.navigate(href);
  return href;
}
