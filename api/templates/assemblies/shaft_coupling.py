"""Compose a rigid shaft coupling with two half-bodies and axle indicators."""

from ..atomic import get_module
from ..models import ShaftCouplingSpec


def compose(spec: ShaftCouplingSpec) -> str:
    half_len   = (spec.coupling_length - spec.gap) / 2
    z_bottom   = -(spec.gap / 2 + half_len / 2)   # centre of lower half
    z_top      = spec.gap / 2 + half_len / 2        # centre of upper half
    ext        = half_len * 0.8                      # shaft extension beyond coupling

    lines = [
        "// Shaft Coupling (rigid) — auto-generated from template",
        "$fn = 32;",
        f"// Shaft 1: Ø{spec.shaft_d1} mm  |  Shaft 2: Ø{spec.shaft_d2} mm",
        f"// Body OD: {spec.coupling_od} mm  |  Length: {spec.coupling_length} mm  |  Gap: {spec.gap} mm",
        "",
        get_module("shaft_coupling"),
        "",
        f'color("Silver")',
        (
            f"shaft_coupling(shaft_d1={spec.shaft_d1}, shaft_d2={spec.shaft_d2}, "
            f"od={spec.coupling_od}, length={spec.coupling_length}, gap={spec.gap});"
        ),
        "",
        "// Shaft extensions",
        f'color("DimGray", 0.7)',
        "union() {",
        f"  translate([0, 0, {z_bottom - ext/2:.3f}])",
        f"    cylinder(d={spec.shaft_d1}, h={ext:.3f}, center=true, $fn=32);",
        f"  translate([0, 0, {z_top + ext/2:.3f}])",
        f"    cylinder(d={spec.shaft_d2}, h={ext:.3f}, center=true, $fn=32);",
        "}",
    ]
    return "\n".join(lines)
