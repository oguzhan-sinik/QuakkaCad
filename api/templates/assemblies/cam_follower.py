"""Compose a cam and follower assembly: shaped cam disc with roller follower."""

from ..atomic import get_module
from ..models import CamFollowerSpec


_PROFILE_MAP = {"eccentric": 0, "pear": 1, "heart": 2}


def compose(spec: CamFollowerSpec) -> str:
    profile_id = _PROFILE_MAP.get(spec.cam_profile, 0)
    # Follower sits above the cam at the highest point
    max_r = spec.base_radius + spec.lift
    follower_base_z = max_r + spec.follower_diameter / 2 + 1  # small clearance

    lines = [
        f"// Cam and Follower ({spec.cam_profile}) — auto-generated from template",
        "$fn = 32;",
        f"// Base radius: {spec.base_radius} mm  |  Lift: {spec.lift} mm  |  "
        f"Profile: {spec.cam_profile}",
        "",
        get_module("cam"),
        "",
        "// Cam disc",
        f'color("SteelBlue")',
        (
            f"cam(base_r={spec.base_radius}, lift={spec.lift}, "
            f"thickness={spec.cam_thickness}, shaft_d={spec.shaft_d}, "
            f"profile={profile_id});"
        ),
        "",
        "// Camshaft",
        f'color("DimGray")',
        f"cylinder(d={spec.shaft_d * 0.9:.2f}, h={spec.cam_thickness * 3}, center=true, $fn=24);",
        "",
        "// Follower roller",
        f'color("Tomato")',
        f"translate([{max_r:.3f}, 0, 0])",
        f"  rotate([90, 0, 0])",
        f"  cylinder(d={spec.follower_diameter}, h={spec.cam_thickness * 0.8:.1f}, center=true, $fn=32);",
        "",
        "// Follower stem (guide rod)",
        f'color("Silver")',
        f"translate([{max_r:.3f}, 0, {spec.follower_length / 2:.1f}])",
        f"  cylinder(d={spec.follower_diameter * 0.4:.1f}, h={spec.follower_length}, center=true, $fn=16);",
        "",
        "// Follower guide block",
        f'color("DimGray", 0.4)',
        f"translate([{max_r:.3f}, 0, {spec.follower_length + 5:.1f}])",
        f"  cube([{spec.follower_diameter * 1.5:.1f}, {spec.cam_thickness:.1f}, 10], center=true);",
    ]
    return "\n".join(lines)
