import type { PaperAccountResponse } from "@/lib/api";

/**
 * Fail-closed resolver for the paper account's available cash.
 *
 * `getPaperAccount()` returns a $1,000,000 FALLBACK_ACCOUNT when the API is
 * unreachable, tagging the envelope with `apiError`. Consumers must not treat
 * that synthetic cash figure as real. Returns `null` when the account payload
 * carries an `apiError` (or the cash figure is otherwise absent), so callers
 * render "--" / block cash-mode actions instead of trusting the fallback.
 */
export function resolvePaperAccountAvailableCash(
  account: Pick<PaperAccountResponse, "apiError" | "available_cash"> | null | undefined,
): number | null {
  if (account == null) {
    return null;
  }
  if (account.apiError) {
    return null;
  }
  const cash = account.available_cash;
  return typeof cash === "number" && Number.isFinite(cash) ? cash : null;
}
