import { cookies } from "next/headers";
import { LOCALE_COOKIE, resolveLocale, type Locale } from "./locale";

/**
 * Resolve the active locale for a server component.
 * Priority: explicit `?lang=` query param (per-page override) > saved cookie > "en".
 */
export async function getServerLocale(
  searchParams?: Record<string, string | string[] | undefined>,
): Promise<Locale> {
  if (searchParams?.lang) {
    return resolveLocale(searchParams.lang);
  }
  const store = await cookies();
  return resolveLocale(store.get(LOCALE_COOKIE)?.value);
}
