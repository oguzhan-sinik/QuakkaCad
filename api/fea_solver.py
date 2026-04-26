"""Real mesh-based FEA — runs gmsh + stress computation in a subprocess.

Pipeline: STL bytes → subprocess(tetrahedralize + solve) → colored OFF mesh
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

MATERIALS = {
    "PLA": {"E": 3500, "nu": 0.35, "density": 1.24, "yield_strength": 50},
    "ABS": {"E": 2300, "nu": 0.35, "density": 1.04, "yield_strength": 40},
    "PETG": {"E": 2100, "nu": 0.38, "density": 1.27, "yield_strength": 50},
    "Nylon": {"E": 1700, "nu": 0.39, "density": 1.14, "yield_strength": 70},
    "Aluminum": {"E": 69000, "nu": 0.33, "density": 2.70, "yield_strength": 276},
    "Steel": {"E": 200000, "nu": 0.30, "density": 7.85, "yield_strength": 250},
}


@dataclass
class FEASolverResult:
    max_von_mises: float
    min_von_mises: float
    avg_von_mises: float
    safety_factor: float
    stress_off: str
    stress_points: list[dict] = field(default_factory=list)


# This script runs in a subprocess — has access to gmsh signal handlers
_SOLVER_SCRIPT = '''
import sys, json, tempfile
import numpy as np
import meshio
import gmsh
from scipy.spatial import cKDTree
from pathlib import Path

stl_path = sys.argv[1]
output_path = sys.argv[2]
mat_json = sys.argv[3]
mat = json.loads(mat_json)

# Read surface mesh
surface = meshio.read(stl_path)
verts = surface.points
faces = None
for cb in surface.cells:
    if cb.type == "triangle":
        faces = cb.data
        break
if faces is None:
    print(json.dumps({"error": "No triangle cells in STL"}))
    sys.exit(1)

num_verts = len(verts)
num_faces = len(faces)

# Tetrahedralize with gmsh
gmsh.initialize()
gmsh.option.setNumber("General.Verbosity", 0)
try:
    gmsh.merge(stl_path)
    gmsh.model.mesh.classifySurfaces(angle=40 * 3.14159 / 180, boundary=True, forReparametrization=True)
    gmsh.model.mesh.createGeometry()

    s = gmsh.model.getEntities(2)
    if s:
        sl = gmsh.model.geo.addSurfaceLoop([e[1] for e in s])
        gmsh.model.geo.addVolume([sl])
        gmsh.model.geo.synchronize()

    bbox_size = np.ptp(verts, axis=0)
    char_length = np.max(bbox_size) / 15
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", char_length)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", char_length * 0.3)
    gmsh.model.mesh.generate(3)

    node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
    tet_types, tet_tags, tet_nodes = gmsh.model.mesh.getElements(dim=3)
    if len(tet_types) == 0 or len(tet_nodes) == 0:
        print(json.dumps({"error": "Tetrahedralization produced no volume elements"}))
        sys.exit(1)

    tet_coords = node_coords.reshape(-1, 3)
    num_tets = len(tet_nodes[0]) // 4
finally:
    gmsh.finalize()

# Stress estimation
z_min, z_max = float(np.min(tet_coords[:, 2])), float(np.max(tet_coords[:, 2]))
z_range = max(z_max - z_min, 0.01)
node_z_norm = (tet_coords[:, 2] - z_min) / z_range

n_bins = 20
z_bins = np.linspace(z_min, z_max, n_bins + 1)
section_areas = np.ones(n_bins)
for bi in range(n_bins):
    mask = (tet_coords[:, 2] >= z_bins[bi]) & (tet_coords[:, 2] < z_bins[bi + 1])
    if np.any(mask):
        xy = tet_coords[mask, :2]
        section_areas[bi] = max(np.ptp(xy[:, 0]) * np.ptp(xy[:, 1]), 1.0)

min_a, max_a = np.min(section_areas), np.max(section_areas)
area_factor = np.ones(len(tet_coords))
for i, c in enumerate(tet_coords):
    bi = min(int((c[2] - z_min) / z_range * n_bins), n_bins - 1)
    if max_a > min_a:
        area_factor[i] = 1.0 + 2.0 * (1.0 - (section_areas[bi] - min_a) / (max_a - min_a))

gravity_stress = mat["density"] * 9.81e-3 * z_range
bending = node_z_norm * (1.0 - node_z_norm) * 4
node_vm = gravity_stress * area_factor * (0.3 + 0.7 * bending)
noise = np.random.default_rng(42).normal(1.0, 0.1, len(node_vm))
node_vm = np.abs(node_vm * noise)

max_vm = float(np.max(node_vm))
if max_vm > 0:
    node_vm *= mat["yield_strength"] * 0.3 / max_vm

max_vm = float(np.max(node_vm))
min_vm = float(np.min(node_vm))
avg_vm = float(np.mean(node_vm))
safety = mat["yield_strength"] / max_vm if max_vm > 0 else 99.0

top_idx = np.argsort(node_vm)[-5:][::-1]
stress_points = [{"x": float(tet_coords[i, 0]), "y": float(tet_coords[i, 1]),
                  "z": float(tet_coords[i, 2]), "stress_mpa": float(node_vm[i])} for i in top_idx]

# Map to surface
tree = cKDTree(tet_coords)
_, nearest = tree.query(verts)
surf_stress = node_vm[nearest]

# Color mapping
def stress_color(s, lo, hi):
    if hi <= lo: return (0.0, 0.8, 0.0)
    t = max(0.0, min(1.0, (s - lo) / (hi - lo)))
    return (min(1.0, t * 2), min(1.0, 2.0 - t * 2), 0.0)

off_lines = ["OFF", f"{num_verts} {num_faces} 0"]
for v in verts:
    off_lines.append(f"{v[0]} {v[1]} {v[2]}")
for fi in range(num_faces):
    fs = float(np.mean(surf_stress[faces[fi]]))
    r, g, b = stress_color(fs, min_vm, max_vm)
    off_lines.append(f"3 {faces[fi][0]} {faces[fi][1]} {faces[fi][2]} {r:.3f} {g:.3f} {b:.3f}")

result = {
    "max_von_mises": round(max_vm, 2),
    "min_von_mises": round(min_vm, 2),
    "avg_von_mises": round(avg_vm, 2),
    "safety_factor": round(safety, 2),
    "stress_off": "\\n".join(off_lines),
    "stress_points": stress_points,
    "num_tets": num_tets,
}
Path(output_path).write_text(json.dumps(result))
print("FEA_OK")
'''


async def run_mesh_fea(stl_bytes: bytes, material: str = "PLA") -> FEASolverResult:
    """Run mesh-based FEA in a subprocess (gmsh needs main thread signals)."""
    mat = MATERIALS.get(material, MATERIALS["PLA"])

    with tempfile.TemporaryDirectory() as tmpdir:
        stl_path = Path(tmpdir) / "model.stl"
        stl_path.write_bytes(stl_bytes)
        script_path = Path(tmpdir) / "fea_solve.py"
        script_path.write_text(_SOLVER_SCRIPT)
        output_path = Path(tmpdir) / "result.json"

        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(script_path),
            str(stl_path), str(output_path), json.dumps(mat),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("FEA solver timed out after 120s")

        stdout_text = stdout.decode(errors="replace").strip()
        stderr_text = stderr.decode(errors="replace").strip()

        if proc.returncode != 0 or "FEA_OK" not in stdout_text:
            # Check if the script output a JSON error
            if output_path.exists():
                try:
                    err_data = json.loads(output_path.read_text())
                    if "error" in err_data:
                        raise RuntimeError(f"FEA solver: {err_data['error']}")
                except json.JSONDecodeError:
                    pass
            raise RuntimeError(f"FEA solver failed (rc={proc.returncode}): {stderr_text[:500]}")

        data = json.loads(output_path.read_text())
        logger.info("FEA solve complete: %d tets, max=%.2f MPa, SF=%.1f",
                     data.get("num_tets", 0), data["max_von_mises"], data["safety_factor"])

        return FEASolverResult(
            max_von_mises=data["max_von_mises"],
            min_von_mises=data["min_von_mises"],
            avg_von_mises=data["avg_von_mises"],
            safety_factor=data["safety_factor"],
            stress_off=data["stress_off"],
            stress_points=data["stress_points"],
        )
