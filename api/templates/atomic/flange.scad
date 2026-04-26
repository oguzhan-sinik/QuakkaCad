// Bolt-pattern flange, centered on origin, axis = Z
module flange(od, id, thickness, bolt_count, bolt_circle_d, bolt_hole_d) {
    difference() {
        // Flange disc
        cylinder(d=od, h=thickness, center=true, $fn=$fn);
        // Center bore
        cylinder(d=id, h=thickness+1, center=true, $fn=$fn);
        // Bolt holes on circle
        for (i = [0:bolt_count-1]) {
            rotate([0, 0, i * (360 / bolt_count)])
                translate([bolt_circle_d/2, 0, 0])
                    cylinder(d=bolt_hole_d, h=thickness+1, center=true, $fn=$fn);
        }
    }
}
