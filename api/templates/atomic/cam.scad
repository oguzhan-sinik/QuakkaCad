// Cam disc — base circle with a lobe defined by profile type
// Centered on origin, axis = Z
// profile: 0 = eccentric, 1 = pear, 2 = heart
module cam(base_r, lift, thickness, shaft_d, profile=0) {
    difference() {
        union() {
            // Base circle
            cylinder(r=base_r, h=thickness, center=true, $fn=64);
            // Lobe
            if (profile == 0) {
                // Eccentric: offset circle
                translate([lift/2, 0, 0])
                    cylinder(r=base_r, h=thickness, center=true, $fn=64);
            } else if (profile == 1) {
                // Pear: teardrop lobe
                hull() {
                    cylinder(r=base_r * 0.6, h=thickness, center=true, $fn=48);
                    translate([base_r + lift - base_r*0.3, 0, 0])
                        cylinder(r=base_r * 0.3, h=thickness, center=true, $fn=32);
                }
            } else {
                // Heart: two lobes
                hull() {
                    translate([base_r * 0.5 + lift * 0.3, base_r * 0.2, 0])
                        cylinder(r=base_r * 0.4, h=thickness, center=true, $fn=32);
                    translate([base_r * 0.5 + lift * 0.3, -base_r * 0.2, 0])
                        cylinder(r=base_r * 0.4, h=thickness, center=true, $fn=32);
                    translate([base_r + lift * 0.8, 0, 0])
                        cylinder(r=base_r * 0.15, h=thickness, center=true, $fn=24);
                }
            }
        }
        // Shaft bore
        cylinder(d=shaft_d, h=thickness+1, center=true, $fn=32);
    }
}
