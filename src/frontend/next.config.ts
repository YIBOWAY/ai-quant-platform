import type { NextConfig } from "next";

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
};

export default nextConfig;
