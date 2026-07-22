import type { NextConfig } from "next";

// Package E (IA + Route Rename): the frontend page routes /replications and
// /order-book were renamed to /strategies and /polymarket. These permanent
// redirects keep old bookmarks/links working and preserve dynamic [runId]
// segments and query strings. The locale prefix (/en, /zh) is handled by
// middleware.ts AFTER redirects run, so each old path is covered for the bare
// form and for each explicit locale prefix. NOTE: backend /api/replications/...
// paths are unaffected — only Next.js page routes are renamed here.
const LOCALE_PREFIXES = ["", "/en", "/zh"] as const;

type RouteRename = { from: string; to: string };

const RENAMED_ROUTES: RouteRename[] = [
  { from: "/replications/:runId", to: "/strategies/:runId" },
  { from: "/replications", to: "/strategies" },
  { from: "/order-book", to: "/polymarket" },
];

const routeRedirects = RENAMED_ROUTES.flatMap(({ from, to }) =>
  LOCALE_PREFIXES.map((prefix) => ({
    source: `${prefix}${from}`,
    destination: `${prefix}${to}`,
    permanent: true,
  })),
);

// L2a-Send owner gate requires same-origin browser calls (cookie + CSRF +
// Sec-Fetch-Site=same-origin). Dev/prod FE therefore rewrites /api/* to the
// local BFF instead of browser-cross-origin fetch to :8765.
const API_REWRITE_ORIGIN =
  process.env.QUANT_API_REWRITE_ORIGIN ?? "http://127.0.0.1:8765";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  typescript: {
    ignoreBuildErrors: false,
  },
  images: {
    remotePatterns: [
      {
        protocol: "http",
        hostname: "127.0.0.1",
        port: "8765",
        pathname: "/api/prediction-market/**",
      },
      {
        protocol: "http",
        hostname: "localhost",
        port: "8765",
        pathname: "/api/prediction-market/**",
      },
    ],
  },
  transpilePackages: ["motion"],
  async redirects() {
    return routeRedirects;
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_REWRITE_ORIGIN}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
