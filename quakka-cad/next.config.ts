import type { NextConfig } from "next";

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    // afterFiles: app router route handlers are tried first; these rewrites are
    // fallbacks for any path that has no matching route.ts file.
    return {
      afterFiles: [
        { source: "/api/conference", destination: `${API_BASE}/api/conference` },
        { source: "/api/token", destination: `${API_BASE}/api/token` },
        { source: "/ws/:conferenceId", destination: `${API_BASE}/ws/:conferenceId` },
        { source: "/api/generate", destination: `${API_BASE}/generate` },
        { source: "/api/meetings", destination: `${API_BASE}/api/meetings` },
        { source: "/api/meetings/:path*", destination: `${API_BASE}/api/meetings/:path*` },
      ],
    };
  },
};

export default nextConfig;
