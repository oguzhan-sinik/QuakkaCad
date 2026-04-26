"""Render pipeline: prompt → agent → spec → compose → .scad source."""

from __future__ import annotations

import asyncio
import logging
import math

from .agent import run_template_agent
from .assemblies import dispatch_compose
from .models import (
    AssemblySpec,
    BushingAssemblySpec,
    FinnedRocketBodySpec,
    FlangedTubeSpec,
    GearTrainSpec,
    HelicalSpringSpec,
    HexStandoffSpec,
    PlanetaryGearSpec,
    RackAndPinionSpec,
    ShaftCouplingSpec,
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

    return specs
