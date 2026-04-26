"use client";

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { TranscriptEvent } from "../lib/useConference";

interface TranscriptLine {
  id: string;
  speakerName: string;
  text: string;
  timestamp: number;
  isChat?: boolean;
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
          isChat: event.peerId === "__self__",
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

  const clearTranscript = useCallback(() => {
    setLines([]);
    setPartials(new Map());
  }, []);

  return { lines, partials, handleTranscript, downloadTranscript, clearTranscript };
}

export default function TranscriptPanel({
  lines,
  partials,
  onDownload,
  onClear,
  onSendChat,
  processingUpToEntry,
  isScanning,
}: {
  lines: TranscriptLine[];
  partials: Map<string, PartialLine>;
  onDownload: () => void;
  onClear?: () => void;
  onSendChat?: (text: string) => void;
  processingUpToEntry?: number | null;
  isScanning?: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const userScrolledRef = useRef(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatText, setChatText] = useState("");

  // Auto-scroll on new lines or when scan cursor first appears
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines, partials, autoScroll, processingUpToEntry]);

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

  function openChat() {
    setChatOpen(true);
    setTimeout(() => inputRef.current?.focus(), 0);
  }

  function sendChat() {
    const text = chatText.trim();
    if (!text || !onSendChat) return;
    onSendChat(text);
    setChatText("");
  }

  function handleChatKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") sendChat();
    if (e.key === "Escape") setChatOpen(false);
  }

  return (
    <div className="h-full flex-1 flex flex-col bg-zinc-900 rounded-xl border border-zinc-700/50 min-h-0 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-700/50 flex-shrink-0">
        <div className="flex items-center gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
            Live Transcript
          </h3>
          {isScanning && (
            <span className="text-[10px] text-indigo-400 font-mono animate-pulse">▶ scanning</span>
          )}
        </div>
        {lines.length > 0 && (
          <div className="flex items-center gap-1.5">
            <button
              onClick={onDownload}
              className="text-xs px-2 py-1 bg-zinc-800 border border-zinc-700 rounded text-zinc-400 hover:text-zinc-200 transition-colors"
            >
              Download
            </button>
            {onClear && (
              <button
                onClick={onClear}
                className="text-xs px-2 py-1 bg-zinc-800 border border-zinc-700 rounded text-zinc-400 hover:text-red-400 transition-colors"
              >
                Clear
              </button>
            )}
          </div>
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

        {lines.flatMap((line, idx) => {
          const lineEl = (
            <div key={line.id} className="text-sm">
              <span className="font-medium text-zinc-300">{line.speakerName}: </span>
              <span className="text-zinc-400">{line.text}</span>
            </div>
          );
          // Insert scan cursor divider after the last line that has been processed
          if (
            processingUpToEntry != null &&
            idx === processingUpToEntry - 1 &&
            processingUpToEntry < lines.length
          ) {
            return [
              lineEl,
              <div
                key={`cursor-${processingUpToEntry}`}
                className="flex items-center gap-2 my-1"
              >
                <div className="flex-1 h-px bg-indigo-500/40" />
                <span className="text-[10px] text-indigo-400 font-mono animate-pulse whitespace-nowrap">
                  ▶ scanning
                </span>
                <div className="flex-1 h-px bg-indigo-500/40" />
              </div>,
            ];
          }
          return [lineEl];
        })}

        {/* Trailing cursor: always show when scanning and no mid-transcript cursor is active */}
        {isScanning && (processingUpToEntry == null || processingUpToEntry >= lines.length) && lines.length > 0 && (
          <div className="flex items-center gap-2 my-1">
            <div className="flex-1 h-px bg-indigo-500/40" />
            <span className="text-[10px] text-indigo-400 font-mono animate-pulse whitespace-nowrap">
              ▶ scanning
            </span>
            <div className="flex-1 h-px bg-indigo-500/40" />
          </div>
        )}

        {partialEntries.map((p) => (
          <div key={`partial-${p.peerId}`} className="text-sm italic text-zinc-600">
            <span className="font-medium">{p.speakerName}: </span>
            <span>{p.text}</span>
          </div>
        ))}

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

      {/* Chat */}
      {onSendChat && (
        <div className="flex-shrink-0 border-t border-zinc-800">
          {chatOpen ? (
            <div className="flex items-center gap-2 px-3 py-2">
              <input
                ref={inputRef}
                type="text"
                value={chatText}
                onChange={(e) => setChatText(e.target.value)}
                onKeyDown={handleChatKey}
                placeholder="Type a message…"
                className="flex-1 bg-zinc-800 text-sm text-zinc-200 placeholder-zinc-600 px-3 py-1.5 rounded-lg border border-zinc-700 focus:outline-none focus:border-zinc-500 transition-colors"
              />
              <button
                onClick={sendChat}
                disabled={!chatText.trim()}
                className="text-xs px-2.5 py-1.5 bg-zinc-700 text-zinc-200 rounded-lg hover:bg-zinc-600 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              >
                Send
              </button>
              <button
                onClick={() => setChatOpen(false)}
                className="text-zinc-600 hover:text-zinc-400 transition-colors text-sm leading-none px-1"
                title="Hide chat"
              >
                ✕
              </button>
            </div>
          ) : (
            <button
              onClick={openChat}
              className="w-full text-xs text-zinc-700 hover:text-zinc-500 py-1.5 transition-colors"
            >
              + Chat
            </button>
          )}
        </div>
      )}
    </div>
  );
}
