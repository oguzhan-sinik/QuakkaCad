"""Compose a belt-and-pulley or chain-and-sprocket drive between two shafts."""

import math

from ..atomic import get_module
from ..models import BeltPulleySpec


def compose(spec: BeltPulleySpec) -> str:
    r1 = spec.driver_diameter / 2
    r2 = spec.driven_diameter / 2
    cd = spec.center_distance
    ratio = spec.driven_diameter / spec.driver_diameter
    is_chain = spec.drive_type == "chain"
    drive_label = "Chain & Sprocket" if is_chain else "Belt & Pulley"

    lines = [
        f"// {drive_label} — auto-generated from template",
        "$fn = 32;",
        f"// Ratio: {ratio:.2f}:1  |  Centre distance: {cd} mm",
        "",
        get_module("pulley"),
        "",
    ]

    # Driver pulley at origin
    lines.extend([
        "// Driver pulley/sprocket",
        f'color("SteelBlue")',
        (
            f"pulley(pitch_d={spec.driver_diameter}, face_width={spec.pulley_thickness}, "
            f"bore_d={spec.bore_d}, groove_depth={spec.belt_thickness});"
        ),
        "",
        "// Driver axle",
        f'color("DimGray")',
        f"cylinder(d={spec.bore_d * 0.8:.2f}, h={spec.pulley_thickness * 2}, center=true, $fn=16);",
        "",
    ])

    # Driven pulley at (center_distance, 0, 0)
    lines.extend([
        "// Driven pulley/sprocket",
        f'color("Gold")',
        f"translate([{cd:.3f}, 0, 0])",
        (
            f"  pulley(pitch_d={spec.driven_diameter}, face_width={spec.pulley_thickness}, "
            f"bore_d={spec.bore_d}, groove_depth={spec.belt_thickness});"
        ),
        "",
        "// Driven axle",
        f'color("DimGray")',
        f"translate([{cd:.3f}, 0, 0])",
        f"  cylinder(d={spec.bore_d * 0.8:.2f}, h={spec.pulley_thickness * 2}, center=true, $fn=16);",
        "",
    ])

    # Belt/chain — approximate as two tangent lines + two arcs
    # Tangent angle for cross-belt geometry
    if cd > 0:
        sin_alpha = (r2 - r1) / cd
        sin_alpha = max(-1, min(1, sin_alpha))
        alpha = math.asin(sin_alpha)
        cos_alpha = math.cos(alpha)

        # Tangent points on driver
        t1_y = r1 * cos_alpha
        t1_x = r1 * sin_alpha
        # Tangent points on driven
        t2_y = r2 * cos_alpha
        t2_x = cd + r2 * sin_alpha

        belt_color = "DimGray" if is_chain else "Tomato"
        belt_label = "Chain" if is_chain else "Belt"
        belt_h = spec.belt_width * 0.3

        lines.extend([
            f"// {belt_label} (straight runs + wrap arcs)",
            f'color("{belt_color}", 0.6)',
            "union() {",
            f"  // Upper straight run",
            f"  hull() {{",
            f"    translate([{-t1_x:.3f}, {t1_y:.3f}, 0])",
            f"      cube([{spec.belt_thickness}, {spec.belt_thickness}, {belt_h:.1f}], center=true);",
            f"    translate([{t2_x - cd + cd:.3f}, {t2_y:.3f}, 0])",
            f"      cube([{spec.belt_thickness}, {spec.belt_thickness}, {belt_h:.1f}], center=true);",
            "  }",
            f"  // Lower straight run",
            f"  hull() {{",
            f"    translate([{t1_x:.3f}, {-t1_y:.3f}, 0])",
            f"      cube([{spec.belt_thickness}, {spec.belt_thickness}, {belt_h:.1f}], center=true);",
            f"    translate([{cd - (t2_x - cd):.3f}, {-t2_y:.3f}, 0])",
            f"      cube([{spec.belt_thickness}, {spec.belt_thickness}, {belt_h:.1f}], center=true);",
            "  }",
            "}",
        ])

    return "\n".join(lines)
