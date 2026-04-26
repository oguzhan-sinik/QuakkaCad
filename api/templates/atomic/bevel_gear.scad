// Bevel gear — simplified conical gear with teeth on the face
// Axis = Z, pitch cone apex above origin
module bevel_gear(teeth, module_val, thickness, bore, cone_angle=45) {
    pitch_r = module_val * teeth / 2;
    outer_r = pitch_r + module_val;
    root_r = pitch_r - 1.25 * module_val;
    tooth_width = 3.14159 * module_val / 2;
    // Taper factor for conical shape
    taper = 1 - thickness * sin(cone_angle) / (2 * pitch_r);

    difference() {
        union() {
            // Tapered root cone
            cylinder(r1=root_r, r2=root_r * taper, h=thickness, center=false, $fn=max(teeth*2, 48));
            // Teeth
            for (i = [0:teeth-1]) {
                rotate([0, 0, i * 360 / teeth])
                    translate([root_r * 0.95, -tooth_width/2, 0])
                        linear_extrude(height=thickness, scale=[taper, taper])
                            square([module_val * 2, tooth_width]);
            }
        }
        // Bore
        if (bore > 0)
            translate([0, 0, -0.5])
                cylinder(d=bore, h=thickness+1, $fn=32);
    }
}
