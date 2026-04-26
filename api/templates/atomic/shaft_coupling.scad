module shaft_coupling(shaft_d1, shaft_d2, od, length, gap) {
    half_len = (length - gap) / 2;
    union() {
        translate([0, 0, -(gap/2 + half_len/2)])
            difference() {
                cylinder(d=od, h=half_len, center=true, $fn=32);
                cylinder(d=shaft_d1, h=half_len+1, center=true);
            }
        translate([0, 0, gap/2 + half_len/2])
            difference() {
                cylinder(d=od, h=half_len, center=true, $fn=32);
                cylinder(d=shaft_d2, h=half_len+1, center=true);
            }
    }
}
