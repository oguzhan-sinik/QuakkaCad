module rack(rack_length, rack_width, rack_height, module_val) {
    pitch    = 3.14159 * module_val;
    addendum = module_val;
    tooth_w  = pitch * 0.5;
    n        = floor(rack_length / pitch);
    union() {
        cube([rack_length, rack_width, rack_height], center=true);
        for (i = [0:n-1]) {
            translate([
                -rack_length/2 + pitch * (i + 0.5),
                0,
                rack_height/2 + addendum/2
            ])
                cube([tooth_w, rack_width, addendum], center=true);
        }
    }
}
