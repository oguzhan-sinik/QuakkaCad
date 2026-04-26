// Trapezoidal fin using hull() of root and tip rectangles
// Orientation: root chord along Z, height extends in +X, thickness in Y
// Centered on origin in Y and Z
module trapezoidal_fin(root_chord, tip_chord, height, sweep, thickness) {
    hull() {
        // Root rectangle — at X=0
        translate([0, -thickness/2, -root_chord/2])
            cube([0.1, thickness, root_chord]);
        // Tip rectangle — at X=height, shifted by sweep along Z
        translate([height, -thickness/2, -tip_chord/2 + sweep])
            cube([0.1, thickness, tip_chord]);
    }
}
