// U-joint yoke — fork-shaped end fitting for a universal joint
// Opens along Y axis, shaft along Z
module ujoint_yoke(shaft_d, yoke_width, yoke_thickness, cross_d, arm_length) {
    gap = cross_d + 2;  // clearance for the cross journal
    arm_h = arm_length;

    difference() {
        union() {
            // Base hub
            cylinder(d=yoke_width, h=yoke_thickness, center=true, $fn=32);
            // Two arms extending in +Z
            translate([yoke_width/2 - yoke_thickness/2, 0, arm_h/2])
                cube([yoke_thickness, yoke_thickness, arm_h], center=true);
            translate([-(yoke_width/2 - yoke_thickness/2), 0, arm_h/2])
                cube([yoke_thickness, yoke_thickness, arm_h], center=true);
        }
        // Shaft bore through hub
        cylinder(d=shaft_d, h=yoke_thickness+1, center=true, $fn=24);
        // Cross pin holes through arm tips
        translate([0, 0, arm_h])
            rotate([0, 90, 0])
                cylinder(d=cross_d, h=yoke_width+1, center=true, $fn=24);
    }
}
