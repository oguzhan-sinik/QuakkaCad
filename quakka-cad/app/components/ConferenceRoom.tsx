"use client";

import { useState } from "react";
import type { Peer } from "../lib/useConference";
import AttendeeList from "./AttendeeList";
import ControlBar from "./ControlBar";
import TranscriptPanel from "./TranscriptPanel";
import CadPanel, { type ModelIteration, type FEAAnalysisData, type TechnicalDrawingData } from "./CadPanel";
import PlanSidebar, { type PlanBlock } from "./PlanSidebar";

interface TranscriptLine {
  id: string;
  speakerName: string;
  text: string;
  timestamp: number;
}

interface PartialLine {
  speakerName: string;
  text: string;
  peerId: string;
}

interface ConferenceRoomProps {
  conferenceId: string;
  peers: Peer[];
  myName: string;
  isMuted: boolean;
  onToggleMute: () => void;
  onLeave: () => void;
  transcriptLines: TranscriptLine[];
  transcriptPartials: Map<string, PartialLine>;
  onDownloadTranscript: () => void;
  onClearTranscript: () => void;
  onSendChat: (text: string) => void;
  planBlocks: PlanBlock[];
  plannerLoading: boolean;
  targetedBlockIds: Set<string>;
  processingUpToEntry: number | null;
  onRunPlanner?: () => void;
  cadCode?: string | null;
  cadLoading?: boolean;
  onUpdateCad?: () => void;
  onRefine?: () => void;
  refineLoading?: boolean;
  modelIterations?: ModelIteration[];
  viewingVersionId?: string | null;
  onSelectVersion?: (id: string | null) => void;
  cadTabOverride?: "code" | "preview" | "fea" | "drawing" | null;
  onRunTemplate?: () => void;
  templateLoading?: boolean;
  onTemplateOutcome?: (success: boolean, error?: string) => void;
  onRunFEA?: (meshData?: string) => void;
  feaLoading?: boolean;
  feaData?: FEAAnalysisData | null;
  onRunDrawing?: (screenshots?: string[]) => void;
  drawingLoading?: boolean;
  drawingData?: TechnicalDrawingData | null;
  gestureEnabled?: boolean;
  onToggleGesture?: () => void;
}

export default function ConferenceRoom(props: ConferenceRoomProps) {
  const {
    conferenceId,
    peers,
    myName,
    isMuted,
    onToggleMute,
    onLeave,
    transcriptLines,
    transcriptPartials,
    onDownloadTranscript,
    onClearTranscript,
    onSendChat,
    planBlocks,
    plannerLoading,
    targetedBlockIds,
    processingUpToEntry,
    onRunPlanner,
    cadCode,
    cadLoading,
    onUpdateCad,
    onRefine,
    refineLoading,
    modelIterations,
    viewingVersionId,
    onSelectVersion,
    cadTabOverride,
    onRunTemplate,
    templateLoading,
    onTemplateOutcome,
    onRunFEA,
    feaLoading,
    feaData,
    onRunDrawing,
    drawingLoading,
    drawingData,
    gestureEnabled,
    onToggleGesture,
  } = props;

  const [leftWidth, setLeftWidth] = useState(20);
  const [middleWidth, setMiddleWidth] = useState(50);
  const [rightWidth, setRightWidth] = useState(30);

  const shareUrl =
    typeof window !== "undefined"
      ? `${window.location.origin}/${conferenceId}`
      : "";

  function copyLink() {
    navigator.clipboard.writeText(shareUrl);
  }

  const startResize = (e: React.MouseEvent, divider: "left" | "right") => {
    e.preventDefault();

    const startX = e.clientX;
    const startLeft = leftWidth;
    const startMiddle = middleWidth;
    const startRight = rightWidth;

    document.body.style.userSelect = "none";

    const onMouseMove = (e: MouseEvent) => {
      const delta = ((e.clientX - startX) / window.innerWidth) * 100;

      if (divider === "left") {
        const newLeft = startLeft + delta;
        const newMiddle = startMiddle - delta;

        if (newLeft > 10 && newMiddle > 20) {
          setLeftWidth(newLeft);
          setMiddleWidth(newMiddle);
        }
      }

      if (divider === "right") {
        const newMiddle = startMiddle + delta;
        const newRight = startRight - delta;

        if (newMiddle > 20 && newRight > 15) {
          setMiddleWidth(newMiddle);
          setRightWidth(newRight);
        }
      }
    };

    const onMouseUp = () => {
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
  };

  return (
    <div className="flex-1 flex flex-col min-h-0 p-4 gap-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold">Quakka CAD</h2>
          <span className="text-xs text-zinc-500 font-mono">
            {conferenceId}
          </span>
        </div>
        <button
          onClick={copyLink}
          className="text-xs px-3 py-1.5 bg-zinc-800 border border-zinc-700 rounded-md text-zinc-300 hover:bg-zinc-700 transition-colors"
        >
          Copy invite link
        </button>
      </div>

      {/* Layout */}
      <div className="flex-1 flex gap-2 min-h-0">
        {/* LEFT */}
        <div
          style={{ width: `${leftWidth}%` }}
          className="min-h-0 flex flex-col"
        >
          <div className="h-full overflow-auto">
            <PlanSidebar
              blocks={planBlocks}
              isLoading={plannerLoading}
              targetedBlockIds={targetedBlockIds}
              onRunPlanner={onRunPlanner}
            />
          </div>
        </div>

        {/* Divider */}
        <div
          onMouseDown={(e) => startResize(e, "left")}
          className="w-1 hover:w-2 transition-all rounded-xl cursor-col-resize bg-zinc-700 hover:bg-zinc-500"
        />

        {/* MIDDLE */}
        <div
          style={{ width: `${middleWidth}%` }}
          className="min-h-0 flex flex-col"
        >
          <div className="h-full overflow-auto">
            <CadPanel
              cadCode={cadCode}
              cadLoading={cadLoading}
              onUpdateCad={onUpdateCad}
              onRefine={onRefine}
              refineLoading={refineLoading}
              modelIterations={modelIterations}
              viewingVersionId={viewingVersionId}
              onSelectVersion={onSelectVersion}
              tabOverride={cadTabOverride}
              onRunTemplate={onRunTemplate}
              templateLoading={templateLoading}
              onTemplateOutcome={onTemplateOutcome}
              onRunFEA={onRunFEA}
              feaLoading={feaLoading}
              feaData={feaData}
              onRunDrawing={onRunDrawing}
              drawingLoading={drawingLoading}
              drawingData={drawingData}
              gestureEnabled={gestureEnabled}
              onToggleGesture={onToggleGesture}
            />
          </div>
        </div>

        {/* Divider */}
        <div
          onMouseDown={(e) => startResize(e, "right")}
          className="w-1 hover:w-2 rounded-xl transition-all cursor-col-resize bg-zinc-700 hover:bg-zinc-500"
        />

        {/* RIGHT */}
        <div
          style={{ width: `${rightWidth}%` }}
          className="min-h-0 flex flex-col gap-3"
        >
          {/* Transcript */}
          <div className="flex-1 min-h-0">
            <TranscriptPanel
              lines={transcriptLines}
              partials={transcriptPartials}
              onDownload={onDownloadTranscript}
              onClear={onClearTranscript}
              onSendChat={onSendChat}
              processingUpToEntry={processingUpToEntry}
              isScanning={plannerLoading}
            />
          </div>

          {/* Attendees */}
          <div className="bg-zinc-900 rounded-xl border border-zinc-700/50 p-4 flex-shrink-0">
            <AttendeeList
              peers={peers}
              myName={myName}
              isMuted={isMuted}
            />
          </div>

          {/* Controls */}
          <div className="bg-zinc-900 rounded-xl border border-zinc-700/50 p-4 flex-shrink-0">
            <ControlBar
              isMuted={isMuted}
              onToggleMute={onToggleMute}
              onLeave={onLeave}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
