// Spur gear with proper tooth profile
// Centered on origin, axis = Z
module spur_gear(teeth, module_val, thickness, bore) {
    pitch_r = module_val * teeth / 2;
    addendum = module_val;
    dedendum = 1.25 * module_val;
    outer_r = pitch_r + addendum;
    root_r = pitch_r - dedendum;
    tooth_angle = 360 / teeth;
    // Tooth width at pitch circle ~= half the circular pitch
    half_tooth_deg = tooth_angle * 0.25;

    difference() {
        union() {
            // Root disc
            cylinder(r=root_r, h=thickness, center=true, $fn=teeth*4);
            // Individual teeth
            for (i = [0:teeth-1]) {
                rotate([0, 0, i * tooth_angle])
                translate([0, 0, -thickness/2])
                linear_extrude(height=thickness)
                polygon(points=[
                    // Base of tooth (at root_r)
                    [root_r * cos(-half_tooth_deg), root_r * sin(-half_tooth_deg)],
                    // Left flank at pitch circle
                    [pitch_r * cos(-half_tooth_deg * 0.7), pitch_r * sin(-half_tooth_deg * 0.7)],
                    // Tip of tooth
                    [outer_r * cos(0), outer_r * sin(0)],
                    // Right flank at pitch circle
                    [pitch_r * cos(half_tooth_deg * 0.7), pitch_r * sin(half_tooth_deg * 0.7)],
                    // Base of tooth (at root_r)
                    [root_r * cos(half_tooth_deg), root_r * sin(half_tooth_deg)]
                ]);
            }
        }
        // Center bore
        if (bore > 0)
            cylinder(d=bore, h=thickness + 1, center=true, $fn=$fn);
    }
}
