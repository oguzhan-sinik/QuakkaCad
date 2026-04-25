"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import type { PlanBlock } from "../components/PlanSidebar";
import type { ModelIteration } from "../components/CadPanel";
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

  const { lines, partials, handleTranscript, downloadTranscript, clearTranscript } = useTranscript();

  const [meetingId, setMeetingId] = useState<string | null>(null);
  const [planBlocks, setPlanBlocks] = useState<PlanBlock[]>([]);
  const [plannerLoading, setPlannerLoading] = useState(false);
  const [targetedBlockIds, setTargetedBlockIds] = useState<Set<string>>(new Set());
  const [processingUpToEntry, setProcessingUpToEntry] = useState<number | null>(null);
  const [transcriptUpdated, setTranscriptUpdated] = useState(false);
  const [cadCode, setCadCode] = useState<string | null>(null);
  const [cadLoading, setCadLoading] = useState(false);
  const [planUpdatedForCad, setPlanUpdatedForCad] = useState(false);
  const [modelIterations, setModelIterations] = useState<ModelIteration[]>([]);
  const [viewingVersionId, setViewingVersionId] = useState<string | null>(null);
  const modelIterationsRef = useRef<ModelIteration[]>([]);
  modelIterationsRef.current = modelIterations;
  const cadLoadingRef = useRef(false);
  cadLoadingRef.current = cadLoading;

  const postedCountRef = useRef(0);
  const linesRef = useRef(lines);
  linesRef.current = lines;
  const meetingIdRef = useRef(meetingId);
  meetingIdRef.current = meetingId;
  const plannerLoadingRef = useRef(false);
  plannerLoadingRef.current = plannerLoading;
  const lastPlannerLinesRef = useRef(0);
  // Records the frontend line index (= postedCountRef before posting) at planner run start

  const conference = useConference({
    conferenceId,
    displayName,
    onTranscript: handleTranscript,
    onPlanUpdate: (blocks) => setPlanBlocks(blocks as PlanBlock[]),
  });

  const onScribeTranscript = useCallback(
    (text: string, isPartial: boolean) => {
      handleTranscript({
        speakerName: displayNameRef.current,
        text,
        isPartial,
        timestamp: Date.now(),
        peerId: "__self__",
      });
      conference.sendTranscript(text, isPartial);
    },
    [conference.sendTranscript, handleTranscript]
  );

  useEffect(() => {
    if (lines.length > 0) setTranscriptUpdated(true);
  }, [lines.length]);

  useEffect(() => {
    if (partials.size > 0) setTranscriptUpdated(true);
  }, [partials.size]);

  const handleClearTranscript = useCallback(() => {
    clearTranscript();
    postedCountRef.current = 0;
    lastPlannerLinesRef.current = 0;
    setTranscriptUpdated(false);
  }, [clearTranscript]);

  const handleRunOpenSCAD = useCallback(async () => {
    const mid = meetingIdRef.current;
    if (!mid || cadLoadingRef.current) return;
    setPlanUpdatedForCad(false);
    setCadLoading(true);
    try {
      const res = await fetch(`/api/meetings/${mid}/agent/model`, { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      const result = await res.json();
      setCadCode(result.iteration.script);
      setModelIterations(prev => [...prev, result.iteration as ModelIteration]);
      setViewingVersionId(null);
    } catch (e) {
      console.error("OpenSCAD agent error:", e);
    } finally {
      setCadLoading(false);
    }
  }, []);

  const handleRunPlanner = useCallback(async () => {
    const mid = meetingIdRef.current;
    if (!mid || plannerLoadingRef.current) return;

    lastPlannerLinesRef.current = linesRef.current.length;
    setTranscriptUpdated(false);
    setPlannerLoading(true);
    setTargetedBlockIds(new Set());
    setProcessingUpToEntry(null);

    let blocksCreatedThisRun = 0;

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

      // Open the SSE stream
      const res = await fetch(`/api/meetings/${mid}/agent/plan`, { method: "POST" });
      if (!res.ok || !res.body) throw new Error(`Planner HTTP error: ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let streamEnded = false;

      while (!streamEnded) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Split on SSE double-newline delimiter; keep incomplete trailing event in buffer
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";

        for (const part of parts) {
          const dataLine = part.split("\n").find((l) => l.startsWith("data: "));
          if (!dataLine) continue;

          let event: Record<string, unknown>;
          try {
            event = JSON.parse(dataLine.slice("data: ".length));
          } catch {
            continue;
          }

          const type = event.type as string;

          if (type === "chunk_start") {
            // New chunk: clear previous block highlights, advance scan cursor
            setTargetedBlockIds(new Set());
            const prevCount = (event.prev_count as number) ?? 0;
            const batchOffsetEnd = event.batch_offset_end as number;
            setProcessingUpToEntry(prevCount + batchOffsetEnd);

          } else if (type === "block_created") {
            blocksCreatedThisRun++;
            const block = event.block as PlanBlock;
            setPlanBlocks((prev) => [...prev, block]);
            setTargetedBlockIds((prev) => new Set([...prev, block.id]));

          } else if (type === "block_updated") {
            const block = event.block as PlanBlock;
            setPlanBlocks((prev) => prev.map((b) => (b.id === block.id ? block : b)));
            setTargetedBlockIds((prev) => new Set([...prev, block.id]));

          } else if (type === "done") {
            // Broadcast final plan state to WebSocket peers
            setPlanBlocks((prev) => {
              conference.sendPlanUpdate(prev);
              return prev;
            });
            setPlanUpdatedForCad(true);
            if (blocksCreatedThisRun > 0) {
              handleRunOpenSCAD();
            }
            // Exit immediately — don't wait for the stream to close naturally,
            // since Next.js dev may not propagate the backend's connection close.
            streamEnded = true;
            break;

          } else if (type === "error") {
            console.error("Planner SSE error:", event.detail);
            streamEnded = true;
            break;
          }
        }
      }
      reader.cancel().catch(() => {});
    } catch (e) {
      console.error("Planner error:", e);
    } finally {
      setPlannerLoading(false);
      setTargetedBlockIds(new Set());
      setProcessingUpToEntry(null);
    }
  }, [handleRunOpenSCAD]);

  const handleSelectVersion = useCallback((id: string | null) => {
    if (id === null) {
      setViewingVersionId(null);
      setCadCode(modelIterationsRef.current.at(-1)?.script ?? null);
    } else {
      const iter = modelIterationsRef.current.find(i => i.id === id);
      if (iter) {
        setViewingVersionId(id);
        setCadCode(iter.script);
      }
    }
  }, []);

  useScribe({
    stream: conference.localStream,
    isMuted: conference.isMuted,
    onTranscript: onScribeTranscript,
  });

  useEffect(() => {
    if (!meetingId) return;
    const id = setInterval(() => {
      if (!plannerLoadingRef.current && linesRef.current.length > lastPlannerLinesRef.current) {
        handleRunPlanner();
      }
    }, 1000);
    return () => clearInterval(id);
  }, [meetingId, handleRunPlanner]);

  const handleJoin = useCallback(
    async (name: string) => {
      setDisplayName(name);
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
      onClearTranscript={handleClearTranscript}
      onSendChat={handleSendChat}
      planBlocks={planBlocks}
      plannerLoading={plannerLoading}
      targetedBlockIds={targetedBlockIds}
      processingUpToEntry={processingUpToEntry}
      onRunPlanner={transcriptUpdated ? handleRunPlanner : undefined}
      cadCode={cadCode}
      cadLoading={cadLoading}
      onUpdateCad={planUpdatedForCad && viewingVersionId === null ? handleRunOpenSCAD : undefined}
      modelIterations={modelIterations}
      viewingVersionId={viewingVersionId}
      onSelectVersion={handleSelectVersion}
    />
  );
}
