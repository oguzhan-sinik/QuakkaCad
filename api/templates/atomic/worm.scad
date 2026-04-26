module worm(starts, module_val, length, bore_d) {
    pitch_r = module_val * 4;
    root_r  = max(bore_d / 2 + 0.5, pitch_r - 1.25 * module_val);
    lead    = 3.14159 * module_val * 2 * starts;
    twist   = 360 * length / lead;

    rotate([0, 90, 0])
    difference() {
        union() {
            cylinder(r=root_r, h=length, center=true, $fn=32);
            translate([0, 0, -length/2])
                linear_extrude(height=length, twist=-twist, slices=60)
                    for (s = [0:starts-1])
                        rotate([0, 0, s * 360 / starts])
                            translate([pitch_r, 0])
                                circle(r=module_val * 0.75, $fn=8);
        }
        cylinder(d=bore_d, h=length+1, center=true, $fn=32);
    }
}
