"""Compose a rack-and-pinion assembly: flat rack with meshing spur pinion."""

from ..atomic import get_module
from ..models import RackAndPinionSpec


def compose(spec: RackAndPinionSpec) -> str:
    pinion_pr = spec.module_val * spec.pinion_teeth / 2
    # Rack pitch line is at the tooth root (top of base bar); pinion centre sits
    # one pitch radius above that, with a small clearance for the addendum.
    pinion_z = spec.rack_height / 2 + spec.module_val + pinion_pr

    lines = [
        "// Rack and Pinion — auto-generated from template",
        "$fn = 32;",
        f"// Ratio: 1 revolution moves rack {spec.module_val * 3.14159 * spec.pinion_teeth:.1f} mm",
        "",
        get_module("rack"),
        "",
        get_module("spur_gear"),
        "",
        "// Rack",
        f'color("SteelBlue")',
        (
            f"rack(rack_length={spec.rack_length}, rack_width={spec.rack_width}, "
            f"rack_height={spec.rack_height}, module_val={spec.module_val});"
        ),
        "",
        "// Pinion (centred over rack pitch line)",
        f'color("Tomato")',
        f"translate([0, 0, {pinion_z:.3f}])",
        (
            f"  spur_gear(teeth={spec.pinion_teeth}, module_val={spec.module_val}, "
            f"thickness={spec.pinion_thickness}, bore={spec.bore_d});"
        ),
        "",
        "// Pinion axle",
        f'color("DimGray")',
        f"translate([0, 0, {pinion_z:.3f}])",
        f"  cylinder(d={spec.bore_d * 0.8:.2f}, h={spec.pinion_thickness * 2}, center=true, $fn=32);",
    ]
    return "\n".join(lines)
