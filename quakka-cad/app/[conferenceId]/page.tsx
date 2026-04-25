"use client";

import { useParams } from "next/navigation";
import { useCallback, useRef, useState } from "react";
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
      setTimeout(async () => {
        await conference.connect();
      }, 0);
    },
    [conference]
  );

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
    />
  );
}
