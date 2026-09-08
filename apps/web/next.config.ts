import type { NextConfig } from "next";
import { buildSecurityHeaderRules } from "./lib/security-headers";

const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async headers() {
    const environment =
      process.env.NODE_ENV === "development" ? "development" : "production";
    return buildSecurityHeaderRules(environment, BACKEND_ORIGIN);
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_ORIGIN}/:path*` }];
  },
};

export default nextConfig;
