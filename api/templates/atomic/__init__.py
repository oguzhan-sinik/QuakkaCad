"""Load and cache atomic OpenSCAD template module text."""

from pathlib import Path

_DIR = Path(__file__).parent
_CACHE: dict[str, str] = {}


def get_module(name: str) -> str:
    """Return the .scad source for an atomic module (cached)."""
    if name not in _CACHE:
        path = _DIR / f"{name}.scad"
        if not path.exists():
            raise FileNotFoundError(f"Atomic template not found: {path}")
        _CACHE[name] = path.read_text()
    return _CACHE[name]
