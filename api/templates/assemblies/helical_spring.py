"""Compose a helical spring (compression, extension, or torsion)."""

from ..atomic import get_module
from ..models import HelicalSpringSpec

_COLORS = {
    "compression": "SteelBlue",
    "extension":   "Tomato",
    "torsion":     "Gold",
}


def compose(spec: HelicalSpringSpec) -> str:
    coil_id  = spec.coil_od - 2 * spec.wire_d
    pitch    = spec.free_length / spec.coil_count
    color    = _COLORS[spec.spring_type]

    lines = [
        f"// Helical Spring ({spec.spring_type}) — auto-generated from template",
        "$fn = 32;",
        f"// Wire Ø{spec.wire_d} mm  |  Coil OD {spec.coil_od} mm  |  ID {coil_id:.2f} mm",
        f"// Free length {spec.free_length} mm  |  {spec.coil_count} coils  |  pitch {pitch:.2f} mm/coil",
        "",
        get_module("spring"),
        "",
        f'color("{color}")',
        (
            f"helical_spring(wire_d={spec.wire_d}, coil_od={spec.coil_od}, "
            f"free_length={spec.free_length}, coil_count={spec.coil_count});"
        ),
    ]
    return "\n".join(lines)
