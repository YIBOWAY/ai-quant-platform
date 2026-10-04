export type Locale = "en" | "zh";

export const LOCALE_COOKIE = "qs_lang";
export const LOCALES: Locale[] = ["en", "zh"];

export function resolveLocale(value: string | string[] | undefined | null): Locale {
  const raw = Array.isArray(value) ? value[0] : value;
  return raw === "zh" ? "zh" : "en";
}

export function splitLocalePath(pathname: string): {
  locale?: Locale;
  pathname: string;
} {
  const boundary = pathname.search(/[?#]/);
  const pathOnly = boundary < 0 ? pathname : pathname.slice(0, boundary);
  const suffix = boundary < 0 ? "" : pathname.slice(boundary);
  const segments = pathOnly.split("/");
  const maybeLocale = segments[1];
  if (maybeLocale === "en" || maybeLocale === "zh") {
    const rest = `/${segments.slice(2).join("/")}`.replace(/\/+$/, "") || "/";
    return { locale: maybeLocale, pathname: `${rest}${suffix}` };
  }
  return { pathname };
}

export function localizePath(pathname: string, locale: Locale): string {
  if (!pathname.startsWith("/")) {
    return pathname;
  }
  const boundary = pathname.search(/[?#]/);
  const pathOnly = boundary < 0 ? pathname : pathname.slice(0, boundary);
  const suffix = boundary < 0 ? "" : pathname.slice(boundary);
  const stripped = splitLocalePath(pathOnly).pathname;
  const normalized = stripped === "/" ? "" : stripped;
  return `/${locale}${normalized}${suffix}`;
}
