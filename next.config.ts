import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: process.cwd(),
  outputFileTracingExcludes: {
    "*": ["./release/**/*", "./.runtime/**/*", "./var/**/*"],
  },
  turbopack: {
    root: process.cwd(),
  },
  reactStrictMode: false,
};

export default nextConfig;
