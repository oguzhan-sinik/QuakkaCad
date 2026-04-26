"""Compose a worm-gear assembly: worm shaft (X-axis) + worm wheel (Z-axis)."""

from ..atomic import get_module
from ..models import WormGearSpec


def compose(spec: WormGearSpec) -> str:
    worm_pitch_r  = spec.module_val * 4          # simplified worm pitch radius
    wheel_pitch_r = spec.module_val * spec.wheel_teeth / 2
    centre_dist   = worm_pitch_r + wheel_pitch_r  # separation along Y
    ratio         = spec.wheel_teeth / spec.worm_starts

    lines = [
        "// Worm Gear — auto-generated from template",
        "$fn = 32;",
        f"// Ratio: {ratio:.1f}:1  ({spec.worm_starts}-start worm, {spec.wheel_teeth} wheel teeth)",
        "",
        get_module("worm"),
        "",
        get_module("spur_gear"),
        "",
        "// Worm shaft (horizontal, along X)",
        f'color("SteelBlue")',
        (
            f"worm(starts={spec.worm_starts}, module_val={spec.module_val}, "
            f"length={spec.worm_length}, bore_d={spec.worm_bore_d});"
        ),
        "",
        "// Worm wheel (vertical, offset along Y by centre distance)",
        f'color("Gold")',
        f"translate([0, {centre_dist:.3f}, 0])",
        (
            f"  spur_gear(teeth={spec.wheel_teeth}, module_val={spec.module_val}, "
            f"thickness={spec.wheel_thickness}, bore={spec.bore_d});"
        ),
        "",
        "// Wheel axle",
        f'color("DimGray")',
        f"translate([0, {centre_dist:.3f}, 0])",
        f"  cylinder(d={spec.bore_d * 0.8:.2f}, h={spec.wheel_thickness * 2}, center=true, $fn=32);",
    ]
    return "\n".join(lines)
