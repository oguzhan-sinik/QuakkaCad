module helical_spring(wire_d, coil_od, free_length, coil_count, steps_per_turn=16) {
    coil_r      = (coil_od - wire_d) / 2;
    total_steps = round(coil_count * steps_per_turn);
    step_z      = free_length / total_steps;
    step_angle  = 360.0 / steps_per_turn;
    union() {
        for (i = [0:total_steps-1]) {
            hull() {
                translate([
                    coil_r * cos(i * step_angle),
                    coil_r * sin(i * step_angle),
                    i * step_z
                ]) sphere(d=wire_d, $fn=6);
                translate([
                    coil_r * cos((i+1) * step_angle),
                    coil_r * sin((i+1) * step_angle),
                    (i+1) * step_z
                ]) sphere(d=wire_d, $fn=6);
            }
        }
    }
}
