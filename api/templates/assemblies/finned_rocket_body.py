"""Compose a finned rocket body from tube + rings + fins."""

from ..atomic import get_module
from ..models import FinnedRocketBodySpec


def compose(spec: FinnedRocketBodySpec) -> str:
    tube_id = spec.tube_outer_d - 2 * spec.tube_wall
    ring_od = spec.tube_outer_d + 2 * spec.ring_radial_thickness
    slot_width = spec.fin_thickness + 0.2  # clearance

    # Compute ring Z positions (centered on tube — tube is centered at Z=0)
    ring_positions: list[float] = []
    if spec.ring_count > 0:
        spacing = spec.ring_spacing
        if spacing is None:
            spacing = (spec.tube_length - spec.ring_count * spec.ring_width) / (spec.ring_count + 1)
        if spec.ring_count == 1:
            ring_positions.append(0)
        else:
            total_span = (spec.ring_count - 1) * spacing
            for i in range(spec.ring_count):
                ring_positions.append(-total_span / 2 + i * spacing)

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
    lines.append(
        f"    color(\"SteelBlue\") "
        f"tube(od={spec.tube_outer_d}, id={tube_id}, length={spec.tube_length});"
    )

    # Rings
    for z in ring_positions:
        if spec.fins_through_rings and spec.fin_count > 0:
            lines.append(
                f"    color(\"Gold\") translate([0, 0, {z:.2f}]) "
                f"slotted_ring(od={ring_od}, id={spec.tube_outer_d}, "
                f"height={spec.ring_width}, "
                f"slot_count={spec.fin_count}, slot_width={slot_width:.1f}, "
                f"slot_depth={spec.ring_radial_thickness + 1});"
            )
        else:
            lines.append(
                f"    color(\"Gold\") translate([0, 0, {z:.2f}]) "
                f"ring(od={ring_od}, id={spec.tube_outer_d}, "
                f"height={spec.ring_width});"
            )

    # Fins — each fin: root chord along Z, height extends radially outward (+X after rotation)
    # The fin module: height in +X, chord in Z, thickness in Y, centered at origin
    # We translate it to the tube surface and rotate around Z for each fin
    if spec.fin_count > 0:
        angle_step = 360.0 / spec.fin_count
        for i in range(spec.fin_count):
            lines.append(
                f"    color(\"Tomato\") rotate([0, 0, {i * angle_step:.1f}]) "
                f"translate([{spec.tube_outer_d / 2}, 0, 0]) "
                f"trapezoidal_fin(root_chord={spec.fin_root_chord}, "
                f"tip_chord={spec.fin_tip_chord}, "
                f"height={spec.fin_height}, sweep={spec.fin_sweep}, "
                f"thickness={spec.fin_thickness});"
            )

    lines.append("}")
    return "\n".join(lines)
