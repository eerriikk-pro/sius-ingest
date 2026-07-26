import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";
import path from "node:path";

// Next loads web/.env* before this config. Force a second pass at the repository
// root so the collector and local viewer share one ignored credential file.
loadEnvConfig(
  path.resolve(process.cwd(), ".."),
  process.env.NODE_ENV === "development",
  undefined,
  true,
);

const nextConfig: NextConfig = {
  reactStrictMode: true,
};

export default nextConfig;
