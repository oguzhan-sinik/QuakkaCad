"""Compose a four-bar linkage — ground, crank, coupler, rocker with pivot pins."""

import math

from ..atomic import get_module
from ..models import FourBarLinkageSpec


def compose(spec: FourBarLinkageSpec) -> str:
    # Solve linkage position for the given crank angle.
    # Ground link from origin to (ground_length, 0).
    # Crank pivots at origin; rocker pivots at (ground_length, 0).
    angle_rad = math.radians(spec.crank_angle)
    cx = spec.crank_length * math.cos(angle_rad)
    cy = spec.crank_length * math.sin(angle_rad)

    # Find rocker angle via circle-circle intersection:
    # Coupler end is at (cx, cy); rocker pivots at (ground_length, 0).
    dx = spec.ground_length - cx
    dy = -cy
    dist = math.sqrt(dx * dx + dy * dy)

    # Clamp to avoid numerical issues at extreme positions
    cos_val = (dist * dist + spec.rocker_length ** 2 - spec.coupler_length ** 2) / (
        2 * dist * spec.rocker_length
    )
    cos_val = max(-1.0, min(1.0, cos_val))
    rocker_local = math.acos(cos_val)
    base_angle = math.atan2(dy, dx)
    rocker_angle = base_angle - rocker_local  # take one solution

    rx = spec.ground_length + spec.rocker_length * math.cos(rocker_angle)
    ry = spec.rocker_length * math.sin(rocker_angle)

    # Angles for each bar (for rotation in OpenSCAD)
    crank_deg = spec.crank_angle
    coupler_dx = rx - cx
    coupler_dy = ry - cy
    coupler_deg = math.degrees(math.atan2(coupler_dy, coupler_dx))
    rocker_deg = math.degrees(math.atan2(ry, rx - spec.ground_length))

    pin_h = spec.link_thickness * 1.5

    lines = [
        "// Four-Bar Linkage — auto-generated from template",
        "$fn = 32;",
        f"// Ground={spec.ground_length}  Crank={spec.crank_length}  "
        f"Coupler={spec.coupler_length}  Rocker={spec.rocker_length} mm",
        f"// Crank angle: {spec.crank_angle}°",
        "",
        get_module("linkage_bar"),
        "",
        "// Ground link (fixed frame)",
        f'color("{spec.ground_color}")',
        f"translate([{spec.ground_length / 2:.3f}, 0, 0])",
        f"  linkage_bar(length={spec.ground_length}, width={spec.link_width}, "
        f"thickness={spec.link_thickness}, pivot_d={spec.pivot_d});",
        "",
        "// Crank (input link)",
        f'color("{spec.crank_color}")',
        f"translate([{cx / 2:.3f}, {cy / 2:.3f}, {spec.link_thickness:.1f}])",
        f"  rotate([0, 0, {crank_deg:.3f}])",
        f"  linkage_bar(length={spec.crank_length}, width={spec.link_width}, "
        f"thickness={spec.link_thickness}, pivot_d={spec.pivot_d});",
        "",
        "// Coupler (connecting link)",
        f'color("{spec.coupler_color}")',
        f"translate([{(cx + rx) / 2:.3f}, {(cy + ry) / 2:.3f}, {spec.link_thickness * 2:.1f}])",
        f"  rotate([0, 0, {coupler_deg:.3f}])",
        f"  linkage_bar(length={spec.coupler_length}, width={spec.link_width}, "
        f"thickness={spec.link_thickness}, pivot_d={spec.pivot_d});",
        "",
        "// Rocker (output link)",
        f'color("{spec.rocker_color}")',
        f"translate([{(spec.ground_length + rx) / 2:.3f}, {ry / 2:.3f}, {spec.link_thickness * 3:.1f}])",
        f"  rotate([0, 0, {rocker_deg:.3f}])",
        f"  linkage_bar(length={spec.rocker_length}, width={spec.link_width}, "
        f"thickness={spec.link_thickness}, pivot_d={spec.pivot_d});",
        "",
        "// Pivot pins",
        f'color("Silver")',
        "union() {",
        f"  cylinder(d={spec.pivot_d * 0.9:.2f}, h={pin_h:.1f}, center=true, $fn=24);",
        f"  translate([{spec.ground_length:.3f}, 0, 0])",
        f"    cylinder(d={spec.pivot_d * 0.9:.2f}, h={pin_h:.1f}, center=true, $fn=24);",
        f"  translate([{cx:.3f}, {cy:.3f}, 0])",
        f"    cylinder(d={spec.pivot_d * 0.9:.2f}, h={pin_h:.1f}, center=true, $fn=24);",
        f"  translate([{rx:.3f}, {ry:.3f}, 0])",
        f"    cylinder(d={spec.pivot_d * 0.9:.2f}, h={pin_h:.1f}, center=true, $fn=24);",
        "}",
    ]
    return "\n".join(lines)
