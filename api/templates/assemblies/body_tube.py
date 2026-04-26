"""Compose a hobby-rocketry body tube with optional hole cutouts.

Supports standard Estes BT designations (BT-20, BT-50, BT-80 …) or
custom diameters.  Holes are cut through the tube wall at specified
positions (given as Z-height along the tube and angular position).
"""

import math

from ..models import BodyTubeSpec
from .hole_utils import render_hole_cuts


def compose(spec: BodyTubeSpec) -> str:
    inner_d = spec.outer_d - 2 * spec.wall
    designation = spec.bt_designation or f"Ø{spec.outer_d}"
    has_holes = len(spec.holes) > 0

    lines = [
        "// Body Tube — auto-generated from template",
        "$fn = 64;",
        f"// {designation}  OD={spec.outer_d} mm  ID={inner_d:.1f} mm  "
        f"Wall={spec.wall} mm  Length={spec.length} mm",
        "",
    ]

    lines.append(f'color("{spec.color}")')

    if has_holes:
        lines.append("difference() {")
        indent = "    "
    else:
        indent = ""

    # Tube (hollow cylinder, base at z=0, top at z=length)
    lines.append(f"{indent}difference() {{")
    lines.append(
        f"{indent}    cylinder(d={spec.outer_d}, h={spec.length}, $fn=64);"
    )
    lines.append(
        f"{indent}    translate([0, 0, -0.5])"
    )
    lines.append(
        f"{indent}        cylinder(d={inner_d:.2f}, h={spec.length + 1}, $fn=64);"
    )
    lines.append(f"{indent}}}")

    # Holes cut through the wall
    # For tube holes, we project them onto the tube surface.  Each hole's
    # (x, y) in the HolePattern is interpreted as:
    #   x → angular position in degrees around the tube
    #   y → Z height along the tube (mm from bottom)
    # Circular holes become cylinders punched radially inward.
    # Rect slots become cubes punched radially.
    if has_holes:
        lines.append("")
        lines.append("    // --- Wall cutouts ---")
        radial_depth = spec.wall + 2  # punch cleanly through

        for h in spec.holes:
            angle = h.x  # degrees around tube
            z_pos = h.y  # mm from bottom

            if h.hole_type == "circular":
                lines.append(f"    // Circular hole Ø{h.diameter} @ {angle}°, Z={z_pos}")
                lines.append(f"    rotate([0, 0, {angle}])")
                lines.append(f"    translate([{spec.outer_d / 2:.2f}, 0, {z_pos}])")
                lines.append(f"    rotate([0, 90, 0])")
                lines.append(
                    f"    cylinder(d={h.diameter}, h={radial_depth}, center=true, $fn=32);"
                )

            elif h.hole_type == "bolt_circle":
                lines.append(f"    // Bolt circle ({h.bolt_count}× Ø{h.bolt_hole_d}) @ Z={z_pos}")
                bc_r = h.bolt_circle_d / 2
                for i in range(h.bolt_count):
                    ba = h.start_angle + i * 360 / h.bolt_count
                    bz = z_pos + bc_r * math.sin(math.radians(ba))
                    b_ang = angle + (bc_r * math.cos(math.radians(ba)) / (math.pi * spec.outer_d) * 360)
                    lines.append(f"    rotate([0, 0, {b_ang:.2f}])")
                    lines.append(f"    translate([{spec.outer_d / 2:.2f}, 0, {bz:.2f}])")
                    lines.append(f"    rotate([0, 90, 0])")
                    lines.append(
                        f"    cylinder(d={h.bolt_hole_d}, h={radial_depth}, center=true, $fn=24);"
                    )

            elif h.hole_type == "rect_slot":
                lines.append(f"    // Rect slot {h.width}×{h.height} @ {angle}°, Z={z_pos}")
                lines.append(f"    rotate([0, 0, {angle}])")
                lines.append(f"    translate([{spec.outer_d / 2:.2f}, 0, {z_pos}])")
                lines.append(f"    rotate([0, 90, 0])")
                if h.corner_r > 0:
                    cr = min(h.corner_r, h.width / 2, h.height / 2)
                    hw = h.width / 2 - cr
                    hh = h.height / 2 - cr
                    lines.append(f"    hull() {{")
                    for sx, sy in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
                        lines.append(
                            f"        translate([{sx * hh:.3f}, {sy * hw:.3f}, 0]) "
                            f"cylinder(r={cr}, h={radial_depth}, center=true, $fn=16);"
                        )
                    lines.append(f"    }}")
                else:
                    lines.append(
                        f"    cube([{h.height}, {h.width}, {radial_depth}], center=true);"
                    )

        lines.append("}")

    return "\n".join(lines)
