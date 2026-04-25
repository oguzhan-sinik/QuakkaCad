// Web Worker: compiles OpenSCAD code to binary STL using WASM
let instance = null;

async function initOpenSCAD() {
  if (instance) return instance;

  // Load the Emscripten-generated JS module
  importScripts("/wasm/openscad.js");

  instance = await OpenSCAD({
    noInitialRun: true,
    locateFile: (path) => `/wasm/${path}`,
    print: (text) => self.postMessage({ type: "stdout", text }),
    printErr: (text) => self.postMessage({ type: "stderr", text }),
  });

  return instance;
}

self.onmessage = async (e) => {
  const { code, id } = e.data;

  try {
    self.postMessage({ type: "status", text: "Loading OpenSCAD WASM...", id });
    const inst = await initOpenSCAD();

    // Write input file
    inst.FS.writeFile("/input.scad", code);

    self.postMessage({ type: "status", text: "Compiling...", id });

    // Run OpenSCAD — compile to binary STL
    const exitCode = inst.callMain([
      "/input.scad",
      "-o", "/output.stl",
      "--export-format=binstl",
      "--backend=manifold",
    ]);

    if (exitCode !== 0) {
      self.postMessage({ type: "error", text: `OpenSCAD exited with code ${exitCode}`, id });
      return;
    }

    // Read output STL
    let stlData;
    try {
      stlData = inst.FS.readFile("/output.stl");
    } catch {
      self.postMessage({ type: "error", text: "No output generated — check your OpenSCAD code", id });
      return;
    }

    // Transfer the buffer (zero-copy)
    self.postMessage(
      { type: "result", stl: stlData.buffer, id },
      [stlData.buffer]
    );

    // Cleanup output file
    try { inst.FS.unlink("/output.stl"); } catch {}
    try { inst.FS.unlink("/input.scad"); } catch {}
  } catch (err) {
    self.postMessage({ type: "error", text: err.message || String(err), id });
  }
};
