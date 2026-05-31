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
    const rewritten = request.nextUrl.clone();
    const rest = `/${segments.slice(2).join("/")}`.replace(/\/+$/, "") || "/";
    rewritten.pathname = rest;
    requestHeaders.set("x-qs-locale", maybeLocale);
    return NextResponse.rewrite(rewritten, {
      request: { headers: requestHeaders },
    });
  }

  return NextResponse.next({
    request: { headers: requestHeaders },
  });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image).*)"],
};
