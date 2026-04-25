"use client";

import { useEffect, useRef, useState } from "react";

type Tab = "code" | "preview";

export interface ModelIteration {
  id: string;
  timestamp: string;
  script: string;
  reasoning: string;
  applied_lessons: string[];
}

interface CadPanelProps {
  cadCode?: string | null;
  cadLoading?: boolean;
  onUpdateCad?: () => void;
  onRefine?: () => void;
  refineLoading?: boolean;
  modelIterations?: ModelIteration[];
  viewingVersionId?: string | null;
  onSelectVersion?: (id: string | null) => void;
}

export default function CadPanel({
  cadCode,
  cadLoading = false,
  onUpdateCad,
  onRefine,
  refineLoading = false,
  modelIterations,
  viewingVersionId,
  onSelectVersion,
}: CadPanelProps) {
  const [tab, setTab] = useState<Tab>("preview");
  const [code, setCode] = useState("");
  const [compiling, setCompiling] = useState(false);
  const [debugLog, setDebugLog] = useState<string[]>([]);

  const canvasContainerRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<any>(null);
  const rendererRef = useRef<any>(null);
  const cameraRef = useRef<any>(null);
  const frameRef = useRef<number>(0);
  const THREERef = useRef<any>(null);
  const workerRef = useRef<Worker | null>(null);
  const codeRef = useRef(code);
  codeRef.current = code;
  const compiledCodeRef = useRef<string>("");

  useEffect(() => {
    if (cadCode == null) return;
    setCode(cadCode);
    compiledCodeRef.current = "";
    setTab("preview");
  }, [cadCode]);

  // Camera orbit state
  // rotY = azimuth (horizontal rotation), rotX = elevation (vertical tilt)
  // OpenSCAD default view: looking from front-right, slightly above
  const orbitRef = useRef({
    isDown: false,
    rightDown: false,
    startX: 0,
    startY: 0,
    rotX: 0.6,        // ~35 deg elevation (looking down)
    rotY: -0.8,        // ~45 deg azimuth (front-right)
    dist: 100,
    targetX: 0,
    targetY: 0,
    targetZ: 0,
  });
  const keysRef = useRef<Set<string>>(new Set());

  function log(msg: string) {
    console.log(`[CadPanel] ${msg}`);
    setDebugLog(prev => [...prev.slice(-9), msg]);
  }

  // --- Three.js setup ---
  async function ensureThree() {
    if (THREERef.current && rendererRef.current && sceneRef.current) return true;

    const container = canvasContainerRef.current;
    if (!container) { log("ERROR: container ref null"); return false; }

    const rect = container.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) { log(`ERROR: container ${rect.width}x${rect.height}`); return false; }

    try {
      const THREE = await import("three");
      THREERef.current = THREE;

      const canvas = document.createElement("canvas");
      container.innerHTML = "";
      container.appendChild(canvas);

      const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
      renderer.setSize(rect.width, rect.height);
      renderer.setPixelRatio(window.devicePixelRatio);
      renderer.setClearColor(0xffffff, 1);
      rendererRef.current = renderer;

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0xffffff);
      sceneRef.current = scene;

      const camera = new THREE.PerspectiveCamera(45, rect.width / rect.height, 0.1, 10000);
      cameraRef.current = camera;

      scene.add(new THREE.AmbientLight(0xffffff, 0.5));
      const dir1 = new THREE.DirectionalLight(0xffffff, 0.8);
      dir1.position.set(5, 10, 7);
      scene.add(dir1);
      const dir2 = new THREE.DirectionalLight(0xffffff, 0.4);
      dir2.position.set(-5, -3, -5);
      scene.add(dir2);

      // Grid on XY plane
      const grid = new THREE.GridHelper(200, 20, 0xcccccc, 0xe5e5e5);
      grid.rotation.x = Math.PI / 2;
      scene.add(grid);

      function animate() {
        frameRef.current = requestAnimationFrame(animate);
        const o = orbitRef.current;

        // WASD/QE keyboard movement
        const keys = keysRef.current;
        const moveSpeed = o.dist * 0.015;
        const rotSpeed = 0.03;
        // Forward/back direction on the XY plane based on azimuth
        const fwdX = -Math.sin(o.rotY);
        const fwdY = Math.cos(o.rotY);
        // Right direction
        const rightX = Math.cos(o.rotY);
        const rightY = Math.sin(o.rotY);

        if (keys.has("w")) { o.targetX += fwdX * moveSpeed; o.targetY += fwdY * moveSpeed; }
        if (keys.has("s")) { o.targetX -= fwdX * moveSpeed; o.targetY -= fwdY * moveSpeed; }
        if (keys.has("a")) { o.targetX -= rightX * moveSpeed; o.targetY -= rightY * moveSpeed; }
        if (keys.has("d")) { o.targetX += rightX * moveSpeed; o.targetY += rightY * moveSpeed; }
        if (keys.has("q")) { o.targetZ -= moveSpeed; }
        if (keys.has("e")) { o.targetZ += moveSpeed; }
        if (keys.has("arrowleft"))  { o.rotY -= rotSpeed; }
        if (keys.has("arrowright")) { o.rotY += rotSpeed; }
        if (keys.has("arrowup"))    { o.rotX = Math.min(Math.PI / 2 - 0.01, o.rotX + rotSpeed); }
        if (keys.has("arrowdown"))  { o.rotX = Math.max(-Math.PI / 2 + 0.01, o.rotX - rotSpeed); }

        // Spherical coordinates around target — Z is up (OpenSCAD convention)
        camera.position.set(
          o.targetX + o.dist * Math.cos(o.rotX) * Math.sin(o.rotY),
          o.targetY - o.dist * Math.cos(o.rotX) * Math.cos(o.rotY),
          o.targetZ + o.dist * Math.sin(o.rotX)
        );
        camera.up.set(0, 0, 1);
        camera.lookAt(new THREE.Vector3(o.targetX, o.targetY, o.targetZ));
        renderer.render(scene, camera);
      }
      animate();

      log(`Three.js OK (${Math.round(rect.width)}x${Math.round(rect.height)})`);
      return true;
    } catch (e: any) {
      log(`Three.js init error: ${e.message}`);
      return false;
    }
  }

  // --- WASM Worker ---
  function getWorker() {
    if (!workerRef.current) {
      workerRef.current = new Worker("/openscad-worker.js", { type: "module" });
    }
    return workerRef.current;
  }

  function compileAndRender(scadCode: string) {
    if (compiledCodeRef.current === scadCode) {
      log("Code unchanged, skipping recompile");
      return;
    }

    setCompiling(true);
    log("Sending to OpenSCAD WASM compiler...");

    const worker = getWorker();
    const id = Date.now();

    const handler = (e: MessageEvent) => {
      if (e.data.id !== undefined && e.data.id !== id) return;

      switch (e.data.type) {
        case "status":
          log(e.data.text);
          break;
        case "stderr":
          if (e.data.text && !e.data.text.startsWith("Compiling")) {
            log(`stderr: ${e.data.text}`);
          }
          break;
        case "result": {
          worker.removeEventListener("message", handler);
          setCompiling(false);
          compiledCodeRef.current = scadCode;
          if (e.data.format === "stl" && e.data.stl) {
            log("Compilation done (STL) — loading mesh...");
            loadSTL(e.data.stl);
          } else if (e.data.off) {
            const preview = e.data.off.substring(0, 100).replace(/\n/g, " ");
            log(`Compilation done (OFF, ${e.data.off.length} chars) — ${preview}`);
            loadOFF(e.data.off);
          } else {
            log("Compile returned but no mesh data");
          }
          break;
        }
        case "error": {
          worker.removeEventListener("message", handler);
          setCompiling(false);
          log(`Compile error: ${e.data.text}`);
          break;
        }
      }
    };

    worker.addEventListener("message", handler);
    worker.postMessage({ code: scadCode, id });
  }

  function loadSTL(buffer: ArrayBuffer) {
    const THREE = THREERef.current;
    const scene = sceneRef.current;
    if (!THREE || !scene) return;

    const toRemove: any[] = [];
    scene.traverse((child: any) => { if (child.isMesh) toRemove.push(child); });
    toRemove.forEach((m: any) => { scene.remove(m); m.geometry?.dispose(); m.material?.dispose(); });

    const dv = new DataView(buffer);
    const numTriangles = dv.getUint32(80, true);
    const positions = new Float32Array(numTriangles * 9);
    let offset = 84;
    for (let i = 0; i < numTriangles; i++) {
      offset += 12;
      for (let v = 0; v < 9; v++) { positions[i * 9 + v] = dv.getFloat32(offset, true); offset += 4; }
      offset += 2;
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.computeVertexNormals();
    const material = new THREE.MeshPhongMaterial({ color: 0xf9d72c, shininess: 50, side: THREE.DoubleSide });
    const mesh = new THREE.Mesh(geometry, material);
    scene.add(mesh);

    const box = new THREE.Box3().setFromObject(mesh);
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    orbitRef.current.dist = Math.max(size.x, size.y, size.z) * 2.2;
    orbitRef.current.targetX = center.x;
    orbitRef.current.targetY = center.y;
    orbitRef.current.targetZ = center.z;
    orbitRef.current.rotX = 0.6;
    orbitRef.current.rotY = -0.8;
    log(`STL: ${numTriangles} triangles, size ${size.x.toFixed(1)}x${size.y.toFixed(1)}x${size.z.toFixed(1)}`);
  }

  function loadOFF(offText: string) {
    const THREE = THREERef.current;
    const scene = sceneRef.current;
    if (!THREE || !scene) { log("loadOFF: THREE/scene missing"); return; }

    // Remove old meshes
    const toRemove: any[] = [];
    scene.traverse((child: any) => { if (child.isMesh) toRemove.push(child); });
    toRemove.forEach((m: any) => { scene.remove(m); m.geometry?.dispose(); if (m.material) { if (Array.isArray(m.material)) m.material.forEach((mt: any) => mt.dispose()); else m.material.dispose(); } });

    try {
      const { positions, colors, hasColors } = parseOFF(offText);

      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
      if (hasColors) {
        geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
      }
      geometry.computeVertexNormals();

      const material = new THREE.MeshPhongMaterial({
        vertexColors: hasColors,
        color: hasColors ? 0xffffff : 0xf9d72c,
        shininess: 50,
        side: THREE.DoubleSide,
      });

      const mesh = new THREE.Mesh(geometry, material);
      scene.add(mesh);

      // Auto-fit camera
      const box = new THREE.Box3().setFromObject(mesh);
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      orbitRef.current.dist = Math.max(size.x, size.y, size.z) * 2.2;
      orbitRef.current.targetX = center.x;
      orbitRef.current.targetY = center.y;
      orbitRef.current.targetZ = center.z;
      orbitRef.current.rotX = 0.6;
      orbitRef.current.rotY = -0.8;

      const triCount = positions.length / 9;
      log(`Loaded: ${triCount} triangles, ${hasColors ? "with colors" : "no colors"}, size ${size.x.toFixed(1)}x${size.y.toFixed(1)}x${size.z.toFixed(1)}`);
    } catch (e: any) {
      log(`OFF parse error: ${e.message}`);
      console.error("OFF parse error:", e);
    }
  }

  // --- OFF format parser (supports per-face colors) ---
  function parseOFF(text: string) {
    const lines = text.split("\n").map(l => l.trim()).filter(l => l && !l.startsWith("#"));

    let idx = 0;
    // Handle header — could be "OFF" alone or "OFF 46247 92742 0" on same line
    const headerMatch = lines[idx].match(/^(C?N?OFF)\s*(.*)/i);
    let numVerts: number, numFaces: number;
    if (headerMatch) {
      const rest = headerMatch[2].trim();
      idx++;
      if (rest) {
        // Counts on same line as OFF header
        const counts = rest.split(/\s+/).map(Number);
        numVerts = counts[0];
        numFaces = counts[1];
      } else {
        // Counts on next line
        const counts = lines[idx++].split(/\s+/).map(Number);
        numVerts = counts[0];
        numFaces = counts[1];
      }
    } else {
      // No header — first line is counts
      const counts = lines[idx++].split(/\s+/).map(Number);
      numVerts = counts[0];
      numFaces = counts[1];
    }

    // Read vertices
    const verts: number[][] = [];
    for (let i = 0; i < numVerts; i++) {
      const parts = lines[idx++].split(/\s+/).map(Number);
      verts.push([parts[0], parts[1], parts[2]]);
    }

    // Read faces — triangulate and extract colors
    const positions: number[] = [];
    const colors: number[] = [];
    let hasColors = false;

    for (let i = 0; i < numFaces; i++) {
      if (idx >= lines.length) break;
      const parts = lines[idx++].split(/\s+/).map(Number);
      const n = parts[0]; // number of vertices in this face
      const faceVerts = parts.slice(1, 1 + n);

      // Colors come after vertex indices
      let r = 0.98, g = 0.84, b = 0.17; // default OpenSCAD yellow
      const colorStart = 1 + n;
      if (parts.length > colorStart + 2) {
        hasColors = true;
        // Colors can be 0-1 floats or 0-255 ints
        let cr = parts[colorStart], cg = parts[colorStart + 1], cb = parts[colorStart + 2];
        if (cr > 1 || cg > 1 || cb > 1) { cr /= 255; cg /= 255; cb /= 255; }
        r = cr; g = cg; b = cb;
      }

      // Triangulate (fan from first vertex)
      for (let j = 1; j < n - 1; j++) {
        const v0 = verts[faceVerts[0]];
        const v1 = verts[faceVerts[j]];
        const v2 = verts[faceVerts[j + 1]];
        if (!v0 || !v1 || !v2) continue;

        positions.push(v0[0], v0[1], v0[2]);
        positions.push(v1[0], v1[1], v1[2]);
        positions.push(v2[0], v2[1], v2[2]);

        // Same color for all 3 vertices of this triangle
        colors.push(r, g, b);
        colors.push(r, g, b);
        colors.push(r, g, b);
      }
    }

    return {
      positions: new Float32Array(positions),
      colors: new Float32Array(colors),
      hasColors,
    };
  }

  // --- Preview tab effect ---
  useEffect(() => {
    if (tab !== "preview") return;

    const timer = setTimeout(async () => {
      const ready = await ensureThree();
      if (!ready) return;

      // Resize
      const container = canvasContainerRef.current;
      if (container && rendererRef.current && cameraRef.current) {
        const rect = container.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) {
          rendererRef.current.setSize(rect.width, rect.height);
          cameraRef.current.aspect = rect.width / rect.height;
          cameraRef.current.updateProjectionMatrix();
        }
      }

      const currentCode = codeRef.current;
      if (currentCode) {
        compileAndRender(currentCode);
      } else {
        log("No code yet — paste or generate some");
      }
    }, 100);

    return () => clearTimeout(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, code]);

  // Resize on window resize
  useEffect(() => {
    function onResize() {
      if (tab !== "preview") return;
      const container = canvasContainerRef.current;
      if (!container || !rendererRef.current || !cameraRef.current) return;
      const rect = container.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;
      rendererRef.current.setSize(rect.width, rect.height);
      cameraRef.current.aspect = rect.width / rect.height;
      cameraRef.current.updateProjectionMatrix();
    }
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [tab]);

  // Cleanup worker on unmount
  useEffect(() => {
    return () => { workerRef.current?.terminate(); };
  }, []);

  // --- Mouse controls ---
  function onMouseDown(e: React.MouseEvent) {
    e.preventDefault();
    const o = orbitRef.current;
    o.startX = e.clientX;
    o.startY = e.clientY;
    if (e.button === 2 || e.shiftKey) {
      o.rightDown = true;
    } else {
      o.isDown = true;
    }
  }
  function onMouseMove(e: React.MouseEvent) {
    const o = orbitRef.current;
    if (!o.isDown && !o.rightDown) return;
    const dx = e.clientX - o.startX;
    const dy = e.clientY - o.startY;
    if (o.rightDown) {
      // Pan: move target in screen-space
      const panScale = o.dist * 0.002;
      const rightX = Math.cos(o.rotY);
      const rightY = Math.sin(o.rotY);
      o.targetX -= dx * panScale * rightX;
      o.targetY -= dx * panScale * rightY;
      o.targetZ += dy * panScale;
    } else {
      // Orbit
      o.rotY += dx * 0.005;
      o.rotX += dy * 0.005;
      o.rotX = Math.max(-Math.PI / 2 + 0.01, Math.min(Math.PI / 2 - 0.01, o.rotX));
    }
    o.startX = e.clientX;
    o.startY = e.clientY;
  }
  function onMouseUp() { orbitRef.current.isDown = false; orbitRef.current.rightDown = false; }
  function onContextMenu(e: React.MouseEvent) { e.preventDefault(); }
  function onWheel(e: React.WheelEvent) {
    orbitRef.current.dist = Math.max(1, orbitRef.current.dist * (1 + e.deltaY * 0.001));
  }

  // --- Keyboard controls (WASD + QE + Arrows) — only when the viewport is focused ---
  function onPreviewKeyDown(e: React.KeyboardEvent) {
    const key = e.key.toLowerCase();
    if (["w", "a", "s", "d", "q", "e", "arrowleft", "arrowright", "arrowup", "arrowdown"].includes(key)) {
      e.preventDefault();
      keysRef.current.add(key);
    }
  }
  function onPreviewKeyUp(e: React.KeyboardEvent) {
    keysRef.current.delete(e.key.toLowerCase());
  }

  return (
    <div className="h-full flex-1 flex flex-col bg-zinc-900 rounded-xl border border-zinc-700/50 min-h-0 overflow-hidden">
      {/* Tabs */}
      <div className="flex items-center border-b border-zinc-700/50 flex-shrink-0">
        <button
          onClick={() => setTab("code")}
          className={`px-4 py-2.5 text-xs font-semibold uppercase tracking-wider transition-colors ${
            tab === "code"
              ? "text-white border-b-2 border-violet-500"
              : "text-zinc-500 hover:text-zinc-300"
          }`}
        >
          OpenSCAD Code
        </button>
        <button
          onClick={() => { compiledCodeRef.current = ""; setTab("preview"); }}
          className={`px-4 py-2.5 text-xs font-semibold uppercase tracking-wider transition-colors ${
            tab === "preview"
              ? "text-white border-b-2 border-violet-500"
              : "text-zinc-500 hover:text-zinc-300"
          }`}
        >
          3D Preview
        </button>
        <div className="ml-auto flex items-center gap-3 pr-3">
          <button
            onClick={onRefine}
            disabled={!onRefine || refineLoading || cadLoading}
            className="text-xs px-2.5 py-1 bg-amber-600 text-white rounded hover:bg-amber-500 transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
          >
            {refineLoading ? (
              <>
                <svg className="animate-spin h-3 w-3" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                </svg>
                Refining...
              </>
            ) : "Refine"}
          </button>
          <button
            onClick={onUpdateCad}
            disabled={!onUpdateCad || cadLoading || refineLoading}
            className="text-xs px-2.5 py-1 bg-violet-600 text-white rounded hover:bg-violet-500 transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
          >
            {cadLoading ? (
              <>
                <svg className="animate-spin h-3 w-3" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                </svg>
                Generating...
              </>
            ) : "Update 3D"}
          </button>
        </div>
      </div>

      {/* Version history strip */}
      {modelIterations && modelIterations.length > 1 && (
        <div className="flex items-center gap-1.5 px-4 py-1.5 border-b border-zinc-800 flex-shrink-0">
          <span className="text-[10px] text-zinc-600 uppercase tracking-wider mr-0.5">History</span>
          {modelIterations.map((iter, i) => {
            const isLatest = i === modelIterations.length - 1;
            const isViewing = viewingVersionId === iter.id || (viewingVersionId == null && isLatest);
            return (
              <button
                key={iter.id}
                onClick={() => onSelectVersion?.(isLatest ? null : iter.id)}
                title={iter.reasoning}
                className={`text-[10px] px-1.5 py-0.5 rounded font-mono transition-colors ${
                  isViewing ? "bg-zinc-700 text-zinc-200" : "text-zinc-600 hover:text-zinc-400"
                }`}
              >
                v{i + 1}
              </button>
            );
          })}
          {viewingVersionId != null && (
            <button
              onClick={() => onSelectVersion?.(null)}
              className="ml-1 text-[10px] text-amber-400 hover:text-amber-300 transition-colors"
            >
              ← latest
            </button>
          )}
        </div>
      )}

      {/* Content area — both tabs always mounted, toggled via CSS */}
      <div className="flex-1 min-h-0 overflow-hidden relative">
        {/* Code tab — editable */}
        <div className={`absolute inset-0 flex flex-col overflow-hidden ${tab === "code" ? "" : "invisible pointer-events-none"}`}>
          <textarea
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="Paste OpenSCAD code here..."
            spellCheck={false}
            className="flex-1 w-full bg-transparent p-4 text-xs font-mono text-zinc-300 leading-relaxed resize-none focus:outline-none placeholder-zinc-600"
          />
          {code && (
            <div className="flex-shrink-0 border-t border-zinc-700/50 px-4 py-2 flex justify-end">
              <button
                onClick={() => { compiledCodeRef.current = ""; setTab("preview"); }}
                className="text-xs px-3 py-1.5 bg-violet-600 text-white rounded-md hover:bg-violet-700 transition-colors"
              >
                Preview
              </button>
            </div>
          )}
        </div>

        {/* 3D Preview tab — always mounted so canvas/scene persist */}
        <div
          className={`absolute inset-0 outline-none ${tab === "preview" ? "" : "invisible pointer-events-none"}`}
          tabIndex={0}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onMouseLeave={onMouseUp}
          onContextMenu={onContextMenu}
          onWheel={onWheel}
          onKeyDown={onPreviewKeyDown}
          onKeyUp={onPreviewKeyUp}
          onBlur={() => keysRef.current.clear()}
        >
          <div ref={canvasContainerRef} className="absolute inset-0" />

          {/* Compiling spinner */}
          {compiling && (
            <div className="absolute inset-0 flex items-center justify-center bg-white/60 pointer-events-none">
              <div className="flex items-center gap-2 bg-white px-4 py-2 rounded-lg shadow text-sm text-gray-700">
                <svg className="animate-spin h-4 w-4 text-violet-600" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Compiling with OpenSCAD WASM...
              </div>
            </div>
          )}

          {/* Debug log */}
          {tab === "preview" && (
            <div className="absolute bottom-2 left-2 text-[10px] text-gray-600 bg-white/90 px-2 py-1 rounded pointer-events-none font-mono max-w-[80%]">
              {debugLog.length === 0 ? "Initializing..." : debugLog.map((line, i) => (
                <div key={i}>{line}</div>
              ))}
            </div>
          )}

          {!code && tab === "preview" && (
            <div className="absolute inset-0 flex items-center justify-center text-gray-500 text-sm pointer-events-none">
              Paste or generate code first
            </div>
          )}
        </div>
      </div>

    </div>
  );
}
