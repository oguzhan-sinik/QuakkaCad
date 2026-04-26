"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PlanBlock } from "../components/PlanSidebar";
import type { ModelIteration, FEAAnalysisData, TechnicalDrawingData } from "../components/CadPanel";
import { useConference } from "../lib/useConference";
import { useScribe } from "../lib/useScribe";
import { useTranscript } from "../components/TranscriptPanel";
import { useVoiceCommands, type VoiceCommandDef } from "../lib/useVoiceCommands";
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
  const [refineLoading, setRefineLoading] = useState(false);
  const [planUpdatedForCad, setPlanUpdatedForCad] = useState(false);
  const [modelIterations, setModelIterations] = useState<ModelIteration[]>([]);
  const [viewingVersionId, setViewingVersionId] = useState<string | null>(null);
  const [cadTabOverride, setCadTabOverride] = useState<"code" | "preview" | "fea" | "drawing" | null>(null);
  const [feaLoading, setFeaLoading] = useState(false);
  const [feaData, setFeaData] = useState<FEAAnalysisData | null>(null);
  const [drawingLoading, setDrawingLoading] = useState(false);
  const [drawingData, setDrawingData] = useState<TechnicalDrawingData | null>(null);
  const feaLoadingRef = useRef(false);
  feaLoadingRef.current = feaLoading;
  const drawingLoadingRef = useRef(false);
  drawingLoadingRef.current = drawingLoading;
  const [templateLoading, setTemplateLoading] = useState(false);
  const templateLoadingRef = useRef(false);
  templateLoadingRef.current = templateLoading;
  // Stores the MuBit session context for the most recent template generation,
  // so the WASM compile outcome can be reported back to close the learning loop.
  const templateSessionRef = useRef<{ sessionId: string; assemblyType: string } | null>(null);
  const modelIterationsRef = useRef<ModelIteration[]>([]);
  modelIterationsRef.current = modelIterations;
  const cadLoadingRef = useRef(false);
  cadLoadingRef.current = cadLoading;
  const refineLoadingRef = useRef(false);
  refineLoadingRef.current = refineLoading;

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

  const handleRefine = useCallback(async () => {
    const mid = meetingIdRef.current;
    if (!mid || refineLoadingRef.current) return;
    setRefineLoading(true);
    try {
      const res = await fetch(`/api/meetings/${mid}/agent/model`, { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      const result = await res.json();
      setCadCode(result.iteration.script);
      setModelIterations(prev => [...prev, result.iteration as ModelIteration]);
      setViewingVersionId(null);
    } catch (e) {
      console.error("Refine error:", e);
    } finally {
      setRefineLoading(false);
    }
  }, []);

  const handleRunFEA = useCallback(async (meshData?: string) => {
    const mid = meetingIdRef.current;
    if (!mid || feaLoadingRef.current) return;
    setFeaLoading(true);
    setCadTabOverride("fea");
    try {
      const res = await fetch(`/api/meetings/${mid}/agent/fea`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mesh_base64: meshData ?? null }),
      });
      if (!res.ok) throw new Error(await res.text());
      const result = await res.json();
      setFeaData(result.analysis as FEAAnalysisData);
    } catch (e) {
      console.error("FEA analysis error:", e);
    } finally {
      setFeaLoading(false);
    }
  }, []);

  const handleRunDrawing = useCallback(async (screenshots?: string[]) => {
    const mid = meetingIdRef.current;
    if (!mid || drawingLoadingRef.current) return;
    setDrawingLoading(true);
    setCadTabOverride("drawing");
    try {
      const res = await fetch(`/api/meetings/${mid}/agent/drawing`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reference_images: screenshots ?? [] }),
      });
      if (!res.ok) throw new Error(await res.text());
      const result = await res.json();
      setDrawingData(result.drawing as TechnicalDrawingData);
    } catch (e) {
      console.error("Technical drawing error:", e);
    } finally {
      setDrawingLoading(false);
    }
  }, []);

  const handleRunTemplate = useCallback(async () => {
    const mid = meetingIdRef.current;
    if (!mid || templateLoadingRef.current) return;
    setTemplateLoading(true);
    try {
      // Use last few transcript lines as the prompt
      const recent = linesRef.current.slice(-5).map(l => l.text).join(" ");
      const prompt = recent || "parametric enclosure 60x40x30mm";
      const res = await fetch(`/api/meetings/${mid}/agent/template`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      });
      if (!res.ok) throw new Error(await res.text());
      const result = await res.json();
      setCadCode(result.iteration.script);
      setModelIterations(prev => [...prev, result.iteration as ModelIteration]);
      setViewingVersionId(null);
      // Store session context so WASM compile outcome can be reported to MuBit
      const sessionId = result.meta?.session_id;
      const assemblyType = result.meta?.assembly_type;
      if (sessionId && assemblyType) {
        templateSessionRef.current = { sessionId, assemblyType };
      }
    } catch (e) {
      console.error("Template generation error:", e);
    } finally {
      setTemplateLoading(false);
    }
  }, []);

  const handleTemplateOutcome = useCallback(async (success: boolean, error?: string) => {
    const mid = meetingIdRef.current;
    const session = templateSessionRef.current;
    if (!mid || !session) return;
    // Clear so we don't double-report
    templateSessionRef.current = null;
    try {
      await fetch(`/api/meetings/${mid}/agent/template/outcome`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: session.sessionId,
          assembly_type: session.assemblyType,
          success,
          error: error ?? null,
        }),
      });
    } catch (e) {
      console.warn("Template outcome reporting failed:", e);
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

    try {
      // Sync any unposted committed lines to the backend transcript
      // (skip voice command lines — they're actions, not design discussion)
      const currentLines = linesRef.current;
      const t0 = currentLines[0]?.timestamp ?? Date.now();
      const cmdIndices = commandLineIndicesRef.current;
      for (let i = postedCountRef.current; i < currentLines.length; i++) {
        if (cmdIndices.has(i)) continue;
        const line = currentLines[i];
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
            const block = event.block as PlanBlock;
            setPlanBlocks((prev) => [...prev, block]);
            setTargetedBlockIds((prev) => new Set([...prev, block.id]));

          } else if (type === "block_updated") {
            const block = event.block as PlanBlock;
            setPlanBlocks((prev) => prev.map((b) => (b.id === block.id ? block : b)));
            setTargetedBlockIds((prev) => new Set([...prev, block.id]));

          } else if (type === "done") {
            const created = (event.total_created as number) ?? 0;
            const updated = (event.total_updated as number) ?? 0;
            // Broadcast final plan state to WebSocket peers
            setPlanBlocks((prev) => {
              conference.sendPlanUpdate(prev);
              return prev;
            });
            // Auto-trigger 3D generation only if planning actually produced/changed blocks
            if (created > 0 || updated > 0) {
              setPlanUpdatedForCad(true);
              handleRunTemplate();
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
  }, [handleRunTemplate]);

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

  // Voice commands — detect spoken triggers and fire corresponding actions
  const voiceCommands = useMemo<VoiceCommandDef[]>(() => [
    {
      id: "update-cad",
      triggers: ["update 3d design", "update the design", "generate 3d", "generate the model", "generate model"],
      cooldownMs: 8000,
      action: () => handleRunTemplate(),
    },
    {
      id: "refine",
      triggers: ["refine generation", "refine the model", "refine design", "refine the design", "generate with opus"],
      cooldownMs: 8000,
      action: () => handleRefine(),
    },
    {
      id: "run-planner",
      triggers: ["run planner", "run the planner", "update the plan", "analyze transcript"],
      cooldownMs: 5000,
      action: () => handleRunPlanner(),
    },
    {
      id: "show-code",
      triggers: ["show openscad", "show code", "show the code", "show me the code"],
      cooldownMs: 3000,
      action: () => setCadTabOverride("code"),
    },
    {
      id: "show-preview",
      triggers: ["show preview", "show 3d preview", "show the preview", "show model"],
      cooldownMs: 3000,
      action: () => setCadTabOverride("preview"),
    },
    {
      id: "quick-generate",
      triggers: ["quick generate", "quick gen", "template generate", "fast generate"],
      cooldownMs: 8000,
      action: () => handleRunTemplate(),
    },
    {
      id: "run-fea",
      triggers: ["run analysis", "run fea", "structural analysis", "stress analysis", "run fea analysis"],
      cooldownMs: 8000,
      action: () => handleRunFEA(),
    },
    {
      id: "run-drawing",
      triggers: ["technical drawing", "generate drawing", "create drawing", "engineering drawing"],
      cooldownMs: 8000,
      action: () => handleRunDrawing(),
    },
    {
      id: "show-fea",
      triggers: ["show analysis", "show fea", "show stress"],
      cooldownMs: 3000,
      action: () => setCadTabOverride("fea"),
    },
    {
      id: "show-drawing",
      triggers: ["show drawing", "show technical drawing"],
      cooldownMs: 3000,
      action: () => setCadTabOverride("drawing"),
    },
  ], [handleRunOpenSCAD, handleRunTemplate, handleRefine, handleRunPlanner, handleRunFEA, handleRunDrawing]);

  const { commandLineIndices } = useVoiceCommands(lines, voiceCommands);
  const commandLineIndicesRef = useRef(commandLineIndices);
  commandLineIndicesRef.current = commandLineIndices;

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
      onUpdateCad={undefined}
      onRefine={meetingId ? handleRefine : undefined}
      refineLoading={refineLoading}
      modelIterations={modelIterations}
      viewingVersionId={viewingVersionId}
      onSelectVersion={handleSelectVersion}
      cadTabOverride={cadTabOverride}
      onRunTemplate={meetingId ? handleRunTemplate : undefined}
      templateLoading={templateLoading}
      onTemplateOutcome={meetingId ? handleTemplateOutcome : undefined}
      onRunFEA={meetingId ? handleRunFEA : undefined}
      feaLoading={feaLoading}
      feaData={feaData}
      onRunDrawing={meetingId ? handleRunDrawing : undefined}
      drawingLoading={drawingLoading}
      drawingData={drawingData}
    />
  );
}
