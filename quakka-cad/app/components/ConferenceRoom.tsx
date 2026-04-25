"use client";

import type { Peer } from "../lib/useConference";
import AttendeeList from "./AttendeeList";
import ControlBar from "./ControlBar";
import TranscriptPanel from "./TranscriptPanel";
import CadPanel from "./CadPanel";
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
  onSendChat: (text: string) => void;
  planBlocks: PlanBlock[];
  plannerLoading: boolean;
  onRunPlanner: () => void;
}

export default function ConferenceRoom({
  conferenceId,
  peers,
  myName,
  isMuted,
  onToggleMute,
  onLeave,
  transcriptLines,
  transcriptPartials,
  onDownloadTranscript,
  onSendChat,
  planBlocks,
  plannerLoading,
  onRunPlanner,
}: ConferenceRoomProps) {
  const shareUrl = typeof window !== "undefined"
    ? `${window.location.origin}/${conferenceId}`
    : "";

  function copyLink() {
    navigator.clipboard.writeText(shareUrl);
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 p-4 gap-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold">Quakka CAD</h2>
          <span className="text-xs text-zinc-500 font-mono">{conferenceId}</span>
        </div>
        <button
          onClick={copyLink}
          className="text-xs px-3 py-1.5 bg-zinc-800 border border-zinc-700 rounded-md text-zinc-300 hover:bg-zinc-700 transition-colors"
        >
          Copy invite link
        </button>
      </div>

      {/* Three-column layout */}
      <div className="flex-1 flex gap-4 min-h-0">
        {/* Left column — Plan Sidebar */}
        <PlanSidebar blocks={planBlocks} isLoading={plannerLoading} onRunPlanner={onRunPlanner} />

        {/* Middle column — CAD Panel (tabs + prompt) */}
        <CadPanel />

        {/* Right column — Transcript + Attendees + Controls */}
        <div className="flex-1 flex flex-col gap-3 min-h-0">
          {/* Live Transcript */}
          <TranscriptPanel
            lines={transcriptLines}
            partials={transcriptPartials}
            onDownload={onDownloadTranscript}
            onSendChat={onSendChat}
          />

          {/* Attendee list */}
          <div className="bg-zinc-900 rounded-xl border border-zinc-700/50 p-4 flex-shrink-0">
            <AttendeeList peers={peers} myName={myName} isMuted={isMuted} />
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
