// Lead screw shaft — threaded rod with helical thread profile
// Oriented along X axis, centered at origin
module lead_screw_shaft(length, diameter, lead, starts, bore_d) {
    pitch = lead / starts;
    root_r = diameter / 2 - 0.75;
    thread_r = diameter / 2;
    twist = 360 * length / lead;

    rotate([0, 90, 0])
    difference() {
        union() {
            // Core shaft
            cylinder(d=diameter * 0.85, h=length, center=true, $fn=32);
            // Thread helix
            translate([0, 0, -length/2])
                linear_extrude(height=length, twist=-twist, slices=max(60, round(length/pitch)*8))
                    for (s = [0:starts-1])
                        rotate([0, 0, s * 360 / starts])
                            translate([root_r, 0])
                                circle(r=pitch * 0.3, $fn=6);
        }
        // Bore
        if (bore_d > 0)
            cylinder(d=bore_d, h=length+1, center=true, $fn=24);
    }
}
