import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  transpilePackages: ["@rufina/shared"],
  env: {
    NEXT_PUBLIC_DEMO_MODE: process.env.DEMO_MODE === "1" ? "1" : "0",
  },
};

export default nextConfig;
