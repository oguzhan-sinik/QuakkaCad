// Web Worker (module): compiles OpenSCAD code using WASM
// Creates a fresh WASM instance per compilation (callMain can only run once)
let OpenSCADFactory = null;

async function loadFactory() {
  if (OpenSCADFactory) return OpenSCADFactory;
  const mod = await import("/wasm/openscad.js");
  OpenSCADFactory = mod.default;
  return OpenSCADFactory;
}

self.onmessage = async (e) => {
  const { code, id } = e.data;
  const stderrLines = [];

  try {
    self.postMessage({ type: "status", text: "Loading OpenSCAD WASM...", id });
    const factory = await loadFactory();

    // Fresh instance each time (callMain can only be called once)
    const instance = await factory({
      noInitialRun: true,
      locateFile: (path) => `/wasm/${path}`,
      print: (text) => self.postMessage({ type: "stdout", text, id }),
      printErr: (text) => {
        stderrLines.push(text);
        self.postMessage({ type: "stderr", text, id });
      },
    });

    // Write input file
    instance.FS.writeFile("/input.scad", code);

    self.postMessage({ type: "status", text: "Compiling...", id });

    // Try OFF first (has colors), fall back to binstl
    let format = "off";
    let outFile = "/output.off";
    let exitCode = instance.callMain([
      "/input.scad",
      "-o", outFile,
      "--backend=manifold",
    ]);

    if (exitCode !== 0) {
      // Send stderr as error detail
      const errDetail = stderrLines.filter(l => l.includes("ERROR") || l.includes("error")).join("; ");
      self.postMessage({ type: "error", text: errDetail || `OpenSCAD exited with code ${exitCode}`, id });
      return;
    }

    // Read output
    let outputData;
    try {
      outputData = instance.FS.readFile(outFile, { encoding: "utf8" });
    } catch {
      self.postMessage({ type: "error", text: "No output generated — check your OpenSCAD code", id });
      return;
    }

    // Check if it's actually valid OFF
    if (typeof outputData === "string" && (outputData.startsWith("OFF") || outputData.startsWith("COFF"))) {
      self.postMessage({ type: "result", off: outputData, format: "off", id });
    } else {
      // Fallback: try reading as binary STL
      try {
        const stlData = instance.FS.readFile(outFile);
        const buf = stlData.buffer.slice(stlData.byteOffset, stlData.byteOffset + stlData.byteLength);
        self.postMessage({ type: "result", stl: buf, format: "stl", id }, [buf]);
      } catch {
        // Send whatever we got as OFF anyway
        self.postMessage({ type: "result", off: String(outputData), format: "off", id });
      }
    }
  } catch (err) {
    self.postMessage({ type: "error", text: err.message || String(err), id });
  }
};
