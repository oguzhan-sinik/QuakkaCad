"""Compose a stack assembly — multiple templates positioned and rotated.

Each sub-spec is composed independently by its own composer, then the
resulting SCAD source blocks are wrapped in translate + rotate and
combined into a single file.
"""

from ..models import StackAssemblySpec


def compose(spec: StackAssemblySpec) -> str:
    # Late import to avoid circular dependency (this module is registered
    # inside _COMPOSERS which lives in __init__.py)
    from . import _COMPOSERS

    lines = [
        "// Stack Assembly — auto-generated from template",
        f"// {len(spec.parts)} part(s)",
        "$fn = 64;",
        "",
    ]

    for idx, part in enumerate(spec.parts):
        sub_spec = part.spec
        sub_type = sub_spec.assembly_type
        composer_fn = _COMPOSERS.get(sub_type)
        if composer_fn is None:
            lines.append(f"// ERROR: unknown assembly_type '{sub_type}' for part {idx}")
            continue

        sub_scad = composer_fn(sub_spec)

        has_rotation = part.rx != 0 or part.ry != 0 or part.rz != 0
        pos_comment = f"z={part.z_offset}"
        if part.x_offset != 0 or part.y_offset != 0:
            pos_comment = f"x={part.x_offset}, y={part.y_offset}, {pos_comment}"
        if has_rotation:
            pos_comment += f", rot=[{part.rx},{part.ry},{part.rz}]"

        lines.append(f"// --- Part {idx + 1}: {sub_type} ({pos_comment}) ---")

        # OpenSCAD applies transforms inside-out, so we write:
        #   translate(pos) rotate(angles) { geometry }
        lines.append(
            f"translate([{part.x_offset}, {part.y_offset}, {part.z_offset}])"
        )
        if has_rotation:
            lines.append(f"rotate([{part.rx}, {part.ry}, {part.rz}])")
        lines.append("{")

        # Indent sub-SCAD and strip duplicate $fn declarations
        for line in sub_scad.splitlines():
            stripped = line.strip()
            if stripped.startswith("$fn"):
                continue
            lines.append(f"    {line}")

        lines.append("}")
        lines.append("")

    return "\n".join(lines)
