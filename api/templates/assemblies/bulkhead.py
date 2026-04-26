"""Compose a bulkhead — flat disc that seals a rocket body tube.

Supports centre bore, shoulder lip, and arbitrary hole patterns
(bolt circles, screw holes, rectangular cable slots).
"""

from ..models import BulkheadSpec
from .hole_utils import render_hole_cuts


def compose(spec: BulkheadSpec) -> str:
    has_cuts = (
        spec.center_bore_d > 0
        or len(spec.holes) > 0
    )

    lines = [
        "// Bulkhead — auto-generated from template",
        "$fn = 64;",
        f"// OD: {spec.outer_d} mm  |  Thickness: {spec.thickness} mm",
    ]
    if spec.center_bore_d > 0:
        lines.append(f"// Centre bore: {spec.center_bore_d} mm")
    if spec.shoulder_d > 0:
        lines.append(f"// Shoulder: Ø{spec.shoulder_d} × {spec.shoulder_length} mm")
    lines.append("")

    # Main body
    lines.append(f'color("{spec.color}")')
    if has_cuts:
        lines.append("difference() {")
        indent = "    "
    else:
        indent = ""

    # Disc + optional shoulder as a union
    need_union = spec.shoulder_d > 0 and spec.shoulder_length > 0
    if need_union:
        lines.append(f"{indent}union() {{")
        inner = indent + "    "
    else:
        inner = indent

    # Main disc
    lines.append(
        f"{inner}cylinder(d={spec.outer_d}, h={spec.thickness}, center=true, $fn=64);"
    )

    # Shoulder (smaller cylinder protruding downward)
    if need_union:
        lines.append(
            f"{inner}translate([0, 0, {-(spec.thickness / 2 + spec.shoulder_length / 2):.3f}])"
        )
        lines.append(
            f"{inner}  cylinder(d={spec.shoulder_d}, h={spec.shoulder_length}, center=true, $fn=64);"
        )
        lines.append(f"{indent}}}")

    # Cuts
    if has_cuts:
        lines.append("")
        lines.append("    // --- Holes & cutouts ---")

        if spec.center_bore_d > 0:
            cut_h = spec.thickness + spec.shoulder_length + 2
            lines.append(
                f"    cylinder(d={spec.center_bore_d}, h={cut_h}, center=true, $fn=48);"
            )

        hole_lines = render_hole_cuts(spec.holes, spec.thickness)
        lines.extend(hole_lines)
        lines.append("}")

    return "\n".join(lines)
