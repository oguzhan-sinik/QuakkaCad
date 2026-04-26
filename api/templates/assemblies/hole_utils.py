"""Shared OpenSCAD code generators for HolePattern cutouts.

Used by bulkhead, body_tube, and mounting_plate composers to render
CircularHoleSpec, BoltCircleSpec, and RectSlotSpec into OpenSCAD
difference() children.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import HolePattern


def render_hole_cuts(holes: list[HolePattern], through_thickness: float) -> list[str]:
    """Return OpenSCAD lines that subtract holes from the parent solid.

    Each line is indented with 8 spaces (suitable for inside a
    ``difference() { ... }`` block).  ``through_thickness`` is the
    material depth + 1 mm clearance so holes cut cleanly.
    """
    cut_h = through_thickness + 1
    lines: list[str] = []

    for h in holes:
        if h.hole_type == "circular":
            lines.append(
                f"        translate([{h.x}, {h.y}, 0]) "
                f"cylinder(d={h.diameter}, h={cut_h}, center=true, $fn=32);"
            )
            if h.countersink:
                cs_d = h.diameter * 2
                lines.append(
                    f"        translate([{h.x}, {h.y}, {through_thickness / 2 - h.diameter * 0.3:.2f}]) "
                    f"cylinder(d1={h.diameter}, d2={cs_d}, h={h.diameter * 0.6:.2f}, $fn=32);"
                )

        elif h.hole_type == "bolt_circle":
            r = h.bolt_circle_d / 2
            for i in range(h.bolt_count):
                angle = math.radians(h.start_angle + i * 360 / h.bolt_count)
                bx = r * math.cos(angle)
                by = r * math.sin(angle)
                lines.append(
                    f"        translate([{bx:.3f}, {by:.3f}, 0]) "
                    f"cylinder(d={h.bolt_hole_d}, h={cut_h}, center=true, $fn=24);"
                )
                if h.countersink:
                    cs_d = h.bolt_hole_d * 2
                    lines.append(
                        f"        translate([{bx:.3f}, {by:.3f}, {through_thickness / 2 - h.bolt_hole_d * 0.3:.2f}]) "
                        f"cylinder(d1={h.bolt_hole_d}, d2={cs_d}, h={h.bolt_hole_d * 0.6:.2f}, $fn=24);"
                    )

        elif h.hole_type == "rect_slot":
            if h.corner_r > 0:
                # Rounded rectangle via hull of four cylinders
                cr = min(h.corner_r, h.width / 2, h.height / 2)
                hw = h.width / 2 - cr
                hh = h.height / 2 - cr
                lines.append(f"        translate([{h.x}, {h.y}, 0])")
                lines.append(f"        hull() {{")
                for sx, sy in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
                    lines.append(
                        f"            translate([{sx * hw:.3f}, {sy * hh:.3f}, 0]) "
                        f"cylinder(r={cr}, h={cut_h}, center=true, $fn=24);"
                    )
                lines.append(f"        }}")
            else:
                lines.append(
                    f"        translate([{h.x}, {h.y}, 0]) "
                    f"cube([{h.width}, {h.height}, {cut_h}], center=true);"
                )

    return lines
