// Centering ring, centered on origin, axis = Z
module ring(od, id, height) {
    difference() {
        cylinder(d=od, h=height, center=true, $fn=$fn);
        cylinder(d=id, h=height+1, center=true, $fn=$fn);
    }
}
