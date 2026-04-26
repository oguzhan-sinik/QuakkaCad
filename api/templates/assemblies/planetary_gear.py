"""Compose a planetary gear set — sun + orbiting planets + ring gear."""

import math

from ..atomic import get_module
from ..models import PlanetaryGearSpec


def compose(spec: PlanetaryGearSpec) -> str:
    ring_teeth = spec.sun_teeth + 2 * spec.planet_teeth
    # Center distance sun-to-planet = (sun + planet) * module / 2
    orbit_r = (spec.sun_teeth + spec.planet_teeth) * spec.module_val / 2

    lines = [
        "// Planetary Gear Set — auto-generated from template",
        "$fn = 32;",
        "",
        get_module("spur_gear"),
    ]

    if spec.include_ring_gear:
        lines.append(get_module("ring_gear"))

    lines.append("")
    lines.append("// Assembly")
    lines.append("union() {")

    # Sun gear at center
    sun_pitch_r = spec.module_val * spec.sun_teeth / 2
    lines.append(
        f"    color(\"Gold\") "
        f"spur_gear(teeth={spec.sun_teeth}, module_val={spec.module_val}, "
        f"thickness={spec.thickness}, bore={spec.bore_d});"
    )

    # Planet gears orbiting the sun
    planet_tooth_angle = 360.0 / spec.planet_teeth
    for i in range(spec.planet_count):
        angle_deg = i * 360.0 / spec.planet_count
        angle_rad = math.radians(angle_deg)
        px = orbit_r * math.cos(angle_rad)
        py = orbit_r * math.sin(angle_rad)
        # Mesh offset: planet teeth must interleave with sun teeth
        rot = planet_tooth_angle / 2
        lines.append(
            f"    color(\"SteelBlue\") "
            f"translate([{px:.2f}, {py:.2f}, 0]) "
            f"rotate([0, 0, {rot:.3f}]) "
            f"spur_gear(teeth={spec.planet_teeth}, module_val={spec.module_val}, "
            f"thickness={spec.thickness}, bore={spec.bore_d * 0.6:.1f});"
        )

    # Ring gear (internal teeth)
    if spec.include_ring_gear:
        ring_wall = max(3, spec.module_val * 3)
        lines.append(
            f"    color(\"Tomato\", 0.4) "
            f"ring_gear(teeth={ring_teeth}, module_val={spec.module_val}, "
            f"thickness={spec.thickness}, wall={ring_wall:.1f});"
        )

    # Planet carrier plate (thin disc connecting planet axles)
    carrier_r = orbit_r + spec.module_val * spec.planet_teeth / 4
    lines.append(
        f"    color(\"DimGray\", 0.3) "
        f"translate([0, 0, {spec.thickness * 0.7:.1f}]) "
        f"difference() {{"
    )
    lines.append(
        f"        cylinder(r={carrier_r:.1f}, h={spec.thickness * 0.2:.1f}, center=true, $fn=64);"
    )
    lines.append(
        f"        cylinder(d={spec.bore_d}, h={spec.thickness + 1}, center=true, $fn=32);"
    )
    lines.append("    }")

    # Sun axle
    lines.append(
        f"    color(\"DarkGray\") "
        f"cylinder(d={spec.bore_d * 0.8:.1f}, h={spec.thickness * 2}, center=true, $fn=16);"
    )

    lines.append("}")
    return "\n".join(lines)
