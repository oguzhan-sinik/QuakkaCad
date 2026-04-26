"""Compose a mounting plate / table — flat rectangle with arbitrary holes and slots.

Great for avionics sleds, electronics trays, cable-management tables, brackets.
"""

from ..models import MountingPlateSpec
from .hole_utils import render_hole_cuts


def compose(spec: MountingPlateSpec) -> str:
    has_holes = len(spec.holes) > 0

    lines = [
        "// Mounting Plate — auto-generated from template",
        "$fn = 32;",
        f"// {spec.width} × {spec.depth} × {spec.thickness} mm",
    ]
    if spec.corner_r > 0:
        lines.append(f"// Corner radius: {spec.corner_r} mm")
    if has_holes:
        lines.append(f"// {len(spec.holes)} hole/slot cutout(s)")
    lines.append("")

    lines.append(f'color("{spec.color}")')

    if has_holes:
        lines.append("difference() {")
        indent = "    "
    else:
        indent = ""

    # Plate body
    if spec.corner_r > 0:
        # Rounded rectangle via hull of four cylinders
        cr = spec.corner_r
        hw = spec.width / 2 - cr
        hd = spec.depth / 2 - cr
        lines.append(f"{indent}hull() {{")
        for sx, sy in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
            lines.append(
                f"{indent}    translate([{sx * hw:.3f}, {sy * hd:.3f}, 0]) "
                f"cylinder(r={cr}, h={spec.thickness}, center=true, $fn=32);"
            )
        lines.append(f"{indent}}}")
    else:
        lines.append(
            f"{indent}cube([{spec.width}, {spec.depth}, {spec.thickness}], center=true);"
        )

    # Holes and slots
    if has_holes:
        lines.append("")
        lines.append("    // --- Holes & cutouts ---")
        hole_lines = render_hole_cuts(spec.holes, spec.thickness)
        lines.extend(hole_lines)
        lines.append("}")

    return "\n".join(lines)
