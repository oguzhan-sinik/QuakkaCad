"use client";
import { useCallback, useEffect, useRef, useState } from "react";

interface OrbitState {
  rotX: number;
  rotY: number;
  dist: number;
  targetX: number;
  targetY: number;
  targetZ: number;
}

export function useGestureControls({
  orbitRef,
  videoRef,
  enabled,
}: {
  orbitRef: React.RefObject<OrbitState & Record<string, unknown>>;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  enabled: boolean;
}) {
  const recognizerRef = useRef<any>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const rafRef = useRef<number>(0);
  const lastHandRef = useRef<{ x: number; y: number } | null>(null);
  const lastGestureRef = useRef<string>("");
  const homeDist = useRef<number>(100);
  // Stable ref so switchCamera doesn't trigger re-init
  const switchStreamRef = useRef<((deviceId: string) => Promise<void>) | null>(null);

  const [currentGesture, setCurrentGesture] = useState("");
  const [isReady, setIsReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [videoDevices, setVideoDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>("");

  const switchCamera = useCallback(async (deviceId: string) => {
    setSelectedDeviceId(deviceId);
    await switchStreamRef.current?.(deviceId);
  }, []);

  useEffect(() => {
    if (!enabled) {
      cancelAnimationFrame(rafRef.current);
      streamRef.current?.getTracks().forEach(t => t.stop());
      streamRef.current = null;
      recognizerRef.current?.close?.();
      recognizerRef.current = null;
      switchStreamRef.current = null;
      setIsReady(false);
      setError(null);
      setCurrentGesture("");
      setVideoDevices([]);
      setSelectedDeviceId("");
      return;
    }

    let cancelled = false;

    async function startStream(deviceId: string) {
      streamRef.current?.getTracks().forEach(t => t.stop());
      const constraints: MediaStreamConstraints = deviceId
        ? { video: { deviceId: { exact: deviceId } } }
        : { video: { width: 640, height: 480 } };
      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      if (cancelled) { stream.getTracks().forEach(t => t.stop()); return; }
      streamRef.current = stream;
      const video = videoRef.current;
      if (!video) return;
      video.srcObject = stream;
      await new Promise<void>(res => { video.onloadeddata = () => res(); video.play(); });
    }

    async function init() {
      try {
        // Get permission first (generic stream), then enumerate with labels
        const permStream = await navigator.mediaDevices.getUserMedia({ video: true });
        if (cancelled) { permStream.getTracks().forEach(t => t.stop()); return; }
        permStream.getTracks().forEach(t => t.stop());

        const all = await navigator.mediaDevices.enumerateDevices();
        const inputs = all.filter(d => d.kind === "videoinput");
        if (cancelled) return;
        setVideoDevices(inputs);
        const firstId = inputs[0]?.deviceId ?? "";
        setSelectedDeviceId(firstId);

        // Init MediaPipe (WASM + model are HTTP-cached after first load)
        const { FilesetResolver, GestureRecognizer } = await import("@mediapipe/tasks-vision");
        const vision = await FilesetResolver.forVisionTasks(
          "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.18/wasm"
        );
        const recognizer = await GestureRecognizer.createFromOptions(vision, {
          baseOptions: {
            modelAssetPath:
              "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task",
          },
          runningMode: "VIDEO",
          numHands: 1,
        });
        if (cancelled) { recognizer.close(); return; }
        recognizerRef.current = recognizer;

        await startStream(firstId);
        if (cancelled) return;

        // Expose stream-swap function; rAF loop continues uninterrupted since it
        // reads from videoRef.current which keeps the same DOM element
        switchStreamRef.current = startStream;

        homeDist.current = orbitRef.current.dist;
        setIsReady(true);

        const video = videoRef.current!;
        let lastTimestamp = -1;
        function frame() {
          if (!recognizerRef.current || !video) return;
          rafRef.current = requestAnimationFrame(frame);
          const now = performance.now();
          if (now === lastTimestamp) return;
          lastTimestamp = now;

          const res = recognizerRef.current.recognizeForVideo(video, now);
          const gesture: string = res.gestures?.[0]?.[0]?.categoryName ?? "Unknown";
          const landmarks = res.landmarks?.[0];

          if (!landmarks) {
            lastHandRef.current = null;
            setCurrentGesture("");
            return;
          }
          if (gesture !== lastGestureRef.current) {
            lastHandRef.current = null;
            lastGestureRef.current = gesture;
          }
          setCurrentGesture(gesture);

          const wrist = landmarks[0];
          const o = orbitRef.current;
          const prev = lastHandRef.current;

          if (gesture === "Closed_Fist" && prev) {
            o.rotY += (wrist.x - prev.x) * 5.0;
            o.rotX = Math.max(
              -Math.PI / 2 + 0.01,
              Math.min(Math.PI / 2 - 0.01, o.rotX + (wrist.y - prev.y) * 5.0)
            );
          } else if (gesture === "Open_Palm" && prev) {
            const dx = wrist.x - prev.x;
            const dy = wrist.y - prev.y;
            const scale = o.dist * 2;
            o.targetX -= dx * scale * Math.cos(o.rotY);
            o.targetY -= dx * scale * Math.sin(o.rotY);
            o.targetZ += dy * scale;
          } else if (gesture === "Thumb_Up") {
            o.dist = Math.max(1, o.dist * 0.97);
          } else if (gesture === "Thumb_Down") {
            o.dist *= 1.03;
          } else if (gesture === "Victory" && lastGestureRef.current !== "Victory") {
            o.rotX = 0.6;
            o.rotY = -0.8;
            o.dist = homeDist.current;
            o.targetX = 0;
            o.targetY = 0;
            o.targetZ = 0;
          }
          lastHandRef.current = { x: wrist.x, y: wrist.y };
        }
        frame();
      } catch (e: unknown) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Gesture init failed");
        }
      }
    }

    init();
    return () => {
      cancelled = true;
      cancelAnimationFrame(rafRef.current);
    };
  // orbitRef and videoRef are stable refs — intentionally omitted from deps
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  return { currentGesture, isReady, error, videoDevices, selectedDeviceId, switchCamera };
}
