import type { NextConfig } from "next";

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/api/conference", destination: `${API_BASE}/api/conference` },
      { source: "/api/token", destination: `${API_BASE}/api/token` },
      { source: "/ws/:conferenceId", destination: `${API_BASE}/ws/:conferenceId` },
    ];
  },
};

export default nextConfig;
