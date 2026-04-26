"""Compose a finned rocket body from tube + rings + fins.

Emits a parameterized OpenSCAD file in the style of a hand-written
fin-can assembly: named parameters at the top, derived radii, inline
slot cuts in the ring module, and fins built via linear_extrude of a
trapezoidal polygon.
"""

from ..models import FinnedRocketBodySpec


def compose(spec: FinnedRocketBodySpec) -> str:
    # --- Derive ring Z positions along the full tube (tube runs 0 -> tube_length) ---
    fin_center_z = spec.tube_length / 2.0
    ring_positions: list[float] = []

    if spec.ring_count > 0:
        if spec.ring_count == 1:
            ring_positions.append(fin_center_z - spec.ring_width / 2.0)
        elif spec.ring_count == 2:
            spacing = spec.ring_spacing
            if spacing is None:
                spacing = spec.fin_root_chord
            ring_positions.append(fin_center_z - spacing / 2.0 - spec.ring_width)
            ring_positions.append(fin_center_z + spacing / 2.0)
        else:
            spacing = spec.ring_spacing
            if spacing is None:
                spacing = (spec.tube_length - spec.ring_count * spec.ring_width) / (spec.ring_count + 1)
            total_span = (spec.ring_count - 1) * (spacing + spec.ring_width)
            first_z = fin_center_z - total_span / 2.0 - spec.ring_width / 2.0
            for i in range(spec.ring_count):
                ring_positions.append(first_z + i * (spacing + spec.ring_width))

    ring_spacing_param = (
        spec.ring_spacing if spec.ring_spacing is not None else spec.fin_root_chord
    )
    show_slots = spec.fins_through_rings and spec.fin_count > 0 and spec.ring_count > 0

    lines: list[str] = []

    # --- Header / parameters ---
    lines += [
        "// Rocket fin can assembly",
        f"// {spec.fin_count} fins held between {spec.ring_count} ring(s), motor tube nest in the middle",
        "// Auto-generated from FinnedRocketBodySpec",
        "",
        "// === Parameters ===",
        f"motor_diameter = {spec.tube_outer_d};          // Motor tube outer diameter",
        f"motor_tube_thickness = {spec.tube_wall};     // Wall thickness of the tube",
        f"motor_tube_length = {spec.tube_length};      // Length of the motor tube",
        f"ring_width = {spec.ring_width};              // Width of the rings (along tube axis)",
        f"ring_thickness = {spec.ring_radial_thickness};           // Radial thickness of the rings",
        f"ring_spacing = {ring_spacing_param};            // Distance between rings (inner edge to inner edge)",
        f"num_fins = {spec.fin_count};",
        f"fin_height = {spec.fin_height};             // How far the fin extends from the tube",
        f"fin_root_chord = {spec.fin_root_chord};         // Length of fin where it meets the tube",
        f"fin_tip_chord = {spec.fin_tip_chord};          // Length of fin at the outer edge",
        f"fin_sweep = {spec.fin_sweep};               // How far back the tip is swept from the root leading edge",
        f"fin_thickness = {spec.fin_thickness};            // Fin material thickness",
        "show_motor_tube = true;       // Toggle motor tube visibility",
        "$fn = 96;",
        "",
        "// === Derived values ===",
        "motor_outer_r = motor_diameter / 2;",
        "ring_outer_r = motor_outer_r + ring_thickness;",
        "fin_outer_r = motor_outer_r + fin_height;",
        "",
    ]

    # --- Motor tube ---
    lines += [
        "// === Motor tube ===",
        "module motor_tube() {",
        "    difference() {",
        "        cylinder(h = motor_tube_length, d = motor_diameter + motor_tube_thickness * 2);",
        "        translate([0, 0, -0.1])",
        "            cylinder(h = motor_tube_length + 0.2, d = motor_diameter);",
        "    }",
        "}",
        "",
    ]

    # --- Ring (with optional inline fin slots) ---
    lines += [
        "// === Single ring (centering ring that wraps around tube) ===",
        "module ring(z_pos) {",
        "    translate([0, 0, z_pos])",
        "        difference() {",
        "            cylinder(h = ring_width, r = ring_outer_r);",
        "            translate([0, 0, -0.1])",
        "                cylinder(h = ring_width + 0.2, r = motor_outer_r);",
    ]
    if show_slots:
        lines += [
            "",
            "            // Slots in the rings for fins to pass through",
            "            for (i = [0 : num_fins - 1]) {",
            "                angle = i * (360 / num_fins);",
            "                rotate([0, 0, angle])",
            "                    translate([motor_outer_r - 0.5, -fin_thickness / 2, -0.1])",
            "                        cube([ring_thickness + 1, fin_thickness, ring_width + 0.2]);",
            "            }",
        ]
    lines += ["        }", "}", ""]

    # --- Fin ---
    if spec.fin_count > 0:
        lines += [
            "// === Single fin (trapezoidal, swept back) ===",
            "module fin(z_center) {",
            "    root_z_start = z_center - fin_root_chord / 2;",
            "    tip_z_start  = root_z_start + fin_sweep;",
            "",
            "    translate([0, -fin_thickness / 2, 0])",
            "        rotate([90, 0, 0])",
            "            linear_extrude(height = fin_thickness)",
            "                polygon(points = [",
            "                    [motor_outer_r, root_z_start],                      // root leading edge",
            "                    [motor_outer_r, root_z_start + fin_root_chord],     // root trailing edge",
            "                    [fin_outer_r,   tip_z_start + fin_tip_chord],       // tip trailing edge",
            "                    [fin_outer_r,   tip_z_start]                        // tip leading edge",
            "                ]);",
            "}",
            "",
        ]

    # --- Assembly ---
    lines += [
        "// === Assembly ===",
        "fin_center_z = motor_tube_length / 2;",
    ]
    if len(ring_positions) == 2:
        lines += [
            "ring1_z = fin_center_z - ring_spacing / 2 - ring_width;",
            "ring2_z = fin_center_z + ring_spacing / 2;",
        ]
    lines.append("")

    lines += [
        "if (show_motor_tube) {",
        f'    color("{spec.body_color}") motor_tube();',
        "}",
        "",
    ]

    if spec.ring_count > 0 or spec.fin_count > 0:
        lines.append(f'color("{spec.ring_color}") {{')

        if len(ring_positions) == 2:
            lines += ["    ring(ring1_z);", "    ring(ring2_z);"]
        else:
            for z in ring_positions:
                lines.append(f"    ring({z:.2f});")

        if spec.fin_count > 0:
            lines += [
                "",
                "    // Place fins around the tube",
                "    for (i = [0 : num_fins - 1]) {",
                "        angle = i * (360 / num_fins);",
                "        rotate([0, 0, angle])",
                "            fin(fin_center_z);",
                "    }",
            ]

        lines.append("}")

    return "\n".join(lines) + "\n"