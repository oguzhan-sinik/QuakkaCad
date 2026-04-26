// Spur gear — rectangular teeth on a root disc
// Centered on origin, axis = Z
module spur_gear(teeth, module_val, thickness, bore) {
    pitch_r = module_val * teeth / 2;
    outer_r = pitch_r + module_val;
    root_r = pitch_r - 1.25 * module_val;
    // Tooth arc width at pitch circle ≈ half circular pitch
    tooth_width = 3.14159 * module_val / 2;
    tooth_height = outer_r - root_r;

    difference() {
        union() {
            // Root disc
            cylinder(r=root_r, h=thickness, center=true, $fn=max(teeth*2, 48));
            // Teeth — each is a cube at the right radial position, rotated around Z
            for (i = [0:teeth-1]) {
                rotate([0, 0, i * 360 / teeth])
                    translate([root_r + tooth_height/2, -tooth_width/2, -thickness/2])
                        cube([tooth_height, tooth_width, thickness]);
            }
        }
        // Bore
        if (bore > 0)
            cylinder(d=bore, h=thickness+1, center=true, $fn=32);
    }
}
