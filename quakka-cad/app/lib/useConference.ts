"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface Peer {
  peerId: string;
  name: string;
  muted: boolean;
}

export interface TranscriptEvent {
  speakerName: string;
  text: string;
  isPartial: boolean;
  timestamp: number;
  peerId: string;
}

interface UseConferenceOptions {
  conferenceId: string;
  displayName: string;
  onTranscript?: (event: TranscriptEvent) => void;
}

const SIGNALING_URL = "ws://localhost:3001";

const RTC_CONFIG: RTCConfiguration = {
  iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
};

export function useConference({ conferenceId, displayName, onTranscript }: UseConferenceOptions) {
  const [peers, setPeers] = useState<Peer[]>([]);
  const [myPeerId, setMyPeerId] = useState<string | null>(null);
  const [isMuted, setIsMuted] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [localStream, setLocalStream] = useState<MediaStream | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const peerConnectionsRef = useRef<Map<string, RTCPeerConnection>>(new Map());
  const displayNameRef = useRef(displayName);
  displayNameRef.current = displayName;
  const localStreamRef = useRef<MediaStream | null>(null);
  const cleanedUpRef = useRef(false);
  const onTranscriptRef = useRef(onTranscript);
  onTranscriptRef.current = onTranscript;
  const myPeerIdRef = useRef<string | null>(null);

  const cleanup = useCallback(() => {
    if (cleanedUpRef.current) return;
    cleanedUpRef.current = true;

    for (const pc of peerConnectionsRef.current.values()) {
      pc.close();
    }
    peerConnectionsRef.current.clear();

    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach((t) => t.stop());
      localStreamRef.current = null;
      setLocalStream(null);
    }

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    setIsConnected(false);
    setPeers([]);
  }, []);

  const createPeerConnection = useCallback(
    (remotePeerId: string, isInitiator: boolean) => {
      const pc = new RTCPeerConnection(RTC_CONFIG);
      peerConnectionsRef.current.set(remotePeerId, pc);

      // Add local audio tracks
      if (localStreamRef.current) {
        localStreamRef.current.getTracks().forEach((track) => {
          pc.addTrack(track, localStreamRef.current!);
        });
      }

      // Play remote audio when received
      pc.ontrack = (event) => {
        const audio = new Audio();
        audio.srcObject = event.streams[0];
        audio.autoplay = true;
        audio.setAttribute("data-peer", remotePeerId);
        document.body.appendChild(audio);
      };

      // Send ICE candidates
      pc.onicecandidate = (event) => {
        if (event.candidate && wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(
            JSON.stringify({
              type: "ice-candidate",
              to: remotePeerId,
              candidate: event.candidate,
            })
          );
        }
      };

      // If initiator, create and send offer
      if (isInitiator) {
        pc.createOffer()
          .then((offer) => pc.setLocalDescription(offer))
          .then(() => {
            if (wsRef.current?.readyState === WebSocket.OPEN) {
              wsRef.current.send(
                JSON.stringify({
                  type: "offer",
                  to: remotePeerId,
                  sdp: pc.localDescription,
                })
              );
            }
          });
      }

      return pc;
    },
    []
  );

  const connect = useCallback(async () => {
    cleanedUpRef.current = false;
    setError(null);

    // Get mic access
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    } catch {
      setError("Microphone access is required to join the conference.");
      return;
    }
    localStreamRef.current = stream;
    setLocalStream(stream);

    // Connect to signaling server
    const ws = new WebSocket(`${SIGNALING_URL}/${conferenceId}`);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "join", name: displayNameRef.current }));
    };

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);

      switch (msg.type) {
        case "joined": {
          setMyPeerId(msg.peerId);
          myPeerIdRef.current = msg.peerId;
          setIsConnected(true);
          setPeers(msg.peers);

          // Create peer connections to all existing peers (we are the initiator)
          for (const peer of msg.peers) {
            createPeerConnection(peer.peerId, true);
          }
          break;
        }

        case "peer-joined": {
          setPeers((prev) => [
            ...prev,
            { peerId: msg.peerId, name: msg.name, muted: false },
          ]);
          // New peer will initiate the connection to us, so we wait
          break;
        }

        case "peer-left": {
          setPeers((prev) => prev.filter((p) => p.peerId !== msg.peerId));
          const pc = peerConnectionsRef.current.get(msg.peerId);
          if (pc) {
            pc.close();
            peerConnectionsRef.current.delete(msg.peerId);
          }
          // Remove audio element
          const audioEl = document.querySelector(`audio[data-peer="${msg.peerId}"]`);
          if (audioEl) audioEl.remove();
          break;
        }

        case "offer": {
          const pc = createPeerConnection(msg.from, false);
          pc.setRemoteDescription(new RTCSessionDescription(msg.sdp))
            .then(() => pc.createAnswer())
            .then((answer) => pc.setLocalDescription(answer))
            .then(() => {
              if (wsRef.current?.readyState === WebSocket.OPEN) {
                wsRef.current.send(
                  JSON.stringify({
                    type: "answer",
                    to: msg.from,
                    sdp: pc.localDescription,
                  })
                );
              }
            });
          break;
        }

        case "answer": {
          const pc = peerConnectionsRef.current.get(msg.from);
          if (pc) {
            pc.setRemoteDescription(new RTCSessionDescription(msg.sdp));
          }
          break;
        }

        case "ice-candidate": {
          const pc = peerConnectionsRef.current.get(msg.from);
          if (pc && msg.candidate) {
            pc.addIceCandidate(new RTCIceCandidate(msg.candidate));
          }
          break;
        }

        case "mute-status": {
          setPeers((prev) =>
            prev.map((p) =>
              p.peerId === msg.peerId ? { ...p, muted: msg.muted } : p
            )
          );
          break;
        }

        case "transcript": {
          // Skip our own transcripts — already handled locally
          if (msg.peerId === myPeerIdRef.current) break;
          onTranscriptRef.current?.({
            speakerName: msg.speakerName,
            text: msg.text,
            isPartial: msg.isPartial,
            timestamp: msg.timestamp,
            peerId: msg.peerId,
          });
          break;
        }
      }
    };

    ws.onclose = () => {
      if (!cleanedUpRef.current) {
        setIsConnected(false);
      }
    };

    ws.onerror = () => {
      setError("Failed to connect to signaling server. Is it running on port 3001?");
    };
  }, [conferenceId, displayName, createPeerConnection]);

  const toggleMute = useCallback(() => {
    if (localStreamRef.current) {
      const newMuted = !isMuted;
      localStreamRef.current.getAudioTracks().forEach((track) => {
        track.enabled = !newMuted;
      });
      setIsMuted(newMuted);

      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({ type: "mute-status", muted: newMuted })
        );
      }
    }
  }, [isMuted]);

  const sendTranscript = useCallback((text: string, isPartial: boolean) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: "transcript",
          text,
          isPartial,
          timestamp: Date.now(),
        })
      );
    }
  }, []);

  const leave = useCallback(() => {
    cleanup();
  }, [cleanup]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      cleanup();
    };
  }, [cleanup]);

  return {
    peers,
    myPeerId,
    isMuted,
    isConnected,
    error,
    localStream,
    connect,
    toggleMute,
    leave,
    sendTranscript,
    displayName,
  };
}
