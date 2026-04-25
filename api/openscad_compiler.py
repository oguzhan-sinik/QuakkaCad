from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


async def compile_openscad(script: str, timeout: float = 30.0) -> tuple[bool, str]:
    """Compile an OpenSCAD script headlessly and return (success, stderr).

    Writes the script to a temp file, runs `openscad --export-format off -o /dev/null`,
    and parses the result. Success requires exit code 0 and no ERROR: lines in stderr.

    Raises FileNotFoundError if the openscad binary is not on PATH.
    """
    with tempfile.NamedTemporaryFile(suffix=".scad", mode="w", delete=False) as f:
        f.write(script)
        tmp_path = Path(f.name)

    try:
        proc = await asyncio.create_subprocess_exec(
            "openscad",
            "--export-format", "off",
            "-o", "/dev/null",
            str(tmp_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return False, f"ERROR: OpenSCAD compilation timed out after {timeout:.0f}s"

        stderr = stderr_bytes.decode(errors="replace").strip()
        has_error = proc.returncode != 0 or any(
            line.startswith("ERROR:") for line in stderr.splitlines()
        )
        return not has_error, stderr

    except FileNotFoundError:
        raise FileNotFoundError(
            "openscad binary not found on PATH. Install it with: sudo apt install openscad"
        )
    finally:
        tmp_path.unlink(missing_ok=True)
