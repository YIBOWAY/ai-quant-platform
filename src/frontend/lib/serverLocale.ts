import { cookies, headers } from "next/headers";
import { LOCALE_COOKIE, resolveLocale, type Locale } from "./locale";

/**
 * Resolve the active locale for a server component.
 * Priority: locale path header > explicit `?lang=` override > saved cookie > "en".
 */
export async function getServerLocale(
  searchParams?: Record<string, string | string[] | undefined>,
): Promise<Locale> {
  const requestHeaders = await headers();
  const pathLocale = requestHeaders.get("x-qs-locale");
  if (pathLocale) {
    return resolveLocale(pathLocale);
  }
  if (searchParams?.lang) {
    return resolveLocale(searchParams.lang);
  }
  const store = await cookies();
  return resolveLocale(store.get(LOCALE_COOKIE)?.value);
}
