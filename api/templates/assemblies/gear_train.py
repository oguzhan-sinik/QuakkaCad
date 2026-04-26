"""Compose a gear train from spur gears with computed center distances."""

from ..atomic import get_module
from ..models import GearTrainSpec


def compose(spec: GearTrainSpec) -> str:
    lines = [
        f"// Gear Train — auto-generated from template",
        f"$fn = 32;",
        "",
        get_module("spur_gear"),
        "",
        "// Assembly",
        "union() {",
    ]

    # Position gears along X axis with correct center distances
    colors = ["SteelBlue", "Tomato", "Gold", "MediumSeaGreen"]
    x = 0.0
    for i in range(spec.gear_count):
        pitch_r = spec.module_val * spec.teeth[i] / 2
        color = colors[i % len(colors)]
        # Alternate rotation so teeth mesh (offset by half tooth)
        rot_offset = (180 / spec.teeth[i]) if i % 2 == 1 else 0
        lines.append(
            f"    color(\"{color}\") translate([{x}, 0, 0]) rotate([0, 0, {rot_offset}]) "
            f"spur_gear(teeth={spec.teeth[i]}, module_val={spec.module_val}, "
            f"thickness={spec.thickness}, bore={spec.bore_d});"
        )
        # Center distance to next gear
        if i < spec.gear_count - 1:
            next_pitch_r = spec.module_val * spec.teeth[i + 1] / 2
            x += pitch_r + next_pitch_r

    lines.append("}")
    return "\n".join(lines)
