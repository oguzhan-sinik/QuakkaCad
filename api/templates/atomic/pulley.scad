// Pulley — grooved wheel for belt/chain drive
// Centered on origin, axis = Z
module pulley(pitch_d, face_width, bore_d, groove_depth) {
    outer_r = pitch_d / 2 + groove_depth * 0.3;
    groove_r = pitch_d / 2 - groove_depth;
    flange_r = pitch_d / 2 + groove_depth;

    difference() {
        union() {
            // Central groove section
            cylinder(r=outer_r, h=face_width * 0.7, center=true, $fn=48);
            // Flanges at edges
            translate([0, 0, face_width * 0.35])
                cylinder(r=flange_r, h=face_width * 0.15, center=true, $fn=48);
            translate([0, 0, -face_width * 0.35])
                cylinder(r=flange_r, h=face_width * 0.15, center=true, $fn=48);
        }
        // Belt groove (torus-like cut)
        rotate_extrude($fn=48)
            translate([pitch_d/2, 0, 0])
                circle(r=groove_depth, $fn=16);
        // Bore
        cylinder(d=bore_d, h=face_width+1, center=true, $fn=32);
    }
}
