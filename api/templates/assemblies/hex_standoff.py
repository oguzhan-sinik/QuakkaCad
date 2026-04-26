"""Compose a hex standoff with optional male stud on one end."""

from ..atomic import get_module
from ..models import HexStandoffSpec


def compose(spec: HexStandoffSpec) -> str:
    across_corners = spec.flat_to_flat / 0.866  # flat_to_flat / cos(30)

    lines = [
        "// Hex Standoff — auto-generated from template",
        "$fn = 32;",
        f"// M{spec.bore_d:.0f}  |  AF {spec.flat_to_flat} mm  |  AC {across_corners:.2f} mm  |  L {spec.length} mm",
        "",
        get_module("hex_standoff"),
        "",
    ]

    if spec.male_stud:
        lines += [
            f'color("Silver")',
            "union() {",
            f"  hex_standoff(flat_to_flat={spec.flat_to_flat}, length={spec.length}, bore_d={spec.bore_d});",
            f'  color("DimGray")',
            f"  translate([0, 0, {spec.length/2 + spec.stud_length/2:.3f}])",
            f"    cylinder(d={spec.stud_d}, h={spec.stud_length}, center=true, $fn=32);",
            "}",
        ]
    else:
        lines += [
            f'color("Silver")',
            f"hex_standoff(flat_to_flat={spec.flat_to_flat}, length={spec.length}, bore_d={spec.bore_d});",
        ]

    return "\n".join(lines)
