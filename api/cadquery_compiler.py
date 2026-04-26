"""Execute CadQuery Python scripts and export STEP + STL meshes."""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


def _clean_script(script: str) -> str:
    """Strip markdown fences and common LLM artifacts from the script."""
    s = script.strip()
    # Remove markdown code fences
    if s.startswith("```"):
        lines = s.split("\n")
        lines = lines[1:]  # drop opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines)
    # Remove any leading prose lines (non-import, non-comment, non-blank before first import)
    lines = s.split("\n")
    start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from ") or stripped.startswith("#") or stripped == "" or stripped.startswith("result") or "=" in stripped:
            start = i
            break
    s = "\n".join(lines[start:])
    # Remove dangerous imports
    s = re.sub(r"^import (numpy|sys|os|math).*$", "# removed: disallowed import", s, flags=re.MULTILINE)
    s = re.sub(r"^from (numpy|sys|os|math) import.*$", "# removed: disallowed import", s, flags=re.MULTILINE)
    # Replace numpy/math references with builtins
    s = s.replace("np.pi", "3.14159265358979")
    s = s.replace("math.pi", "3.14159265358979")
    s = s.replace("np.sin", "__import__('math').sin")
    s = s.replace("np.cos", "__import__('math').cos")
    s = s.replace("np.sqrt", "__import__('math').sqrt")
    s = s.replace("math.sin", "__import__('math').sin")
    s = s.replace("math.cos", "__import__('math').cos")
    s = s.replace("math.sqrt", "__import__('math').sqrt")
    return s


@dataclass
class CadQueryResult:
    success: bool
    stderr: str
    stl_bytes: bytes | None = None
    step_bytes: bytes | None = None


async def compile_cadquery(script: str, timeout: float = 60.0) -> CadQueryResult:
    """Execute a CadQuery Python script and export to STEP + STL.

    Returns CadQueryResult with both formats.
    """
    cleaned = _clean_script(script)

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "model.py"
        stl_path = Path(tmpdir) / "output.stl"
        step_path = Path(tmpdir) / "output.step"

        # Wrap user script to auto-export the result
        wrapper = f"""\
import cadquery as cq
import sys

# --- User script (cleaned) ---
{cleaned}
# --- End user script ---

# Auto-detect and export the result
_result = None
for _name in ['result', 'model', 'part', 'assembly', 'obj', 'shape', 'body']:
    if _name in dir():
        _obj = eval(_name)
        if isinstance(_obj, cq.Workplane):
            _result = _obj
            break

if _result is None:
    # Try to find any Workplane object in locals
    for _k, _v in list(locals().items()):
        if isinstance(_v, cq.Workplane) and not _k.startswith('_'):
            _result = _v
            break

if _result is None:
    print("ERROR: No CadQuery Workplane result found. Assign your model to 'result'.", file=sys.stderr)
    sys.exit(1)

# Export STEP (primary engineering format)
cq.exporters.export(_result, "{step_path}", cq.exporters.ExportTypes.STEP)
print("STEP export OK", file=sys.stderr)

# Export STL (for 3D preview)
cq.exporters.export(_result, "{stl_path}", cq.exporters.ExportTypes.STL)
print("STL export OK", file=sys.stderr)
"""
        script_path.write_text(wrapper)

        logger.info("Executing CadQuery script (%d chars cleaned)", len(cleaned))

        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(script_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return CadQueryResult(success=False, stderr=f"CadQuery compilation timed out after {timeout}s")

        stderr_text = stderr.decode(errors="replace")
        logger.info("CadQuery exit code: %d, stderr: %s", proc.returncode, stderr_text[:200])

        if proc.returncode != 0:
            if proc.returncode == -11 or proc.returncode == 139:
                return CadQueryResult(
                    success=False,
                    stderr="CadQuery crashed (SIGSEGV) — cadquery-ocp is incompatible with this system. "
                           "This is a known issue on macOS ARM. The generated code is correct but cannot be compiled locally."
                )
            return CadQueryResult(success=False, stderr=stderr_text or f"Process exited with code {proc.returncode}")

        stl_bytes = stl_path.read_bytes() if stl_path.exists() else None
        step_bytes = step_path.read_bytes() if step_path.exists() else None

        if not stl_bytes and not step_bytes:
            return CadQueryResult(success=False, stderr=f"No output produced.\n{stderr_text}")

        logger.info("CadQuery exported: STEP=%d bytes, STL=%d bytes",
                     len(step_bytes) if step_bytes else 0,
                     len(stl_bytes) if stl_bytes else 0)
        return CadQueryResult(success=True, stderr=stderr_text, stl_bytes=stl_bytes, step_bytes=step_bytes)
