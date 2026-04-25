"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { TranscriptEvent } from "../lib/useConference";

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

interface TranscriptPanelProps {
  onDownload: () => void;
}

let lineIdCounter = 0;

export function useTranscript() {
  const [lines, setLines] = useState<TranscriptLine[]>([]);
  const [partials, setPartials] = useState<Map<string, PartialLine>>(new Map());

  const handleTranscript = useCallback((event: TranscriptEvent) => {
    if (event.isPartial) {
      setPartials((prev) => {
        const next = new Map(prev);
        next.set(event.peerId, {
          speakerName: event.speakerName,
          text: event.text,
          peerId: event.peerId,
        });
        return next;
      });
    } else {
      // Committed line — add to log and clear partial for this speaker
      setLines((prev) => [
        ...prev,
        {
          id: `line-${++lineIdCounter}`,
          speakerName: event.speakerName,
          text: event.text,
          timestamp: event.timestamp,
        },
      ]);
      setPartials((prev) => {
        const next = new Map(prev);
        next.delete(event.peerId);
        return next;
      });
    }
  }, []);

  const downloadTranscript = useCallback(() => {
    if (lines.length === 0) return;
    const content = lines
      .map((l) => {
        const time = new Date(l.timestamp).toLocaleTimeString();
        return `[${time}] ${l.speakerName}: ${l.text}`;
      })
      .join("\n");
    const blob = new Blob([content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "transcript.txt";
    a.click();
    URL.revokeObjectURL(url);
  }, [lines]);

  return { lines, partials, handleTranscript, downloadTranscript };
}

export default function TranscriptPanel({
  lines,
  partials,
  onDownload,
}: {
  lines: TranscriptLine[];
  partials: Map<string, PartialLine>;
  onDownload: () => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const userScrolledRef = useRef(false);

  // Auto-scroll on new lines
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines, partials, autoScroll]);

  function handleScroll() {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    const atBottom = scrollHeight - scrollTop - clientHeight < 40;
    if (!atBottom) {
      userScrolledRef.current = true;
      setAutoScroll(false);
    } else {
      userScrolledRef.current = false;
      setAutoScroll(true);
    }
  }

  function jumpToLatest() {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      setAutoScroll(true);
    }
  }

  const partialEntries = Array.from(partials.values());

  return (
    <div className="flex-1 flex flex-col bg-zinc-900 rounded-xl border border-zinc-700/50 min-h-0 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-700/50 flex-shrink-0">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
          Live Transcript
        </h3>
        {lines.length > 0 && (
          <button
            onClick={onDownload}
            className="text-xs px-2 py-1 bg-zinc-800 border border-zinc-700 rounded text-zinc-400 hover:text-zinc-200 transition-colors"
          >
            Download
          </button>
        )}
      </div>

      {/* Transcript content */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-4 py-3 space-y-2 relative"
      >
        {lines.length === 0 && partialEntries.length === 0 && (
          <p className="text-zinc-600 text-sm text-center mt-8">
            Transcript will appear here when someone speaks...
          </p>
        )}

        {lines.map((line) => (
          <div key={line.id} className="text-sm">
            <span className="font-medium text-zinc-300">{line.speakerName}: </span>
            <span className="text-zinc-400">{line.text}</span>
          </div>
        ))}

        {partialEntries.map((p) => (
          <div key={`partial-${p.peerId}`} className="text-sm italic text-zinc-600">
            <span className="font-medium">{p.speakerName}: </span>
            <span>{p.text}</span>
          </div>
        ))}
      </div>

      {/* Jump to latest */}
      {!autoScroll && (
        <button
          onClick={jumpToLatest}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 px-3 py-1 bg-zinc-700 text-zinc-300 text-xs rounded-full hover:bg-zinc-600 transition-colors"
        >
          Jump to latest
        </button>
      )}
    </div>
  );
}
