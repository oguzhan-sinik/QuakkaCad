// Internal ring gear — teeth face inward
// Centered on origin, axis = Z
module ring_gear(teeth, module_val, thickness, wall) {
    pitch_r = module_val * teeth / 2;
    inner_r = pitch_r - module_val;       // tip of internal teeth
    root_r = pitch_r + 1.25 * module_val; // root of internal teeth
    outer_r = root_r + wall;
    tooth_width = 3.14159 * module_val / 2;
    tooth_height = root_r - inner_r;

    difference() {
        // Outer wall
        cylinder(r=outer_r, h=thickness, center=true, $fn=max(teeth*2, 64));
        // Hollow interior (to the inner tooth tips)
        cylinder(r=inner_r, h=thickness+1, center=true, $fn=max(teeth*2, 64));
        // Cut tooth gaps (material between teeth stays, gaps are removed)
        for (i = [0:teeth-1]) {
            rotate([0, 0, i * 360 / teeth + 360 / teeth / 2])
                translate([inner_r + tooth_height/2, -tooth_width/2, -thickness/2 - 0.5])
                    cube([tooth_height, tooth_width, thickness + 1]);
        }
    }
}
