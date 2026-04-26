"""Compose a finned rocket body from tube + rings + fins."""

from ..atomic import get_module
from ..models import FinnedRocketBodySpec


def compose(spec: FinnedRocketBodySpec) -> str:
    tube_id = spec.tube_outer_d - 2 * spec.tube_wall
    ring_od = spec.tube_outer_d + 2 * spec.ring_radial_thickness
    slot_width = spec.fin_thickness + 0.2  # clearance

    # Compute ring Z positions (centered around tube midpoint)
    ring_positions: list[float] = []
    if spec.ring_count > 0:
        spacing = spec.ring_spacing
        if spacing is None:
            spacing = (spec.tube_length - spec.ring_count * spec.ring_width) / (spec.ring_count + 1)
        total_span = (spec.ring_count - 1) * (spacing + spec.ring_width) if spec.ring_count > 1 else 0
        start_z = -total_span / 2
        for i in range(spec.ring_count):
            ring_positions.append(start_z + i * (spacing + spec.ring_width))

    # Build SCAD
    lines = [
        f"// Finned Rocket Body — auto-generated from template",
        f"$fn = 32;",
        "",
        get_module("tube"),
    ]

    if spec.ring_count > 0:
        if spec.fins_through_rings and spec.fin_count > 0:
            lines.append(get_module("slotted_ring"))
        else:
            lines.append(get_module("ring"))

    if spec.fin_count > 0:
        lines.append(get_module("trapezoidal_fin"))

    lines.append("")
    lines.append("// Assembly")
    lines.append("union() {")
    lines.append(f"    color(\"SteelBlue\") tube(od={spec.tube_outer_d}, id={tube_id}, length={spec.tube_length});")

    # Rings
    for z in ring_positions:
        if spec.fins_through_rings and spec.fin_count > 0:
            lines.append(
                f"    color(\"Gold\") translate([0, 0, {z}]) "
                f"slotted_ring(od={ring_od}, id={spec.tube_outer_d}, height={spec.ring_width}, "
                f"slot_count={spec.fin_count}, slot_width={slot_width}, "
                f"slot_depth={spec.ring_radial_thickness + 1});"
            )
        else:
            lines.append(
                f"    color(\"Gold\") translate([0, 0, {z}]) "
                f"ring(od={ring_od}, id={spec.tube_outer_d}, height={spec.ring_width});"
            )

    # Fins
    if spec.fin_count > 0:
        angle_step = 360 / spec.fin_count
        for i in range(spec.fin_count):
            lines.append(
                f"    color(\"Tomato\") rotate([0, 0, {i * angle_step}]) "
                f"translate([{spec.tube_outer_d / 2}, -{spec.fin_root_chord / 2}, 0]) "
                f"rotate([0, 0, 90]) "
                f"trapezoidal_fin(root_chord={spec.fin_root_chord}, tip_chord={spec.fin_tip_chord}, "
                f"height={spec.fin_height}, sweep={spec.fin_sweep}, thickness={spec.fin_thickness});"
            )

    lines.append("}")
    return "\n".join(lines)
