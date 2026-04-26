"""Compose a bushing assembly — concentric tube with optional flange."""

from ..atomic import get_module
from ..models import BushingAssemblySpec


def compose(spec: BushingAssemblySpec) -> str:
    lines = [
        f"// Bushing Assembly — auto-generated from template",
        f"$fn = 32;",
        "",
        get_module("tube"),
    ]

    if spec.flange:
        lines.append(get_module("flange"))

    lines.append("")
    lines.append("// Assembly")
    lines.append("union() {")
    lines.append(
        f"    color(\"SteelBlue\") tube(od={spec.outer_d}, id={spec.bore_d}, length={spec.length});"
    )

    if spec.flange and spec.flange_outer_d and spec.flange_thickness:
        # Flange at one end
        bolt_circle_d = (spec.flange_outer_d + spec.outer_d) / 2
        bolt_hole_d = min(4, (spec.flange_outer_d - spec.outer_d) / 6)
        bolt_count = max(4, int(bolt_circle_d * 3.14159 / 15))  # ~1 bolt per 15mm arc
        lines.append(
            f"    color(\"Gold\") translate([0, 0, {-spec.length / 2 - spec.flange_thickness / 2}]) "
            f"flange(od={spec.flange_outer_d}, id={spec.bore_d}, thickness={spec.flange_thickness}, "
            f"bolt_count={bolt_count}, bolt_circle_d={bolt_circle_d}, bolt_hole_d={bolt_hole_d});"
        )

    lines.append("}")
    return "\n".join(lines)
