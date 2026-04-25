"use client";

import { useParams } from "next/navigation";
import { useCallback, useRef, useState } from "react";
import type { PlanBlock } from "../components/PlanSidebar";
import { useConference } from "../lib/useConference";
import { useScribe } from "../lib/useScribe";
import { useTranscript } from "../components/TranscriptPanel";
import JoinScreen from "../components/JoinScreen";
import ConferenceRoom from "../components/ConferenceRoom";

type Phase = "join" | "connected" | "left";

export default function ConferencePage() {
  const params = useParams<{ conferenceId: string }>();
  const conferenceId = params.conferenceId;

  const [phase, setPhase] = useState<Phase>("join");
  const [displayName, setDisplayName] = useState("");
  const displayNameRef = useRef(displayName);
  displayNameRef.current = displayName;

  const { lines, partials, handleTranscript, downloadTranscript } = useTranscript();

  const [meetingId, setMeetingId] = useState<string | null>(null);
  const [planBlocks, setPlanBlocks] = useState<PlanBlock[]>([]);
  const [plannerLoading, setPlannerLoading] = useState(false);
  const postedCountRef = useRef(0);
  const linesRef = useRef(lines);
  linesRef.current = lines;
  const meetingIdRef = useRef(meetingId);
  meetingIdRef.current = meetingId;

  const conference = useConference({
    conferenceId,
    displayName,
    onTranscript: handleTranscript,
  });

  // When Scribe produces a transcript:
  // 1. Update local UI directly (so we see our own transcript immediately)
  // 2. Send through signaling server (so other participants see it)
  const onScribeTranscript = useCallback(
    (text: string, isPartial: boolean) => {
      // Direct local update
      handleTranscript({
        speakerName: displayNameRef.current,
        text,
        isPartial,
        timestamp: Date.now(),
        peerId: "__self__",
      });
      // Broadcast to others
      conference.sendTranscript(text, isPartial);
    },
    [conference.sendTranscript, handleTranscript]
  );

  useScribe({
    stream: conference.localStream,
    isMuted: conference.isMuted,
    onTranscript: onScribeTranscript,
  });

  const handleJoin = useCallback(
    async (name: string) => {
      setDisplayName(name);
      // Create a backend meeting to track transcript + plan blocks
      try {
        const res = await fetch("/api/meetings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        if (res.ok) setMeetingId((await res.json()).id);
      } catch (e) {
        console.warn("Could not create backend meeting:", e);
      }
      setTimeout(async () => {
        await conference.connect();
      }, 0);
    },
    [conference]
  );

  const handleSendChat = useCallback(
    (text: string) => {
      handleTranscript({
        speakerName: displayNameRef.current,
        text,
        isPartial: false,
        timestamp: Date.now(),
        peerId: "__self__",
      });
      conference.sendTranscript(text, false);
    },
    [conference.sendTranscript, handleTranscript],
  );

  const handleRunPlanner = useCallback(async () => {
    const mid = meetingIdRef.current;
    if (!mid || plannerLoading) return;
    setPlannerLoading(true);
    try {
      // Sync any unposted committed lines to the backend transcript
      const currentLines = linesRef.current;
      const t0 = currentLines[0]?.timestamp ?? Date.now();
      const unposted = currentLines.slice(postedCountRef.current);
      for (const line of unposted) {
        const start = (line.timestamp - t0) / 1000;
        await fetch(`/api/meetings/${mid}/transcript`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            text: `${line.speakerName}: ${line.text}`,
            start_time: start,
            end_time: start + 1,
          }),
        });
      }
      postedCountRef.current = currentLines.length;

      // Run the planner agent
      const res = await fetch(`/api/meetings/${mid}/agent/plan`, { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      const result = await res.json();

      setPlanBlocks((prev) => {
        const updatedIds = new Set<string>(result.updated.map((b: PlanBlock) => b.id));
        return [...prev.filter((b) => !updatedIds.has(b.id)), ...result.updated, ...result.created];
      });
    } catch (e) {
      console.error("Planner error:", e);
    } finally {
      setPlannerLoading(false);
    }
  }, [plannerLoading]);

  if (phase === "join" && conference.isConnected) {
    setPhase("connected");
  }

  function handleLeave() {
    conference.leave();
    setPhase("left");
  }

  if (phase === "left") {
    return (
      <main className="flex-1 flex items-center justify-center">
        <div className="text-center space-y-4">
          <h1 className="text-2xl font-bold">You left the meeting</h1>
          <p className="text-zinc-400">Thanks for joining!</p>
          {lines.length > 0 && (
            <button
              onClick={downloadTranscript}
              className="inline-block px-6 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-sm hover:bg-zinc-700 transition-colors"
            >
              Download transcript
            </button>
          )}
          <a
            href="/"
            className="inline-block px-6 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-sm hover:bg-zinc-700 transition-colors"
          >
            Back to home
          </a>
        </div>
      </main>
    );
  }

  if (phase === "join") {
    return (
      <JoinScreen
        conferenceId={conferenceId}
        onJoin={handleJoin}
        error={conference.error}
      />
    );
  }

  return (
    <ConferenceRoom
      conferenceId={conferenceId}
      peers={conference.peers}
      myName={displayName}
      isMuted={conference.isMuted}
      onToggleMute={conference.toggleMute}
      onLeave={handleLeave}
      transcriptLines={lines}
      transcriptPartials={partials}
      onDownloadTranscript={downloadTranscript}
      onSendChat={handleSendChat}
      planBlocks={planBlocks}
      plannerLoading={plannerLoading}
      onRunPlanner={handleRunPlanner}
    />
  );
}
