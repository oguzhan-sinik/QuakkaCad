"""Compose a gear train from spur gears with correct center distances and meshing."""

from ..atomic import get_module
from ..models import GearTrainSpec


def compose(spec: GearTrainSpec) -> str:
    lines = [
        f"// Gear Train — auto-generated from template",
        f"$fn = 32;",
        "",
        get_module("spur_gear"),
        "",
        "// Assembly — gears along X axis with meshing offsets",
    ]

    colors = ["SteelBlue", "Tomato", "Gold", "MediumSeaGreen", "Orchid", "DarkCyan"]
    x_positions: list[float] = [0.0]

    # Compute X positions based on pitch circle distances
    for i in range(1, spec.gear_count):
        prev_pitch_r = spec.module_val * spec.teeth[i - 1] / 2
        curr_pitch_r = spec.module_val * spec.teeth[i] / 2
        x_positions.append(x_positions[-1] + prev_pitch_r + curr_pitch_r)

    lines.append("union() {")
    for i in range(spec.gear_count):
        color = colors[i % len(colors)]
        x = x_positions[i]
        tooth_angle = 360.0 / spec.teeth[i]

        # For meshing: adjacent gears must have teeth interleaved
        # Odd-indexed gears rotate by half a tooth pitch so teeth fit into gaps
        if i % 2 == 1:
            rot = tooth_angle / 2
        else:
            rot = 0

        lines.append(
            f"    color(\"{color}\") "
            f"translate([{x:.2f}, 0, 0]) "
            f"rotate([0, 0, {rot:.3f}]) "
            f"spur_gear(teeth={spec.teeth[i]}, module_val={spec.module_val}, "
            f"thickness={spec.thickness}, bore={spec.bore_d});"
        )

    # Add axle indicators (thin cylinders through bores)
    for i in range(spec.gear_count):
        x = x_positions[i]
        lines.append(
            f"    color(\"DimGray\") translate([{x:.2f}, 0, 0]) "
            f"cylinder(d={spec.bore_d * 0.8}, h={spec.thickness * 2}, center=true, $fn=16);"
        )

    lines.append("}")
    return "\n".join(lines)
