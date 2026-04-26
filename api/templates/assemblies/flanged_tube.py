"""Compose a flanged tube — tube with bolt-pattern flange(s)."""

from ..atomic import get_module
from ..models import FlangedTubeSpec


def compose(spec: FlangedTubeSpec) -> str:
    lines = [
        f"// Flanged Tube — auto-generated from template",
        f"$fn = 32;",
        "",
        get_module("tube"),
        get_module("flange"),
        "",
        "// Assembly",
        "union() {",
        f"    color(\"SteelBlue\") tube(od={spec.tube_outer_d}, id={spec.tube_inner_d}, length={spec.tube_length});",
    ]

    # Flange at bottom (negative Z end)
    flange_z = spec.tube_length / 2 + spec.flange_thickness / 2
    lines.append(
        f"    color(\"Gold\") translate([0, 0, {-flange_z}]) "
        f"flange(od={spec.flange_outer_d}, id={spec.tube_inner_d}, thickness={spec.flange_thickness}, "
        f"bolt_count={spec.bolt_count}, bolt_circle_d={spec.bolt_circle_d}, bolt_hole_d={spec.bolt_hole_d});"
    )

    if spec.flange_both_ends:
        lines.append(
            f"    color(\"Gold\") translate([0, 0, {flange_z}]) "
            f"flange(od={spec.flange_outer_d}, id={spec.tube_inner_d}, thickness={spec.flange_thickness}, "
            f"bolt_count={spec.bolt_count}, bolt_circle_d={spec.bolt_circle_d}, bolt_hole_d={spec.bolt_hole_d});"
        )

    lines.append("}")
    return "\n".join(lines)
