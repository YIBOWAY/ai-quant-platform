import { localizePath, type Locale } from "@/lib/locale";

export const hermesRoutes = {
  today: "/hermes",
  tasks: "/hermes/tasks",
  approvals: "/hermes/approvals",
  results: "/hermes/results",
} as const;

export type HermesSearchParams = Record<
  string,
  string | string[] | undefined
>;

export function hermesHomeHref(
  locale: Locale,
  searchParams: HermesSearchParams,
): string {
  const query = new URLSearchParams();
  for (const key of Object.keys(searchParams).sort()) {
    const values = searchParams[key];
    for (const value of Array.isArray(values) ? values : [values]) {
      if (value !== undefined) query.append(key, value);
    }
  }
  const suffix = query.size ? `?${query.toString()}` : "";
  return localizePath(`/hermes${suffix}`, locale);
}

export function hermesRouteHref(
  route: keyof typeof hermesRoutes,
  locale: Locale,
  searchParams: HermesSearchParams = {},
): string {
  const base = hermesRoutes[route];
  const query = new URLSearchParams();
  for (const key of Object.keys(searchParams).sort()) {
    const values = searchParams[key];
    for (const value of Array.isArray(values) ? values : [values]) {
      if (value !== undefined) query.append(key, value);
    }
  }
  const suffix = query.size ? `?${query.toString()}` : "";
  return localizePath(`${base}${suffix}`, locale);
}
