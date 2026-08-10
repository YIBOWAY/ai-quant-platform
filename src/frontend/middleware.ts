import { NextRequest, NextResponse } from "next/server";
import { LOCALES, type Locale } from "@/lib/locale";

const PUBLIC_FILE = /\.[^/]+$/;

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api") ||
    pathname === "/favicon.ico" ||
    PUBLIC_FILE.test(pathname)
  ) {
    return NextResponse.next();
  }

  const segments = pathname.split("/");
  const maybeLocale = segments[1] as Locale | undefined;
  const requestHeaders = new Headers(request.headers);

  if (maybeLocale && LOCALES.includes(maybeLocale)) {
    requestHeaders.set("x-qs-locale", maybeLocale);
    // Path stripping lives in next.config.ts as a relative rewrite. An
    // absolute middleware rewrite is unsafe here because Next normalizes
    // every loopback NextURL to localhost, then compares it with the actual
    // 127.0.0.1 server URL and intermittently proxies back into itself.
    return NextResponse.next({ request: { headers: requestHeaders } });
  }

  return NextResponse.next({
    request: { headers: requestHeaders },
  });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image).*)"],
};
