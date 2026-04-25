"use client";

import { useCallback, useEffect, useRef } from "react";

interface UseScribeOptions {
  stream: MediaStream | null;
  isMuted: boolean;
  onTranscript: (text: string, isPartial: boolean) => void;
}

const SCRIBE_WS_BASE = "wss://api.elevenlabs.io/v1/speech-to-text/realtime";

export function useScribe({ stream, isMuted, onTranscript }: UseScribeOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const reconnectAttemptRef = useRef(0);
  const isMutedRef = useRef(isMuted);
  const onTranscriptRef = useRef(onTranscript);
  const cleanedUpRef = useRef(false);

  isMutedRef.current = isMuted;
  onTranscriptRef.current = onTranscript;

  const connectScribe = useCallback(async () => {
    if (!stream || cleanedUpRef.current) return;

    // Get single-use token from our backend
    let token: string;
    try {
      const res = await fetch("/api/token");
      if (!res.ok) {
        console.error("Failed to get Scribe token:", await res.text());
        return;
      }
      const data = await res.json();
      token = data.token;
    } catch (err) {
      console.error("Failed to fetch Scribe token:", err);
      return;
    }

    // Set up AudioWorklet for PCM capture
    if (!audioContextRef.current) {
      const ctx = new AudioContext();
      await ctx.audioWorklet.addModule("/pcm-worklet.js");
      audioContextRef.current = ctx;
    }
    const ctx = audioContextRef.current;
    const sampleRate = ctx.sampleRate;

    // Clean up previous nodes
    workletNodeRef.current?.disconnect();
    sourceRef.current?.disconnect();

    const source = ctx.createMediaStreamSource(stream);
    sourceRef.current = source;

    const workletNode = new AudioWorkletNode(ctx, "pcm-processor");
    workletNodeRef.current = workletNode;
    source.connect(workletNode);

    // Connect to Scribe WebSocket with config via query params
    const params = new URLSearchParams({
      token,
      model_id: "scribe_v2_realtime",
      language_code: "en",
      sample_rate: String(sampleRate),
      audio_format: `pcm_${sampleRate}`,
      commit_strategy: "vad",
    });
    const ws = new WebSocket(`${SCRIBE_WS_BASE}?${params}`);
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectAttemptRef.current = 0;
      console.log("Scribe WebSocket connected");
    };

    // Stream PCM audio chunks from worklet to Scribe
    workletNode.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
      if (
        isMutedRef.current ||
        !wsRef.current ||
        wsRef.current.readyState !== WebSocket.OPEN
      ) {
        return;
      }

      const pcmBuffer = event.data;
      const bytes = new Uint8Array(pcmBuffer);
      let binary = "";
      for (let i = 0; i < bytes.length; i++) {
        binary += String.fromCharCode(bytes[i]);
      }
      const base64 = btoa(binary);

      wsRef.current.send(
        JSON.stringify({
          message_type: "input_audio_chunk",
          audio_base_64: base64,
        })
      );
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);

        if (msg.message_type === "partial_transcript" && msg.text) {
          onTranscriptRef.current(msg.text, true);
        } else if (
          (msg.message_type === "committed_transcript" ||
            msg.message_type === "committed_transcript_with_timestamps") &&
          msg.text
        ) {
          onTranscriptRef.current(msg.text, false);
        }
      } catch {
        // ignore malformed messages
      }
    };

    ws.onclose = () => {
      if (cleanedUpRef.current) return;
      const delay = Math.min(1000 * 2 ** reconnectAttemptRef.current, 30000);
      reconnectAttemptRef.current++;
      console.log(`Scribe disconnected, reconnecting in ${delay}ms...`);
      reconnectTimeoutRef.current = setTimeout(() => {
        connectScribe();
      }, delay);
    };

    ws.onerror = (err) => {
      console.error("Scribe WebSocket error:", err);
    };
  }, [stream]);

  useEffect(() => {
    if (stream) {
      cleanedUpRef.current = false;
      connectScribe();
    }

    return () => {
      cleanedUpRef.current = true;
      clearTimeout(reconnectTimeoutRef.current);
      wsRef.current?.close();
      wsRef.current = null;
      workletNodeRef.current?.disconnect();
      sourceRef.current?.disconnect();
      if (audioContextRef.current?.state !== "closed") {
        audioContextRef.current?.close();
      }
      audioContextRef.current = null;
    };
  }, [stream, connectScribe]);
}
