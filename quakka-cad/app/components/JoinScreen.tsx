"use client";

import { useEffect, useState } from "react";

interface JoinScreenProps {
  conferenceId: string;
  onJoin: (name: string) => void;
  error: string | null;
}

export default function JoinScreen({ conferenceId, onJoin, error }: JoinScreenProps) {
  const [name, setName] = useState("");

  // When the browser restores this page from bfcache (back/forward navigation),
  // the DOM reflects the old filled-in name but React reinitialises to "".
  // Resetting on pageshow:persisted keeps them in sync.
  useEffect(() => {
    const onPageShow = (e: PageTransitionEvent) => {
      if (e.persisted) setName("");
    };
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, []);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (trimmed) onJoin(trimmed);
  }

  return (
    <main className="flex-1 flex items-center justify-center">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center space-y-2">
          <h1 className="text-2xl font-bold">Join Conference</h1>
          <p className="text-zinc-400 text-sm font-mono">{conferenceId}</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="name" className="block text-sm text-zinc-400 mb-1.5">
              Your name
            </label>
            <input
              id="name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Enter your display name"
              maxLength={30}
              autoFocus
              className="w-full px-4 py-2.5 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:border-zinc-500 transition-colors"
            />
          </div>

          {error && (
            <p className="text-red-400 text-sm">{error}</p>
          )}

          <button
            type="submit"
            disabled={!name.trim()}
            suppressHydrationWarning
            className="w-full py-2.5 bg-white text-black font-semibold rounded-lg hover:bg-white/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Join
          </button>
        </form>

        <div className="text-center space-y-1">
          <p className="text-zinc-500 text-xs">
            Your browser will request microphone access
          </p>
          <p className="text-zinc-600 text-xs">
            This conference is live-transcribed. By joining, you consent to your
            speech being transcribed and shared with other participants.
          </p>
        </div>
      </div>
    </main>
  );
}
