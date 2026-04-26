"""Compose a differential gear assembly — ring gear, drive pinion, spider gears, side gears, case."""

import math

from ..atomic import get_module
from ..models import DifferentialGearSpec


def compose(spec: DifferentialGearSpec) -> str:
    ring_pitch_r = spec.module_val * spec.ring_gear_teeth / 2
    pinion_pitch_r = spec.module_val * spec.pinion_teeth / 2
    side_pitch_r = spec.module_val * spec.side_gear_teeth / 2
    spider_pitch_r = spec.module_val * spec.spider_gear_teeth / 2
    # Drive pinion meshes at the ring gear — offset along Y
    pinion_offset = ring_pitch_r + pinion_pitch_r
    ratio = spec.ring_gear_teeth / spec.pinion_teeth

    lines = [
        "// Differential Gear — auto-generated from template",
        "$fn = 32;",
        f"// Ring:Pinion = {spec.ring_gear_teeth}:{spec.pinion_teeth} = {ratio:.1f}:1",
        "",
        get_module("spur_gear"),
        get_module("bevel_gear"),
        "",
        "// Assembly",
        "union() {",
        "",
    ]

    # Ring (crown) gear — lies in XY plane
    lines.extend([
        "    // Ring gear (crown gear)",
        f'    color("Gold")',
        (
            f"    spur_gear(teeth={spec.ring_gear_teeth}, module_val={spec.module_val}, "
            f"thickness={spec.thickness}, bore={spec.case_od * 0.5:.1f});"
        ),
        "",
    ])

    # Drive pinion — meshes with ring gear, shaft along Y
    pinion_rot_offset = 360 / spec.pinion_teeth / 2
    lines.extend([
        "    // Drive pinion",
        f'    color("Tomato")',
        f"    translate([0, {pinion_offset:.3f}, 0])",
        f"    rotate([90, {pinion_rot_offset:.3f}, 0])",
        (
            f"    spur_gear(teeth={spec.pinion_teeth}, module_val={spec.module_val}, "
            f"thickness={spec.thickness}, bore={spec.bore_d});"
        ),
        "",
        "    // Pinion shaft",
        f'    color("DimGray")',
        f"    translate([0, {pinion_offset + spec.thickness:.1f}, 0])",
        f"    rotate([90, 0, 0])",
        f"    cylinder(d={spec.bore_d * 0.8:.1f}, h={spec.thickness * 3}, center=true, $fn=16);",
        "",
    ])

    # Side gears — on the left/right axle shafts, inside the case
    side_offset = spider_pitch_r + side_pitch_r
    lines.extend([
        "    // Left side gear",
        f'    color("SteelBlue")',
        f"    translate([{-side_offset * 0.6:.3f}, 0, 0])",
        f"    rotate([0, 90, 0])",
        (
            f"    bevel_gear(teeth={spec.side_gear_teeth}, module_val={spec.module_val}, "
            f"thickness={spec.thickness * 0.8:.1f}, bore={spec.bore_d});"
        ),
        "",
        "    // Right side gear",
        f'    color("SteelBlue")',
        f"    translate([{side_offset * 0.6:.3f}, 0, 0])",
        f"    rotate([0, -90, 0])",
        (
            f"    bevel_gear(teeth={spec.side_gear_teeth}, module_val={spec.module_val}, "
            f"thickness={spec.thickness * 0.8:.1f}, bore={spec.bore_d});"
        ),
        "",
    ])

    # Spider (planet) gears — orbit between the side gears
    for i in range(spec.spider_count):
        angle_deg = i * 360.0 / spec.spider_count
        angle_rad = math.radians(angle_deg)
        sy = (side_pitch_r + spider_pitch_r) * 0.4 * math.cos(angle_rad)
        sz = (side_pitch_r + spider_pitch_r) * 0.4 * math.sin(angle_rad)
        lines.extend([
            f"    // Spider gear {i + 1}",
            f'    color("MediumSeaGreen")',
            f"    translate([0, {sy:.3f}, {sz:.3f}])",
            f"    rotate([{angle_deg:.1f}, 0, 0])",
            (
                f"    bevel_gear(teeth={spec.spider_gear_teeth}, module_val={spec.module_val}, "
                f"thickness={spec.thickness * 0.6:.1f}, bore={spec.module_val * 2:.1f});"
            ),
            "",
        ])

    # Output axle shafts
    axle_ext = spec.case_od * 0.6
    lines.extend([
        "    // Left axle shaft",
        f'    color("DarkGray")',
        f"    translate([{-axle_ext:.1f}, 0, 0])",
        f"    rotate([0, 90, 0])",
        f"    cylinder(d={spec.bore_d * 0.8:.1f}, h={axle_ext * 1.5:.1f}, center=true, $fn=16);",
        "",
        "    // Right axle shaft",
        f'    color("DarkGray")',
        f"    translate([{axle_ext:.1f}, 0, 0])",
        f"    rotate([0, 90, 0])",
        f"    cylinder(d={spec.bore_d * 0.8:.1f}, h={axle_ext * 1.5:.1f}, center=true, $fn=16);",
        "",
    ])

    # Differential case (housing)
    if spec.include_case:
        case_r = spec.case_od / 2
        lines.extend([
            "    // Differential case",
            f'    color("DimGray", 0.25)',
            "    difference() {",
            f"        sphere(r={case_r:.1f}, $fn=48);",
            f"        sphere(r={case_r * 0.9:.1f}, $fn=48);",
            f"        // Axle holes",
            f"        rotate([0, 90, 0])",
            f"        cylinder(d={spec.bore_d * 1.5:.1f}, h={spec.case_od + 10}, center=true, $fn=24);",
            f"        // Pinion shaft hole",
            f"        rotate([90, 0, 0])",
            f"        cylinder(d={spec.bore_d * 1.5:.1f}, h={spec.case_od + 10}, center=true, $fn=24);",
            "    }",
            "",
        ])

    lines.append("}")
    return "\n".join(lines)
