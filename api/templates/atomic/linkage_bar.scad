// Linkage bar — flat bar with pivot holes at each end
// Centered on midpoint, oriented along X axis
module linkage_bar(length, width, thickness, pivot_d) {
    difference() {
        hull() {
            translate([-length/2, 0, 0])
                cylinder(d=width, h=thickness, center=true, $fn=32);
            translate([length/2, 0, 0])
                cylinder(d=width, h=thickness, center=true, $fn=32);
        }
        // Pivot holes
        translate([-length/2, 0, 0])
            cylinder(d=pivot_d, h=thickness+1, center=true, $fn=24);
        translate([length/2, 0, 0])
            cylinder(d=pivot_d, h=thickness+1, center=true, $fn=24);
    }
}
