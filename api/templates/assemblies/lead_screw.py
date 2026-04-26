"""Compose a lead screw / ball screw assembly: threaded shaft with travelling nut."""

from ..atomic import get_module
from ..models import LeadScrewSpec


def compose(spec: LeadScrewSpec) -> str:
    # Nut position along the screw (centered at origin, screw along X)
    nut_x = -spec.screw_length / 2 + spec.nut_length / 2 + (
        spec.screw_length - spec.nut_length
    ) * spec.nut_position

    screw_type = "Ball Screw" if spec.ball_screw else "Lead Screw"
    pitch = spec.lead / spec.starts
    travel_per_rev = spec.lead

    lines = [
        f"// {screw_type} — auto-generated from template",
        "$fn = 32;",
        f"// Lead: {travel_per_rev:.1f} mm/rev  |  {spec.starts}-start  |  "
        f"Pitch: {pitch:.2f} mm",
        "",
        get_module("lead_screw_shaft"),
        "",
        "// Screw shaft (along X)",
        f'color("Silver")',
        (
            f"lead_screw_shaft(length={spec.screw_length}, diameter={spec.screw_diameter}, "
            f"lead={spec.lead}, starts={spec.starts}, bore_d={spec.bore_d});"
        ),
        "",
        f"// Nut ({screw_type.lower()} nut)",
        f'color("{"Gold" if spec.ball_screw else "SteelBlue"}")',
        f"translate([{nut_x:.3f}, 0, 0])",
        f"  rotate([0, 90, 0])",
        "  difference() {",
        f"    cylinder(d={spec.nut_od}, h={spec.nut_length}, center=true, $fn=6);",
        f"    cylinder(d={spec.screw_diameter + 0.5}, h={spec.nut_length + 1}, center=true, $fn=32);",
        "  }",
    ]

    if spec.ball_screw:
        # Add ball return tube indicator
        lines.extend([
            "",
            "// Ball return tube (indicator)",
            f'color("DimGray", 0.5)',
            f"translate([{nut_x:.3f}, {spec.nut_od / 2 + 2:.1f}, 0])",
            f"  rotate([0, 90, 0])",
            f"  cylinder(d={spec.screw_diameter * 0.3:.1f}, h={spec.nut_length * 0.8:.1f}, center=true, $fn=16);",
        ])

    # Support bearing indicators at ends
    bearing_r = spec.screw_diameter * 0.8
    lines.extend([
        "",
        "// End bearings",
        f'color("DimGray")',
        "union() {",
        f"  translate([{-spec.screw_length / 2 - 2:.1f}, 0, 0])",
        f"    rotate([0, 90, 0]) cylinder(d={bearing_r * 2:.1f}, h=4, center=true, $fn=32);",
        f"  translate([{spec.screw_length / 2 + 2:.1f}, 0, 0])",
        f"    rotate([0, 90, 0]) cylinder(d={bearing_r * 2:.1f}, h=4, center=true, $fn=32);",
        "}",
    ])
    return "\n".join(lines)
