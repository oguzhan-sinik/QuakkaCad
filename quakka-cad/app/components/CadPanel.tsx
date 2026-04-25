"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type Tab = "code" | "preview";

interface GenerateResult {
  openscad_code: string;
  provider: string;
  model_used: string;
  latency_ms: number;
  usage: Record<string, number>;
  tokens_per_second: number | null;
}

export default function CadPanel() {
  const [tab, setTab] = useState<Tab>("code");
  const [prompt, setPrompt] = useState("");
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [debugLog, setDebugLog] = useState<string[]>([]);
  const [meta, setMeta] = useState<{
    provider: string;
    latency_ms: number;
    tokens_per_second: number | null;
  } | null>(null);

  const canvasContainerRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<any>(null);
  const rendererRef = useRef<any>(null);
  const cameraRef = useRef<any>(null);
  const frameRef = useRef<number>(0);
  const THREERef = useRef<any>(null);
  const codeRef = useRef(code);
  codeRef.current = code;

  // Mouse orbit state
  const orbitRef = useRef({
    isDown: false,
    startX: 0,
    startY: 0,
    rotX: -0.4,
    rotY: 0.6,
    dist: 100,
    panX: 0,
    panY: 0,
  });

  function log(msg: string) {
    console.log(`[CadPanel] ${msg}`);
    setDebugLog(prev => [...prev.slice(-9), msg]);
  }

  async function ensureThree() {
    if (THREERef.current && rendererRef.current && sceneRef.current) {
      return true;
    }

    const container = canvasContainerRef.current;
    if (!container) {
      log("ERROR: canvas container ref is null");
      return false;
    }

    const rect = container.getBoundingClientRect();
    log(`Container size: ${Math.round(rect.width)}x${Math.round(rect.height)}`);

    if (rect.width === 0 || rect.height === 0) {
      log("ERROR: container has zero dimensions");
      return false;
    }

    try {
      const THREE = await import("three");
      THREERef.current = THREE;

      // Create canvas element
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

      // Lights
      scene.add(new THREE.AmbientLight(0xffffff, 0.6));
      const dir1 = new THREE.DirectionalLight(0xffffff, 0.8);
      dir1.position.set(5, 10, 7);
      scene.add(dir1);
      const dir2 = new THREE.DirectionalLight(0xffffff, 0.3);
      dir2.position.set(-5, -3, -5);
      scene.add(dir2);

      // Grid on XY plane
      const grid = new THREE.GridHelper(200, 20, 0xcccccc, 0xe5e5e5);
      grid.rotation.x = Math.PI / 2;
      scene.add(grid);

      // Animation loop
      function animate() {
        frameRef.current = requestAnimationFrame(animate);
        const o = orbitRef.current;
        camera.position.set(
          o.panX + o.dist * Math.sin(o.rotY) * Math.cos(o.rotX),
          o.panY + o.dist * Math.sin(o.rotX),
          o.dist * Math.cos(o.rotY) * Math.cos(o.rotX)
        );
        camera.lookAt(new THREE.Vector3(o.panX, o.panY, 0));
        renderer.render(scene, camera);
      }
      animate();

      log(`Three.js initialized OK. GL context: ${!!renderer.getContext()}`);
      return true;
    } catch (e: any) {
      log(`ERROR initializing Three.js: ${e.message}`);
      return false;
    }
  }

  function addTestCube() {
    const THREE = THREERef.current;
    const scene = sceneRef.current;
    if (!THREE || !scene) return;
    const geom = new THREE.BoxGeometry(20, 20, 20);
    const mat = new THREE.MeshPhongMaterial({ color: 0x4285f4 });
    const mesh = new THREE.Mesh(geom, mat);
    mesh.position.set(10, 10, 10);
    scene.add(mesh);
    orbitRef.current.dist = 80;
    orbitRef.current.panX = 10;
    orbitRef.current.panY = 10;
    log("TEST CUBE added at (10,10,10) size 20");
  }

  function renderOpenSCAD(scadCode: string) {
    const THREE = THREERef.current;
    const scene = sceneRef.current;
    if (!THREE || !scene) {
      log("renderOpenSCAD: THREE or scene missing");
      return;
    }

    // Remove old meshes (keep lights and grid)
    const toRemove: any[] = [];
    scene.traverse((child: any) => { if (child.isMesh) toRemove.push(child); });
    log(`Removing ${toRemove.length} old mesh(es)`);
    toRemove.forEach((m: any) => { scene.remove(m); m.geometry?.dispose(); });

    // Log first 200 chars of code for debugging
    log(`Code starts with: ${scadCode.substring(0, 200).replace(/\n/g, " ")}`);

    try {
      colorIdx = 0;
      const ast = scadParse(scadCode);
      log(`Parsed AST: ${ast.length} top-level node(s): [${ast.map((n: any) => n?.op || "null").join(", ")}]`);

      if (ast.length === 0) {
        log("WARNING: Parser produced empty AST. Adding test cube instead.");
        addTestCube();
        return;
      }

      const meshes = scadRender(THREE, ast, new THREE.Matrix4(), null, "add");
      log(`Rendered ${meshes.length} mesh(es)`);

      if (meshes.length === 0) {
        log("WARNING: Renderer produced 0 meshes from AST. Adding test cube.");
        addTestCube();
        return;
      }

      meshes.forEach((m: any) => scene.add(m));

      // Auto-fit camera
      const box = new THREE.Box3();
      scene.traverse((c: any) => { if (c.isMesh) box.expandByObject(c); });
      if (!box.isEmpty()) {
        const center = box.getCenter(new THREE.Vector3());
        const size = box.getSize(new THREE.Vector3());
        orbitRef.current.dist = Math.max(size.x, size.y, size.z) * 2.5;
        orbitRef.current.panX = center.x;
        orbitRef.current.panY = center.y;
        log(`Camera: center=(${center.x.toFixed(1)},${center.y.toFixed(1)},${center.z.toFixed(1)}) dist=${orbitRef.current.dist.toFixed(1)}`);
      } else {
        log("WARNING: bounding box empty after adding meshes");
      }
    } catch (e: any) {
      log(`Parse/render ERROR: ${e.message}`);
      console.error("OpenSCAD full error:", e);
      // Still show test cube so we know Three.js works
      addTestCube();
    }
  }

  // When user switches to preview tab, init three + render
  useEffect(() => {
    if (tab !== "preview") return;

    log("Preview tab activated — initializing...");

    // Use a small timeout to ensure DOM is laid out
    const timer = setTimeout(async () => {
      const ready = await ensureThree();
      if (!ready) {
        log("Three.js init failed — cannot show preview");
        return;
      }

      // Resize to actual visible dimensions
      const container = canvasContainerRef.current;
      if (container && rendererRef.current && cameraRef.current) {
        const rect = container.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) {
          rendererRef.current.setSize(rect.width, rect.height);
          cameraRef.current.aspect = rect.width / rect.height;
          cameraRef.current.updateProjectionMatrix();
          log(`Resized to ${Math.round(rect.width)}x${Math.round(rect.height)}`);
        } else {
          log(`WARNING: container size is ${rect.width}x${rect.height}`);
        }
      }

      const currentCode = codeRef.current;
      if (currentCode) {
        log(`Rendering ${currentCode.length} chars of OpenSCAD code...`);
        renderOpenSCAD(currentCode);
      } else {
        log("No code to render yet — generate something first");
      }
    }, 100);

    return () => clearTimeout(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, code]);

  // Handle window resize
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

  // Mouse controls
  function onMouseDown(e: React.MouseEvent) {
    orbitRef.current.isDown = true;
    orbitRef.current.startX = e.clientX;
    orbitRef.current.startY = e.clientY;
  }
  function onMouseMove(e: React.MouseEvent) {
    if (!orbitRef.current.isDown) return;
    const dx = e.clientX - orbitRef.current.startX;
    const dy = e.clientY - orbitRef.current.startY;
    if (e.shiftKey) {
      orbitRef.current.panX -= dx * 0.3;
      orbitRef.current.panY += dy * 0.3;
    } else {
      orbitRef.current.rotY += dx * 0.005;
      orbitRef.current.rotX -= dy * 0.005;
      orbitRef.current.rotX = Math.max(-Math.PI / 2 + 0.01, Math.min(Math.PI / 2 - 0.01, orbitRef.current.rotX));
    }
    orbitRef.current.startX = e.clientX;
    orbitRef.current.startY = e.clientY;
  }
  function onMouseUp() {
    orbitRef.current.isDown = false;
  }
  function onWheel(e: React.WheelEvent) {
    orbitRef.current.dist = Math.max(5, orbitRef.current.dist * (1 + e.deltaY * 0.001));
  }

  // Generate
  async function handleGenerate() {
    if (!prompt.trim() || loading) return;
    setLoading(true);
    setError(null);

    try {
      const res = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: prompt.trim(),
          provider: "pydantic",
          temperature: 0.75,
          max_tokens: 8192,
        }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || `HTTP ${res.status}`);
      }
      const data: GenerateResult = await res.json();
      setCode(data.openscad_code);
      setMeta({
        provider: data.provider,
        latency_ms: data.latency_ms,
        tokens_per_second: data.tokens_per_second,
      });
      setTab("code");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleGenerate();
    }
  }

  return (
    <div className="flex-1 flex flex-col bg-zinc-900 rounded-xl border border-zinc-700/50 min-h-0 overflow-hidden">
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
          onClick={() => setTab("preview")}
          className={`px-4 py-2.5 text-xs font-semibold uppercase tracking-wider transition-colors ${
            tab === "preview"
              ? "text-white border-b-2 border-violet-500"
              : "text-zinc-500 hover:text-zinc-300"
          }`}
        >
          3D Preview
        </button>
        {meta && (
          <div className="ml-auto pr-3 text-[10px] text-zinc-500 flex gap-3">
            <span>{meta.provider}</span>
            <span>{Math.round(meta.latency_ms)}ms</span>
            {meta.tokens_per_second && <span>{meta.tokens_per_second} tok/s</span>}
          </div>
        )}
      </div>

      {/* Content area */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {/* Code tab — editable */}
        {tab === "code" && (
          <div className="h-full flex flex-col overflow-hidden">
            <textarea
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="Paste OpenSCAD code here or generate with a prompt below..."
              spellCheck={false}
              className="flex-1 w-full bg-transparent p-4 text-xs font-mono text-zinc-300 leading-relaxed resize-none focus:outline-none placeholder-zinc-600"
            />
            {code && (
              <div className="flex-shrink-0 border-t border-zinc-700/50 px-4 py-2 flex justify-end">
                <button
                  onClick={() => setTab("preview")}
                  className="text-xs px-3 py-1.5 bg-violet-600 text-white rounded-md hover:bg-violet-700 transition-colors"
                >
                  Preview
                </button>
              </div>
            )}
          </div>
        )}

        {/* 3D Preview tab */}
        {tab === "preview" && (
          <div
            className="h-full w-full relative"
            onMouseDown={onMouseDown}
            onMouseMove={onMouseMove}
            onMouseUp={onMouseUp}
            onMouseLeave={onMouseUp}
            onWheel={onWheel}
          >
            <div ref={canvasContainerRef} className="absolute inset-0" />
            {/* Debug overlay */}
            <div className="absolute bottom-2 left-2 text-[10px] text-gray-600 bg-white/90 px-2 py-1 rounded pointer-events-none font-mono max-w-[80%]">
              {debugLog.length === 0 ? "Initializing..." : debugLog.map((line, i) => (
                <div key={i}>{line}</div>
              ))}
            </div>
            {!code && (
              <div className="absolute inset-0 flex items-center justify-center text-gray-500 text-sm pointer-events-none">
                Generate code first to see 3D preview
              </div>
            )}
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="px-4 py-2 bg-red-500/10 border-t border-red-500/30 text-red-400 text-xs flex-shrink-0">
          {error}
        </div>
      )}

      {/* Prompt input */}
      <div className="flex-shrink-0 border-t border-zinc-700/50 p-3">
        <div className="flex gap-2">
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Describe a 3D object... (Ctrl+Enter to generate)"
            rows={2}
            className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 placeholder-zinc-500 resize-none focus:outline-none focus:border-violet-500 transition-colors"
          />
          <button
            onClick={handleGenerate}
            disabled={loading || !prompt.trim()}
            className="px-4 py-2 bg-violet-600 text-white text-sm font-medium rounded-lg hover:bg-violet-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors self-end"
          >
            {loading ? (
              <span className="flex items-center gap-1.5">
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              </span>
            ) : (
              "Generate"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

// ============================================================
// OpenSCAD Tokenizer
// ============================================================
function scadTokenize(code: string) {
  code = code.replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
  const tokens: { t: string; v: any }[] = [];
  const re = /("(?:[^"\\]|\\.)*")|(\d+\.?\d*(?:e[+-]?\d+)?)|([a-zA-Z_$]\w*)|([{}()\[\];,=+\-*/%<>!&|?:])/g;
  let m;
  while ((m = re.exec(code)) !== null) {
    if (m[1]) tokens.push({ t: "str", v: m[1].slice(1, -1) });
    else if (m[2]) tokens.push({ t: "num", v: parseFloat(m[2]) });
    else if (m[3]) tokens.push({ t: "id", v: m[3] });
    else if (m[4]) tokens.push({ t: "sym", v: m[4] });
  }
  return tokens;
}

// ============================================================
// OpenSCAD Parser: tokens -> AST
// ============================================================
function scadParse(code: string) {
  const tokens = scadTokenize(code);
  let pos = 0;
  const peek = () => tokens[pos] || null;
  const next = () => tokens[pos++] || null;
  const expect = (t: string, v?: any) => {
    const tk = next();
    if (!tk || tk.t !== t || (v !== undefined && tk.v !== v))
      throw new Error(`Expected ${t}:${v} got ${tk?.t}:${tk?.v}`);
    return tk;
  };
  const at = (t: string, v?: any) => {
    const tk = peek();
    return tk && tk.t === t && (v === undefined || tk.v === v);
  };

  const vars: Record<string, any> = {};
  const modules: Record<string, any[]> = {};

  function parseExpr(): any {
    return parseTernary();
  }

  function parseTernary(): any {
    const cond = parseComparison();
    if (at("sym", "?")) {
      next();
      const a = parseExpr();
      expect("sym", ":");
      const b = parseExpr();
      return cond ? a : b;
    }
    return cond;
  }

  function parseComparison(): any {
    let left = parseAddSub();
    while (at("sym", "<") || at("sym", ">") || at("sym", "=") || at("sym", "!")) {
      const op1 = peek()!.v;
      // Handle ==, !=, <=, >=
      if (op1 === "=" && tokens[pos + 1]?.v === "=") {
        next(); next();
        const right = parseAddSub();
        left = left === right ? 1 : 0;
      } else if (op1 === "!" && tokens[pos + 1]?.v === "=") {
        next(); next();
        const right = parseAddSub();
        left = left !== right ? 1 : 0;
      } else if (op1 === "<" && tokens[pos + 1]?.v === "=") {
        next(); next();
        const right = parseAddSub();
        left = left <= right ? 1 : 0;
      } else if (op1 === ">" && tokens[pos + 1]?.v === "=") {
        next(); next();
        const right = parseAddSub();
        left = left >= right ? 1 : 0;
      } else if (op1 === "<") {
        next();
        const right = parseAddSub();
        left = left < right ? 1 : 0;
      } else if (op1 === ">") {
        next();
        const right = parseAddSub();
        left = left > right ? 1 : 0;
      } else {
        break;
      }
    }
    return left;
  }

  function parseAddSub(): any {
    let left = parseMulDiv();
    while (at("sym", "+") || at("sym", "-")) {
      const op = next()!.v;
      const right = parseMulDiv();
      left = op === "+" ? left + right : left - right;
    }
    return left;
  }

  function parseMulDiv(): any {
    let left = parseUnary();
    while (at("sym", "*") || at("sym", "/") || at("sym", "%")) {
      const op = next()!.v;
      const right = parseUnary();
      if (op === "*") left = left * right;
      else if (op === "/") left = left / right;
      else left = left % right;
    }
    return left;
  }

  function parseUnary(): any {
    if (at("sym", "-")) { next(); return -parsePrimExpr(); }
    if (at("sym", "+")) { next(); return parsePrimExpr(); }
    if (at("sym", "!")) { next(); return parsePrimExpr() ? 0 : 1; }
    return parsePrimExpr();
  }

  function parsePrimExpr(): any {
    if (at("num")) return next()!.v;
    if (at("str")) return next()!.v;
    if (at("id", "true")) { next(); return 1; }
    if (at("id", "false")) { next(); return 0; }
    if (at("id", "undef")) { next(); return undefined; }
    if (at("sym", "(")) { next(); const v = parseExpr(); expect("sym", ")"); return v; }
    if (at("sym", "[")) return parseVector();
    if (at("id")) {
      const name = peek()!.v;
      const mathFns: Record<string, Function> = {
        sin: Math.sin, cos: Math.cos, tan: Math.tan, abs: Math.abs,
        sqrt: Math.sqrt, round: Math.round, ceil: Math.ceil, floor: Math.floor,
        min: Math.min, max: Math.max, pow: Math.pow, atan2: Math.atan2,
        asin: (v: number) => Math.asin(v) * 180 / Math.PI,
        acos: (v: number) => Math.acos(v) * 180 / Math.PI,
        atan: (v: number) => Math.atan(v) * 180 / Math.PI,
        len: (v: any) => Array.isArray(v) ? v.length : 0,
        concat: (...args: any[]) => args.flat(),
        str: (...args: any[]) => args.join(""),
      };
      if (mathFns[name]) {
        next();
        if (at("sym", "(")) {
          next();
          const args: any[] = [];
          while (!at("sym", ")") && peek()) {
            args.push(parseExpr());
            if (at("sym", ",")) next();
          }
          if (at("sym", ")")) next();
          if (["sin", "cos", "tan"].includes(name)) return mathFns[name](args[0] * Math.PI / 180);
          return mathFns[name](...args);
        }
      }
      if (vars[name] !== undefined) {
        next();
        // Array index: name[i]
        if (at("sym", "[")) {
          next();
          const idx = parseExpr();
          expect("sym", "]");
          return Array.isArray(vars[name]) ? vars[name][idx] : 0;
        }
        return vars[name];
      }
      next(); return 0;
    }
    if (peek()) next();
    return 0;
  }

  function parseVector(): any[] {
    expect("sym", "[");

    // List comprehension: [for (...) expr] — skip, return empty
    if (at("id", "for") || at("id", "if") || at("id", "let") || at("id", "each")) {
      let depth = 1;
      while (depth > 0 && peek()) {
        if (at("sym", "[")) depth++;
        if (at("sym", "]")) { depth--; if (depth === 0) break; }
        next();
      }
      if (at("sym", "]")) next();
      return [];
    }

    const vals: any[] = [];
    while (!at("sym", "]") && peek()) {
      vals.push(parseExpr());
      // Range expression: [start:end] or [start:step:end]
      if (at("sym", ":")) {
        const start = vals.pop() ?? 0;
        next(); // skip ':'
        const second = parseExpr();
        if (at("sym", ":")) {
          next(); // skip second ':'
          const end = parseExpr();
          // [start:step:end]
          const step = second;
          const range: number[] = [];
          if (step > 0) { for (let i = start; i <= end; i += step) range.push(i); }
          else if (step < 0) { for (let i = start; i >= end; i += step) range.push(i); }
          vals.push(...range);
        } else {
          // [start:end] — step = 1
          const range: number[] = [];
          for (let i = start; i <= second; i++) range.push(i);
          vals.push(...range);
        }
      }
      if (at("sym", ",")) next();
    }
    if (at("sym", "]")) next();
    return vals;
  }

  function parseNamedArgs() {
    expect("sym", "(");
    const named: Record<string, any> = {};
    const positional: any[] = [];
    while (!at("sym", ")") && peek()) {
      if (at("id") && tokens[pos + 1]?.v === "=") {
        const key = next()!.v;
        next(); // skip '='
        named[key] = parseExpr();
      } else {
        positional.push(parseExpr());
      }
      if (at("sym", ",")) next();
    }
    if (at("sym", ")")) next();
    return { named, positional };
  }

  function parseChildren(): any[] {
    if (at("sym", "{")) {
      next();
      const children: any[] = [];
      while (!at("sym", "}") && peek()) {
        try {
          const stmts = parseStatement();
          if (stmts) children.push(...(Array.isArray(stmts) ? stmts : [stmts]));
        } catch (e) {
          console.warn("[scadParse] Skipping in block:", (e as Error).message);
          next();
        }
      }
      if (at("sym", "}")) next();
      return children;
    } else {
      try {
        const s = parseStatement();
        return s ? (Array.isArray(s) ? s : [s]) : [];
      } catch (e) {
        console.warn("[scadParse] Skipping child:", (e as Error).message);
        next();
        return [];
      }
    }
  }

  function parseStatement(): any {
    if (!peek()) return null;
    if (at("sym", ";")) { next(); return null; }

    // Variable assignment
    if (at("id") && tokens[pos + 1]?.v === "=" && tokens[pos + 1]?.t === "sym") {
      // Check it's not ==
      if (tokens[pos + 2]?.v !== "=") {
        const name = next()!.v;
        next();
        vars[name] = parseExpr();
        if (at("sym", ";")) next();
        return null;
      }
    }

    // Module definition
    if (at("id", "module")) {
      next();
      const name = next()?.v || "anon";
      if (at("sym", "(")) {
        let depth = 1; next();
        while (depth > 0 && peek()) {
          if (at("sym", "(")) depth++;
          if (at("sym", ")")) depth--;
          next();
        }
      }
      const startPos = pos;
      if (at("sym", "{")) {
        let depth = 1; next();
        while (depth > 0 && peek()) {
          if (peek()!.v === "{") depth++;
          if (peek()!.v === "}") depth--;
          if (depth > 0) next(); else { next(); break; }
        }
      }
      modules[name] = tokens.slice(startPos, pos);
      return null;
    }

    // function definition - skip
    if (at("id", "function")) {
      while (peek() && !at("sym", ";")) next();
      if (at("sym", ";")) next();
      return null;
    }

    // use/include - skip
    if (at("id", "use") || at("id", "include")) {
      while (peek() && !at("sym", ";") && !at("sym", ">")) next();
      if (at("sym", ">")) next();
      if (at("sym", ";")) next();
      return null;
    }

    // for/if/let/each
    if (at("id", "for") || at("id", "if") || at("id", "let") || at("id", "each")) {
      next();
      if (at("sym", "(")) {
        let depth = 1; next();
        while (depth > 0 && peek()) {
          if (at("sym", "(")) depth++;
          if (at("sym", ")")) depth--;
          next();
        }
      }
      return parseChildren();
    }

    // Modifier prefixes: !, *, #, %
    if (at("sym", "!") || at("sym", "#") || at("sym", "%") || at("sym", "*")) {
      next();
      return parseStatement();
    }

    if (at("id")) {
      const name = next()!.v;
      const transforms = ["translate", "rotate", "scale", "mirror", "resize", "multmatrix"];
      const csgOps = ["union", "difference", "intersection", "hull", "render", "minkowski"];
      const primitives = ["cube", "cylinder", "sphere", "polyhedron"];

      if (transforms.includes(name)) {
        const args = parseNamedArgs();
        const children = parseChildren();
        return { op: name, args, children };
      }

      if (name === "color") {
        const args = parseNamedArgs();
        const children = parseChildren();
        return { op: "color", args, children };
      }

      if (name === "linear_extrude") {
        const args = parseNamedArgs();
        const children = parseChildren();
        return { op: "linear_extrude", args, children };
      }

      if (name === "rotate_extrude") {
        const args = parseNamedArgs();
        const children = parseChildren();
        return { op: "rotate_extrude", args, children };
      }

      if (csgOps.includes(name)) {
        if (at("sym", "(")) parseNamedArgs();
        const children = parseChildren();
        return { op: name, children };
      }

      if (primitives.includes(name)) {
        const args = parseNamedArgs();
        if (at("sym", ";")) next();
        return { op: name, args };
      }

      // 2D primitives
      if (name === "circle" || name === "square" || name === "polygon" || name === "text") {
        const args = parseNamedArgs();
        if (at("sym", ";")) next();
        return { op: name, args };
      }

      // Module call
      if (modules[name]) {
        if (at("sym", "(")) parseNamedArgs();
        if (at("sym", ";")) next();
        else if (at("sym", "{")) parseChildren();
        // Inline module body by re-parsing
        const saved = { p: pos, t: [...tokens] };
        const moduleTokens = [...modules[name]];
        tokens.splice(pos, tokens.length - pos, ...moduleTokens);
        const result = parseChildren();
        tokens.splice(pos, tokens.length - pos, ...saved.t.slice(saved.p));
        return result;
      }

      // Unknown identifier - skip
      if (at("sym", "(")) parseNamedArgs();
      if (at("sym", "{")) parseChildren();
      if (at("sym", ";")) next();
      return null;
    }

    next();
    return null;
  }

  const ast: any[] = [];
  while (peek()) {
    try {
      const s = parseStatement();
      if (s) ast.push(...(Array.isArray(s) ? s : [s]));
    } catch (e) {
      // Skip problematic token and continue parsing
      console.warn("[scadParse] Skipping token due to error:", (e as Error).message, "at pos", pos, "token:", peek());
      next();
    }
  }
  return ast;
}

// ============================================================
// OpenSCAD Renderer: AST -> Three.js meshes
// ============================================================
const COLORS = [0x4285f4, 0x34a853, 0xfbbc04, 0xea4335, 0x9c27b0, 0x00bcd4];
let colorIdx = 0;

function scadRender(THREE: any, nodes: any[], parentMatrix: any, currentColor: number | null, csgMode: string): any[] {
  if (!Array.isArray(nodes)) nodes = [nodes];
  const meshes: any[] = [];

  for (const node of nodes) {
    if (!node || !node.op) continue;
    const { op, args, children } = node;

    switch (op) {
      case "translate": {
        const v = args?.positional?.[0] || args?.named?.v || [0, 0, 0];
        const m = new THREE.Matrix4().makeTranslation(v[0] || 0, v[1] || 0, v[2] || 0);
        const combined = parentMatrix.clone().multiply(m);
        meshes.push(...scadRender(THREE, children || [], combined, currentColor, csgMode));
        break;
      }
      case "rotate": {
        const v = args?.positional?.[0] || [0, 0, 0];
        const m = new THREE.Matrix4();
        if (Array.isArray(v)) {
          const rx = (v[0] || 0) * Math.PI / 180;
          const ry = (v[1] || 0) * Math.PI / 180;
          const rz = (v[2] || 0) * Math.PI / 180;
          m.makeRotationZ(rz)
            .multiply(new THREE.Matrix4().makeRotationY(ry))
            .multiply(new THREE.Matrix4().makeRotationX(rx));
        } else {
          m.makeRotationZ(((typeof v === "number" ? v : 0) * Math.PI) / 180);
        }
        const combined = parentMatrix.clone().multiply(m);
        meshes.push(...scadRender(THREE, children || [], combined, currentColor, csgMode));
        break;
      }
      case "scale": {
        const v = args?.positional?.[0] || [1, 1, 1];
        let sx: number, sy: number, sz: number;
        if (Array.isArray(v)) { sx = v[0] || 1; sy = v[1] || 1; sz = v[2] || 1; }
        else { sx = sy = sz = typeof v === "number" ? v : 1; }
        const m = new THREE.Matrix4().makeScale(sx, sy, sz);
        const combined = parentMatrix.clone().multiply(m);
        meshes.push(...scadRender(THREE, children || [], combined, currentColor, csgMode));
        break;
      }
      case "mirror": {
        const v = args?.positional?.[0] || [1, 0, 0];
        const m = new THREE.Matrix4().makeScale(v[0] ? -1 : 1, v[1] ? -1 : 1, v[2] ? -1 : 1);
        const combined = parentMatrix.clone().multiply(m);
        meshes.push(...scadRender(THREE, children || [], combined, currentColor, csgMode));
        break;
      }
      case "color": {
        let col = null;
        const cv = args?.positional?.[0] || args?.named?.c;
        if (typeof cv === "string") {
          col = new THREE.Color(cv);
        } else if (Array.isArray(cv) && cv.length >= 3) {
          col = new THREE.Color(cv[0], cv[1], cv[2]);
        }
        meshes.push(...scadRender(THREE, children || [], parentMatrix, col ? col.getHex() : currentColor, csgMode));
        break;
      }
      case "union":
      case "hull":
      case "render":
      case "minkowski": {
        meshes.push(...scadRender(THREE, children || [], parentMatrix, currentColor, "add"));
        break;
      }
      case "difference": {
        if (children && children.length > 0) {
          meshes.push(...scadRender(THREE, [children[0]], parentMatrix, currentColor, "add"));
          for (let i = 1; i < children.length; i++) {
            meshes.push(...scadRender(THREE, [children[i]], parentMatrix, currentColor, "subtract"));
          }
        }
        break;
      }
      case "intersection": {
        meshes.push(...scadRender(THREE, children || [], parentMatrix, currentColor, "add"));
        break;
      }
      case "linear_extrude": {
        const h = args?.named?.height || args?.positional?.[0] || 10;
        const center = args?.named?.center;
        if (children) {
          for (const child of children) {
            if (child?.op === "circle") {
              const r = child.args?.named?.r || (child.args?.named?.d ? child.args.named.d / 2 : null) || child.args?.positional?.[0] || 5;
              const geom = new THREE.CylinderGeometry(r, r, h, 48);
              geom.rotateX(Math.PI / 2);
              if (!center) geom.translate(0, 0, h / 2);
              meshes.push(makeMesh(THREE, geom, parentMatrix, currentColor, csgMode));
            } else if (child?.op === "square") {
              const sv = child.args?.positional?.[0] || child.args?.named?.size || 10;
              let sx: number, sy: number;
              if (Array.isArray(sv)) { sx = sv[0]; sy = sv[1]; } else { sx = sy = sv; }
              const cc = child.args?.named?.center;
              const geom = new THREE.BoxGeometry(sx, sy, h);
              if (!cc) geom.translate(sx / 2, sy / 2, 0);
              if (!center) geom.translate(0, 0, h / 2);
              meshes.push(makeMesh(THREE, geom, parentMatrix, currentColor, csgMode));
            } else {
              // Recurse — might be a transform wrapping a 2D shape
              meshes.push(...scadRender(THREE, [child], parentMatrix, currentColor, csgMode));
            }
          }
        }
        break;
      }
      case "rotate_extrude": {
        if (children) {
          for (const child of children) {
            if (child?.op === "circle") {
              const r = child.args?.named?.r || (child.args?.named?.d ? child.args.named.d / 2 : null) || child.args?.positional?.[0] || 5;
              const ringR = 10;
              const geom = new THREE.TorusGeometry(ringR, r, 24, 48);
              meshes.push(makeMesh(THREE, geom, parentMatrix, currentColor, csgMode));
            }
          }
        }
        break;
      }
      case "cube": {
        const sv = args?.positional?.[0] || args?.named?.size || 10;
        let x: number, y: number, z: number;
        if (Array.isArray(sv)) { x = sv[0] || 1; y = sv[1] || 1; z = sv[2] || 1; }
        else { x = y = z = typeof sv === "number" ? sv : 10; }
        const center = args?.named?.center;
        const geom = new THREE.BoxGeometry(x, y, z);
        if (!center) geom.translate(x / 2, y / 2, z / 2);
        meshes.push(makeMesh(THREE, geom, parentMatrix, currentColor, csgMode));
        break;
      }
      case "cylinder": {
        const n = args?.named || {};
        const p = args?.positional || [];
        const h = n.h ?? n.height ?? p[0] ?? 10;
        let r1: number, r2: number;
        if (n.r !== undefined) { r1 = r2 = n.r; }
        else if (n.d !== undefined) { r1 = r2 = n.d / 2; }
        else {
          r1 = n.r1 ?? (n.d1 !== undefined ? n.d1 / 2 : p[1] ?? 5);
          r2 = n.r2 ?? (n.d2 !== undefined ? n.d2 / 2 : p[2] ?? r1);
        }
        const center = n.center;
        const segments = n["$fn"] || 48;
        const geom = new THREE.CylinderGeometry(r2, r1, h, segments);
        geom.rotateX(Math.PI / 2);
        if (!center) geom.translate(0, 0, h / 2);
        meshes.push(makeMesh(THREE, geom, parentMatrix, currentColor, csgMode));
        break;
      }
      case "sphere": {
        const n = args?.named || {};
        const p = args?.positional || [];
        const r = n.r ?? (n.d !== undefined ? n.d / 2 : null) ?? p[0] ?? 10;
        const geom = new THREE.SphereGeometry(r, 32, 32);
        meshes.push(makeMesh(THREE, geom, parentMatrix, currentColor, csgMode));
        break;
      }
      default: {
        if (children) meshes.push(...scadRender(THREE, children, parentMatrix, currentColor, csgMode));
        break;
      }
    }
  }
  return meshes;
}

function makeMesh(THREE: any, geom: any, matrix: any, color: number | null, csgMode: string) {
  const c = color ?? COLORS[colorIdx++ % COLORS.length];
  const isSubtract = csgMode === "subtract";
  const mat = new THREE.MeshPhongMaterial({
    color: isSubtract ? 0xff4444 : c,
    shininess: 60,
    transparent: isSubtract,
    opacity: isSubtract ? 0.15 : 1.0,
    side: THREE.DoubleSide,
    wireframe: isSubtract,
  });
  const mesh = new THREE.Mesh(geom, mat);
  mesh.applyMatrix4(matrix);
  return mesh;
}
