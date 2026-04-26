module hex_standoff(flat_to_flat, length, bore_d) {
    difference() {
        cylinder(d=flat_to_flat / cos(30), h=length, center=true, $fn=6);
        cylinder(d=bore_d, h=length+1, center=true);
    }
}
