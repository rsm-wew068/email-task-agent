import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Proxy the FastAPI backend so /healthz and /api/* are reachable through the
  // public URL (the backend itself only listens on localhost inside the container).
  async rewrites() {
    const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
    return [
      { source: "/healthz", destination: `${backend}/healthz` },
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
    ];
  },
};

export default nextConfig;
