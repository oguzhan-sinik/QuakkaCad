"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export default function Home() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  async function createConference() {
    setLoading(true);
    try {
      const res = await fetch("/api/conference", { method: "POST" });
      const { conferenceId } = await res.json();
      router.push(`/${conferenceId}`);
    } catch {
      setLoading(false);
    }
  }

  return (
    <main className="flex-1 flex items-center justify-center">
      <div className="text-center space-y-8">
        <div className="space-y-3">
          <h1 className="text-4xl font-bold tracking-tight">Quakka CAD</h1>
          <p className="text-foreground/50 text-lg">
            Voice conferences for engineering teams
          </p>
        </div>

        <button
          onClick={createConference}
          disabled={loading}
          className="px-8 py-3 bg-white text-black font-semibold rounded-lg hover:bg-white/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-base"
        >
          {loading ? "Creating..." : "Create Conference"}
        </button>

        <p className="text-foreground/30 text-sm max-w-sm mx-auto">
          Create a conference and share the link with your team. No sign-up
          required.
        </p>
      </div>
    </main>
  );
}
