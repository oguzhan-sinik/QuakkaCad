"""Render pipeline: prompt → agent → spec → compose → .scad source."""

from __future__ import annotations

import asyncio
import logging
import math

from .agent import run_template_agent
from .assemblies import dispatch_compose
from .models import (
    AssemblySpec,
    BeltPulleySpec,
    BodyTubeSpec,
    BulkheadSpec,
    BushingAssemblySpec,
    CamFollowerSpec,
    DifferentialGearSpec,
    FinnedRocketBodySpec,
    FlangedTubeSpec,
    FourBarLinkageSpec,
    GearTrainSpec,
    HelicalSpringSpec,
    HexStandoffSpec,
    LeadScrewSpec,
    MountingPlateSpec,
    PlanetaryGearSpec,
    RackAndPinionSpec,
    ShaftCouplingSpec,
    UniversalJointSpec,
    WormGearSpec,
)

logger = logging.getLogger(__name__)

_ALL_ASSEMBLY_TYPES = [
    "finned_rocket_body",
    "gear_train",
    "planetary_gear",
    "bushing_assembly",
    "flanged_tube",
    "rack_and_pinion",
    "worm_gear",
    "helical_spring",
    "shaft_coupling",
    "hex_standoff",
    "four_bar_linkage",
    "lead_screw",
    "cam_follower",
    "universal_joint",
    "belt_pulley",
    "differential_gear",
    "bulkhead",
    "body_tube",
    "mounting_plate",
]


async def render_from_prompt(
    prompt: str,
    provider: str = "anthropic",
) -> tuple[AssemblySpec, str, dict]:
    """Full pipeline: prompt → AssemblySpec → .scad source string.

    Returns (spec, scad_source, meta).
    The frontend WASM worker handles compilation.
    """
    spec, meta = await run_template_agent(prompt, provider=provider)
    scad_source = dispatch_compose(spec)
    meta["scad_length"] = len(scad_source)
    logger.info(
        "Template render complete: %s, %d chars SCAD",
        spec.assembly_type, len(scad_source),
    )

    # Record the generation trace into the shared MuBit library session so
    # future get_template_context() calls can learn from parameter choices.
    from mubit_client import remember_template_generation
    asyncio.create_task(
        remember_template_generation(
            prompt=prompt,
            assembly_type=spec.assembly_type,
            scad_length=len(scad_source),
            model_used=meta.get("model_name", "unknown"),
        )
    )

    return spec, scad_source, meta


async def compose_from_spec(spec: AssemblySpec) -> tuple[AssemblySpec, str, dict]:
    """Free-tier path: directly compose SCAD from a pre-built spec, no LLM.

    Returns (spec, scad_source, meta). Fires a MuBit trace in the background
    so programmatic generations accumulate in the shared library session.
    """
    scad_source = dispatch_compose(spec)
    meta = {
        "assembly_type": spec.assembly_type,
        "scad_length": len(scad_source),
        "model_name": "programmatic",
        "latency_ms": 0.0,
    }
    logger.info("Programmatic compose: %s, %d chars SCAD", spec.assembly_type, len(scad_source))
    from mubit_client import remember_template_generation
    asyncio.create_task(
        remember_template_generation(
            prompt=f"[programmatic] {spec.assembly_type}",
            assembly_type=spec.assembly_type,
            scad_length=len(scad_source),
            model_used="programmatic",
        )
    )
    return spec, scad_source, meta


def _build_diverse_spec_library(
    count: int,
    assembly_types: list[str] | None = None,
    seed: int = 42,
) -> list[AssemblySpec]:
    """Generate `count` diverse AssemblySpec objects via parametric interpolation.

    No LLM, no randomness — deterministic linear sweeps across valid parameter
    ranges. Each selected assembly type gets floor(count / n_types) specs, with
    remainder distributed to earlier types. All Pydantic validators are respected.
    """
    types = [t for t in (assembly_types or _ALL_ASSEMBLY_TYPES) if t in _ALL_ASSEMBLY_TYPES]
    if not types:
        return []

    n = len(types)
    base, extra = divmod(count, n)
    per_type = [base + (1 if i < extra else 0) for i in range(n)]

    specs: list[AssemblySpec] = []
    for type_name, k in zip(types, per_type):
        specs.extend(_sweep_type(type_name, k, seed))
    return specs


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _t(i: int, k: int) -> float:
    return i / max(k - 1, 1)


def _sweep_type(assembly_type: str, k: int, seed: int) -> list[AssemblySpec]:
    specs: list[AssemblySpec] = []

    if assembly_type == "finned_rocket_body":
        fin_counts = [3, 4, 3, 4, 3, 4, 3, 4]
        ring_counts = [0, 1, 2, 0, 1, 2, 0, 1]
        for i in range(k):
            t = _t(i, k)
            tube_od = round(_lerp(29, 150, t), 1)
            tube_len = round(_lerp(100, 800, t), 1)
            fin_rc = min(round(_lerp(30, 120, t), 1), tube_len * 0.8)
            specs.append(FinnedRocketBodySpec(
                reasoning="parametric sweep",
                tube_outer_d=tube_od,
                tube_wall=round(_lerp(1.5, 5.0, t), 1),
                tube_length=tube_len,
                ring_count=ring_counts[i % len(ring_counts)],
                ring_width=round(_lerp(8, 20, t), 1),
                ring_radial_thickness=round(_lerp(3, 8, t), 1),
                ring_spacing=None,
                fin_count=fin_counts[i % len(fin_counts)],
                fin_root_chord=fin_rc,
                fin_tip_chord=round(fin_rc * 0.35, 1),
                fin_height=round(_lerp(20, 90, t), 1),
                fin_sweep=round(_lerp(10, 50, t), 1),
                fin_thickness=round(_lerp(2, 5, t), 1),
                fins_through_rings=True,
            ))

    elif assembly_type == "gear_train":
        gear_counts = [2, 3, 4, 3, 2, 4, 3, 2]
        for i in range(k):
            t = _t(i, k)
            gc = gear_counts[i % len(gear_counts)]
            mod = round(_lerp(1.0, 4.0, t), 1)
            base_teeth = int(_lerp(12, 40, t))
            # Alternate small/large teeth for reduction effect
            teeth = [base_teeth if j % 2 == 0 else min(80, base_teeth * 2) for j in range(gc)]
            teeth = [max(8, min(80, t_)) for t_ in teeth]
            specs.append(GearTrainSpec(
                reasoning="parametric sweep",
                gear_count=gc,
                teeth=teeth,
                module_val=mod,
                thickness=round(_lerp(4, 20, t), 1),
                bore_d=round(_lerp(3, 12, t), 1),
            ))

    elif assembly_type == "planetary_gear":
        planet_counts = [3, 4, 3, 5, 3, 4, 6, 3]
        for i in range(k):
            t = _t(i, k)
            sun = int(_lerp(12, 40, t))
            planet = int(_lerp(10, 30, t))
            # Ensure ring teeth <= 200
            while sun + 2 * planet > 200:
                planet -= 1
            specs.append(PlanetaryGearSpec(
                reasoning="parametric sweep",
                sun_teeth=max(8, sun),
                planet_teeth=max(8, planet),
                planet_count=planet_counts[i % len(planet_counts)],
                module_val=round(_lerp(1.0, 4.0, t), 1),
                thickness=round(_lerp(5, 20, t), 1),
                bore_d=round(_lerp(3, 12, t), 1),
                include_ring_gear=True,
            ))

    elif assembly_type == "bushing_assembly":
        for i in range(k):
            t = _t(i, k)
            bore = round(_lerp(5, 100, t), 1)
            outer = round(bore * _lerp(1.4, 1.8, t), 1)
            flange = i % 3 == 1
            flange_od = round(outer * 1.6, 1) if flange else None
            specs.append(BushingAssemblySpec(
                reasoning="parametric sweep",
                bore_d=bore,
                outer_d=outer,
                length=round(_lerp(15, 150, t), 1),
                flange=flange,
                flange_outer_d=flange_od,
                flange_thickness=4.0 if flange else None,
            ))

    elif assembly_type == "flanged_tube":
        bolt_counts = [4, 6, 8, 4, 6, 8, 4, 6]
        for i in range(k):
            t = _t(i, k)
            od = round(_lerp(25, 120, t), 1)
            wall = round(_lerp(2.5, 8, t), 1)
            id_ = round(od - 2 * wall, 1)
            flange_od = round(od * _lerp(1.8, 2.2, t), 1)
            bc = round((od + flange_od) / 2, 1)
            bc = max(od + 5, min(flange_od - 5, bc))
            bc = round(bc, 1)
            specs.append(FlangedTubeSpec(
                reasoning="parametric sweep",
                tube_outer_d=od,
                tube_inner_d=id_,
                tube_length=round(_lerp(60, 400, t), 1),
                flange_outer_d=flange_od,
                flange_thickness=round(_lerp(6, 15, t), 1),
                bolt_count=bolt_counts[i % len(bolt_counts)],
                bolt_circle_d=bc,
                bolt_hole_d=round(_lerp(8, 16, t), 1),
                flange_both_ends=i % 4 == 0,
            ))

    elif assembly_type == "rack_and_pinion":
        for i in range(k):
            t = _t(i, k)
            mod = round(_lerp(1.0, 4.0, t), 1)
            width = round(max(mod * 2 + 1, _lerp(8, 20, t)), 1)
            specs.append(RackAndPinionSpec(
                reasoning="parametric sweep",
                rack_length=round(_lerp(100, 600, t), 1),
                rack_width=width,
                rack_height=round(_lerp(8, 25, t), 1),
                module_val=mod,
                pinion_teeth=int(_lerp(12, 32, t)),
                pinion_thickness=round(_lerp(6, 20, t), 1),
                bore_d=round(_lerp(4, 12, t), 1),
            ))

    elif assembly_type == "worm_gear":
        starts_cycle = [1, 2, 1, 4, 2, 1, 3, 2]
        for i in range(k):
            t = _t(i, k)
            starts = starts_cycle[i % len(starts_cycle)]
            specs.append(WormGearSpec(
                reasoning="parametric sweep",
                worm_starts=starts,
                wheel_teeth=int(_lerp(20, 60, t)),
                module_val=round(_lerp(1.0, 4.0, t), 1),
                worm_length=round(_lerp(20, 80, t), 1),
                wheel_thickness=round(_lerp(6, 25, t), 1),
                bore_d=round(_lerp(4, 15, t), 1),
                worm_bore_d=round(_lerp(3, 12, t), 1),
            ))

    elif assembly_type == "helical_spring":
        types_cycle = ["compression", "extension", "torsion", "compression"]
        for i in range(k):
            t = _t(i, k)
            wire = round(_lerp(0.5, 5, t), 1)
            od = round(wire * _lerp(5, 12, t), 1)
            specs.append(HelicalSpringSpec(
                reasoning="parametric sweep",
                wire_d=wire,
                coil_od=od,
                free_length=round(_lerp(20, 200, t), 1),
                coil_count=round(_lerp(4, 20, t), 1),
                spring_type=types_cycle[i % len(types_cycle)],
            ))

    elif assembly_type == "shaft_coupling":
        for i in range(k):
            t = _t(i, k)
            d1 = round(_lerp(4, 30, t), 1)
            d2 = round(_lerp(4, 30, t), 1)
            od = round(max(d1, d2) * _lerp(1.6, 2.2, t), 1)
            length = round(_lerp(15, 80, t), 1)
            gap = 1.5
            if length <= gap:
                length = gap + 5
            specs.append(ShaftCouplingSpec(
                reasoning="parametric sweep",
                shaft_d1=d1,
                shaft_d2=d2,
                coupling_od=od,
                coupling_length=length,
                gap=gap,
            ))

    elif assembly_type == "hex_standoff":
        bore_sizes = [2, 3, 4, 5, 6, 8, 3, 4]
        for i in range(k):
            t = _t(i, k)
            bore = bore_sizes[i % len(bore_sizes)]
            af = round(max(bore * 1.6, _lerp(4, 13, t)), 1)
            male = i % 3 == 2
            specs.append(HexStandoffSpec(
                reasoning="parametric sweep",
                bore_d=bore,
                flat_to_flat=af,
                length=round(_lerp(5, 50, t), 1),
                male_stud=male,
                stud_d=round(bore * 0.9, 1) if male else 3.0,
                stud_length=round(_lerp(4, 12, t), 1),
            ))

    elif assembly_type == "four_bar_linkage":
        for i in range(k):
            t = _t(i, k)
            ground = round(_lerp(40, 200, t), 1)
            crank = round(_lerp(15, 80, t), 1)
            coupler = round(_lerp(30, 180, t), 1)
            rocker = round(_lerp(20, 120, t), 1)
            # Ensure Grashof closure: longest < sum of other three
            links = sorted([ground, crank, coupler, rocker])
            while links[3] >= links[0] + links[1] + links[2]:
                links[3] -= 5
            specs.append(FourBarLinkageSpec(
                reasoning="parametric sweep",
                ground_length=links[2],
                crank_length=links[0],
                coupler_length=links[1],
                rocker_length=links[3],
                link_width=round(_lerp(6, 18, t), 1),
                link_thickness=round(_lerp(3, 10, t), 1),
                pivot_d=round(_lerp(3, 10, t), 1),
                crank_angle=round(_lerp(15, 120, t), 1),
            ))

    elif assembly_type == "lead_screw":
        starts_cycle = [1, 1, 2, 1, 4, 2, 1, 2]
        for i in range(k):
            t = _t(i, k)
            starts = starts_cycle[i % len(starts_cycle)]
            screw_d = round(_lerp(6, 32, t), 1)
            specs.append(LeadScrewSpec(
                reasoning="parametric sweep",
                screw_length=round(_lerp(60, 400, t), 1),
                screw_diameter=screw_d,
                lead=round(_lerp(1, 16, t), 1),
                starts=starts,
                nut_od=round(screw_d * _lerp(1.6, 2.0, t), 1),
                nut_length=round(_lerp(10, 50, t), 1),
                bore_d=round(_lerp(2, 10, t), 1),
                ball_screw=i % 3 == 1,
                nut_position=round(_lerp(0.2, 0.8, t), 2),
            ))

    elif assembly_type == "cam_follower":
        profiles = ["eccentric", "pear", "heart", "eccentric"]
        for i in range(k):
            t = _t(i, k)
            base_r = round(_lerp(15, 80, t), 1)
            lift = round(_lerp(3, base_r * 0.6, t), 1)
            shaft = round(_lerp(4, base_r * 0.5, t), 1)
            specs.append(CamFollowerSpec(
                reasoning="parametric sweep",
                base_radius=base_r,
                lift=lift,
                cam_thickness=round(_lerp(5, 25, t), 1),
                follower_diameter=round(_lerp(6, 20, t), 1),
                follower_length=round(_lerp(30, 120, t), 1),
                shaft_d=shaft,
                cam_profile=profiles[i % len(profiles)],
            ))

    elif assembly_type == "universal_joint":
        for i in range(k):
            t = _t(i, k)
            shaft = round(_lerp(6, 30, t), 1)
            yoke_w = round(shaft * _lerp(2.5, 3.5, t), 1)
            specs.append(UniversalJointSpec(
                reasoning="parametric sweep",
                shaft_d=shaft,
                yoke_width=yoke_w,
                yoke_thickness=round(_lerp(4, 15, t), 1),
                cross_diameter=round(_lerp(3, yoke_w * 0.3, t), 1),
                cross_length=round(yoke_w * 0.8, 1),
                joint_angle=round(_lerp(10, 45, t), 1),
                shaft_length=round(_lerp(30, 120, t), 1),
                double_joint=i % 3 == 2,
            ))

    elif assembly_type == "belt_pulley":
        drive_types = ["belt", "chain", "belt", "belt"]
        for i in range(k):
            t = _t(i, k)
            driver_d = round(_lerp(30, 150, t), 1)
            driven_d = round(_lerp(40, 300, t), 1)
            min_cd = (driver_d + driven_d) / 2 + 10
            cd = round(max(min_cd, _lerp(80, 500, t)), 1)
            bore = round(_lerp(5, min(driver_d * 0.3, 30), t), 1)
            specs.append(BeltPulleySpec(
                reasoning="parametric sweep",
                driver_diameter=driver_d,
                driven_diameter=driven_d,
                center_distance=cd,
                belt_width=round(_lerp(6, 25, t), 1),
                belt_thickness=round(_lerp(1, 6, t), 1),
                pulley_thickness=round(_lerp(8, 30, t), 1),
                bore_d=bore,
                drive_type=drive_types[i % len(drive_types)],
            ))

    elif assembly_type == "differential_gear":
        spider_counts = [2, 2, 3, 4, 2, 3, 2, 4]
        for i in range(k):
            t = _t(i, k)
            ring_teeth = int(_lerp(30, 80, t))
            pinion_teeth = int(_lerp(10, 25, t))
            side_teeth = int(_lerp(12, 30, t))
            spider_teeth = int(_lerp(10, 25, t))
            specs.append(DifferentialGearSpec(
                reasoning="parametric sweep",
                ring_gear_teeth=ring_teeth,
                pinion_teeth=max(8, pinion_teeth),
                side_gear_teeth=max(10, side_teeth),
                spider_gear_teeth=max(8, spider_teeth),
                spider_count=spider_counts[i % len(spider_counts)],
                module_val=round(_lerp(1.0, 4.0, t), 1),
                thickness=round(_lerp(5, 20, t), 1),
                bore_d=round(_lerp(5, 20, t), 1),
                include_case=True,
            ))

    elif assembly_type == "bulkhead":
        from .models import BoltCircleSpec, CircularHoleSpec, RectSlotSpec
        for i in range(k):
            t = _t(i, k)
            od = round(_lerp(20, 100, t), 1)
            holes = []
            if i % 2 == 0:
                # Bolt circle of M3 holes near the outer edge
                holes.append(BoltCircleSpec(
                    bolt_count=int(_lerp(3, 8, t)),
                    bolt_circle_d=round(od - 8, 1),  # ~4mm from edge
                    bolt_hole_d=3.4,
                ))
            if i % 3 == 1:
                # Add a rectangular cable slot
                holes.append(RectSlotSpec(
                    width=round(_lerp(8, 20, t), 1),
                    height=round(_lerp(4, 10, t), 1),
                    corner_r=2,
                ))
            specs.append(BulkheadSpec(
                reasoning="parametric sweep",
                outer_d=od,
                thickness=round(_lerp(2, 8, t), 1),
                center_bore_d=round(od * 0.15, 1) if i % 2 == 1 else 0,
                shoulder_d=round(od * 0.85, 1) if i % 3 == 0 else 0,
                shoulder_length=3 if i % 3 == 0 else 0,
                holes=holes,
            ))

    elif assembly_type == "body_tube":
        from .models import CircularHoleSpec, RectSlotSpec, _BT_DIAMETERS
        bt_names = list(_BT_DIAMETERS.keys())
        for i in range(k):
            t = _t(i, k)
            bt = bt_names[i % len(bt_names)]
            tube_len = round(_lerp(50, 500, t), 1)
            holes = []
            if i % 2 == 1:
                # Vent hole on the side
                holes.append(CircularHoleSpec(
                    diameter=round(_lerp(3, 8, t), 1),
                    x=0,       # angle 0°
                    y=round(tube_len * 0.3, 1),
                ))
            if i % 3 == 2:
                holes.append(RectSlotSpec(
                    width=round(_lerp(6, 15, t), 1),
                    height=round(_lerp(3, 8, t), 1),
                    corner_r=1.5,
                    x=90,      # angle 90°
                    y=round(tube_len * 0.6, 1),
                ))
            specs.append(BodyTubeSpec(
                reasoning="parametric sweep",
                bt_designation=bt,
                length=tube_len,
                wall=round(_lerp(0.5, 2, t), 1),
                holes=holes,
            ))

    elif assembly_type == "mounting_plate":
        from .models import BoltCircleSpec, CircularHoleSpec, RectSlotSpec
        for i in range(k):
            t = _t(i, k)
            w = round(_lerp(30, 200, t), 1)
            d = round(_lerp(20, 150, t), 1)
            holes = []
            # Side-mounted M3 holes — on the long edges, spaced along Y
            edge_inset = 5
            y_spacing = round(d * 0.35, 1)
            for sx in [-1, 1]:
                for sy in [-1, 1]:
                    holes.append(CircularHoleSpec(
                        diameter=3.4,
                        x=round(sx * (w / 2 - edge_inset), 1),
                        y=round(sy * y_spacing, 1),
                    ))
            if i % 2 == 0:
                # Centre cable slot
                holes.append(RectSlotSpec(
                    width=round(_lerp(10, 30, t), 1),
                    height=round(_lerp(5, 15, t), 1),
                    corner_r=round(_lerp(1, 4, t), 1),
                ))
            specs.append(MountingPlateSpec(
                reasoning="parametric sweep",
                width=w,
                depth=d,
                thickness=round(_lerp(2, 8, t), 1),
                corner_r=round(_lerp(0, 8, t), 1),
                holes=holes,
            ))

    return specs
