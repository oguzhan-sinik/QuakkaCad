import { useEffect, useRef, useState } from "react";

export interface VoiceCommandDef {
  id: string;
  /** Phrase variants — each is matched fuzzily against committed lines */
  triggers: string[];
  /** Minimum cooldown between firings (ms) */
  cooldownMs: number;
  action: () => void;
}

interface TranscriptLine {
  id: string;
  text: string;
  isChat?: boolean;
}

function tokenize(text: string): Set<string> {
  return new Set(
    text
      .toLowerCase()
      .split(/[^a-z0-9]+/)
      .filter((w) => w.length >= 2)
  );
}

/**
 * Check if a transcript line fuzzy-matches a trigger phrase.
 * A trigger matches if >= 60% of its words appear in the line.
 */
function matchesTrigger(lineTokens: Set<string>, trigger: string): boolean {
  const triggerWords = trigger
    .toLowerCase()
    .split(/\s+/)
    .filter((w) => w.length >= 2);
  if (triggerWords.length === 0) return false;

  let hits = 0;
  for (const w of triggerWords) {
    if (lineTokens.has(w)) hits++;
  }
  return hits / triggerWords.length >= 0.6;
}

export function useVoiceCommands(
  lines: TranscriptLine[],
  commands: VoiceCommandDef[]
) {
  const [commandLineIndices, setCommandLineIndices] = useState<Set<number>>(
    () => new Set()
  );
  const processedCountRef = useRef(0);
  const lastFiredRef = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    if (lines.length <= processedCountRef.current) return;

    const newIndices: number[] = [];
    const now = Date.now();

    for (let i = processedCountRef.current; i < lines.length; i++) {
      // Skip typed chat messages — voice commands are for spoken input only
      if (lines[i].isChat) continue;
      const lineTokens = tokenize(lines[i].text);

      for (const cmd of commands) {
        const lastFired = lastFiredRef.current.get(cmd.id) ?? 0;
        if (now - lastFired < cmd.cooldownMs) continue;

        const matched = cmd.triggers.some((t) => matchesTrigger(lineTokens, t));
        if (matched) {
          newIndices.push(i);
          lastFiredRef.current.set(cmd.id, now);
          cmd.action();
          break; // one command per line
        }
      }
    }

    processedCountRef.current = lines.length;

    if (newIndices.length > 0) {
      setCommandLineIndices((prev) => {
        const next = new Set(prev);
        for (const idx of newIndices) next.add(idx);
        return next;
      });
    }
  }, [lines, commands]);

  return { commandLineIndices };
}
