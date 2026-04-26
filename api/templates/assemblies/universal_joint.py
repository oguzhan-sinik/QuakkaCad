"""Compose a universal joint (U-joint) or double cardan (CV-like) joint."""

import math

from ..atomic import get_module
from ..models import UniversalJointSpec


def compose(spec: UniversalJointSpec) -> str:
    angle_rad = math.radians(spec.joint_angle)
    arm_length = spec.yoke_width * 0.6

    lines = [
        "// Universal Joint — auto-generated from template",
        "$fn = 32;",
        f"// Joint angle: {spec.joint_angle}°  |  "
        f"{'Double cardan (CV-like)' if spec.double_joint else 'Single U-joint'}",
        "",
        get_module("ujoint_yoke"),
        "",
    ]

    if not spec.double_joint:
        # Single U-joint
        lines.extend([
            "// Input yoke + shaft",
            f'color("SteelBlue")',
            f"rotate([0, -{spec.joint_angle / 2:.1f}, 0])",
            "union() {",
            (
                f"  ujoint_yoke(shaft_d={spec.shaft_d}, yoke_width={spec.yoke_width}, "
                f"yoke_thickness={spec.yoke_thickness}, cross_d={spec.cross_diameter}, "
                f"arm_length={arm_length:.1f});"
            ),
            f"  translate([0, 0, -{spec.shaft_length / 2:.1f}])",
            f"    cylinder(d={spec.shaft_d}, h={spec.shaft_length}, center=true, $fn=24);",
            "}",
            "",
            "// Output yoke + shaft",
            f'color("Gold")',
            f"rotate([0, {spec.joint_angle / 2:.1f}, 0])",
            f"rotate([0, 0, 90])",  # 90° offset for cross alignment
            "union() {",
            (
                f"  ujoint_yoke(shaft_d={spec.shaft_d}, yoke_width={spec.yoke_width}, "
                f"yoke_thickness={spec.yoke_thickness}, cross_d={spec.cross_diameter}, "
                f"arm_length={arm_length:.1f});"
            ),
            f"  translate([0, 0, -{spec.shaft_length / 2:.1f}])",
            f"    cylinder(d={spec.shaft_d}, h={spec.shaft_length}, center=true, $fn=24);",
            "}",
            "",
            "// Spider cross",
            f'color("Tomato")',
            "union() {",
            f"  rotate([0, 90, 0])",
            f"    cylinder(d={spec.cross_diameter}, h={spec.cross_length}, center=true, $fn=16);",
            f"  rotate([90, 0, 0])",
            f"    cylinder(d={spec.cross_diameter}, h={spec.cross_length}, center=true, $fn=16);",
            "}",
        ])
    else:
        # Double cardan joint — two U-joints with a short linking shaft
        link_len = spec.yoke_width * 1.5
        half_angle = spec.joint_angle / 2
        lines.extend([
            "// --- First U-joint ---",
            f'color("SteelBlue")',
            f"rotate([0, -{half_angle:.1f}, 0])",
            f"translate([0, 0, {link_len / 2:.1f}])",
            "union() {",
            (
                f"  ujoint_yoke(shaft_d={spec.shaft_d}, yoke_width={spec.yoke_width}, "
                f"yoke_thickness={spec.yoke_thickness}, cross_d={spec.cross_diameter}, "
                f"arm_length={arm_length:.1f});"
            ),
            f"  translate([0, 0, -{spec.shaft_length / 2:.1f}])",
            f"    cylinder(d={spec.shaft_d}, h={spec.shaft_length}, center=true, $fn=24);",
            "}",
            "",
            "// Centre link",
            f'color("Silver")',
            f"cylinder(d={spec.shaft_d}, h={link_len}, center=true, $fn=24);",
            "",
            "// --- Second U-joint ---",
            f'color("Gold")',
            f"rotate([0, {half_angle:.1f}, 0])",
            f"translate([0, 0, -{link_len / 2:.1f}])",
            f"rotate([0, 0, 90])",
            "union() {",
            (
                f"  ujoint_yoke(shaft_d={spec.shaft_d}, yoke_width={spec.yoke_width}, "
                f"yoke_thickness={spec.yoke_thickness}, cross_d={spec.cross_diameter}, "
                f"arm_length={arm_length:.1f});"
            ),
            f"  translate([0, 0, {spec.shaft_length / 2:.1f}])",
            f"    cylinder(d={spec.shaft_d}, h={spec.shaft_length}, center=true, $fn=24);",
            "}",
            "",
            "// Spider crosses",
            f'color("Tomato")',
            "union() {",
            f"  translate([0, 0, {link_len / 2:.1f}]) {{",
            f"    rotate([0, 90, 0]) cylinder(d={spec.cross_diameter}, h={spec.cross_length}, center=true, $fn=16);",
            f"    rotate([90, 0, 0]) cylinder(d={spec.cross_diameter}, h={spec.cross_length}, center=true, $fn=16);",
            "  }",
            f"  translate([0, 0, -{link_len / 2:.1f}]) {{",
            f"    rotate([0, 90, 0]) cylinder(d={spec.cross_diameter}, h={spec.cross_length}, center=true, $fn=16);",
            f"    rotate([90, 0, 0]) cylinder(d={spec.cross_diameter}, h={spec.cross_length}, center=true, $fn=16);",
            "  }",
            "}",
        ])

    return "\n".join(lines)
