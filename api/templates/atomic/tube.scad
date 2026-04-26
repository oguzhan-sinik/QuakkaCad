// Hollow cylinder (tube), centered on origin, axis = Z
module tube(od, id, length) {
    difference() {
        cylinder(d=od, h=length, center=true, $fn=$fn);
        cylinder(d=id, h=length+1, center=true, $fn=$fn);
    }
}
