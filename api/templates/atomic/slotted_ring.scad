// Centering ring with radial slots, centered on origin, axis = Z
// Slots are evenly distributed around the ring for fin pass-through
module slotted_ring(od, id, height, slot_count, slot_width, slot_depth) {
    difference() {
        // Base ring
        difference() {
            cylinder(d=od, h=height, center=true, $fn=$fn);
            cylinder(d=id, h=height+1, center=true, $fn=$fn);
        }
        // Cut radial slots
        for (i = [0:slot_count-1]) {
            rotate([0, 0, i * (360 / slot_count)])
                translate([id/2 + slot_depth/2, 0, 0])
                    cube([slot_depth + 0.1, slot_width, height + 1], center=true);
        }
    }
}
