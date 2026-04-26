"""Thin wrapper around the MuBit SDK for OpenSCAD generation memory.

All functions are no-ops when MUBIT_API_KEY is not set, so the rest of the
codebase never needs to check for its presence.

The MuBit SDK is synchronous, so all calls are run in a thread pool to avoid
blocking the async event loop.  A short timeout prevents cold-start hangs.

SDK reference: https://docs.mubit.ai/sdk/sdk-methods
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_client: Any = None
_disabled = False

# Max seconds to wait for any single MuBit call (prevents first-call hang)
_TIMEOUT = 5

_AGENT_TEMPLATE = "template-classifier"

# One stable run_id for the shared template-library seed data.
# Using a fixed ID means re-seeding at startup is idempotent (MuBit deduplicates
# by content hash within a run, so repeated seeds don't bloat memory).
_TEMPLATE_LIBRARY_RUN_ID = "quakkacad:template-library:v1"

# Written after a successful seed to prevent re-seeding identical content on restart.
_SEED_HASH_FILE = Path(__file__).parent / ".mubit_seed.hash"


def _get_client() -> Any:
    """Lazily initialise the MuBit client.  Returns None if unavailable."""
    global _client, _disabled
    if _disabled:
        return None
    if _client is not None:
        return _client

    api_key = os.getenv("MUBIT_API_KEY", "")
    if not api_key:
        logger.info("MUBIT_API_KEY not set — MuBit integration disabled")
        _disabled = True
        return None

    try:
        from mubit import Client

        _client = Client()
        logger.info("MuBit client initialised")
        return _client
    except Exception as e:
        logger.warning("Failed to initialise MuBit client: %s", e)
        _disabled = True
        return None


async def _run_sync(fn, *args, timeout: float | None = None, **kwargs) -> Any:
    """Run a sync MuBit SDK call in a thread with timeout."""
    t = timeout if timeout is not None else _TIMEOUT
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, lambda: fn(*args, **kwargs)),
            timeout=t,
        )
    except asyncio.TimeoutError:
        logger.warning("MuBit call %s timed out after %ss", fn.__name__, t)
        return None
    except Exception as e:
        logger.warning("MuBit call %s failed: %s", fn.__name__, e)
        return None


# ---------------------------------------------------------------------------
# General helpers (used by generate / planner / openscad-meeting agents)
# ---------------------------------------------------------------------------
# Template library helpers
# ---------------------------------------------------------------------------


def _build_abstract_schema_items() -> list[dict]:
    """Return abstract parameter-schema descriptions for all 5 template types.

    These give the LLM structural knowledge: what each template does, its
    parameter names and ranges, and engineering constraints.
    """
    return [
        {
            "content": (
                "Template: finned_rocket_body\n"
                "Purpose: hollow cylindrical motor tube with trapezoidal fins and optional centering rings\n"
                "Parameters:\n"
                "  tube_outer_d (mm, 10-500): outer diameter of tube\n"
                "  tube_wall (mm, 0.5-20): tube wall thickness\n"
                "  tube_length (mm, 20-2000): axial length of tube\n"
                "  ring_count (0-4): number of centering rings\n"
                "  ring_width (mm, default 10): axial width of each ring\n"
                "  ring_radial_thickness (mm, default 4): radial thickness of ring material\n"
                "  ring_spacing (mm, optional): gap between rings; auto-computed if None\n"
                "  fin_count (0-8): number of fins\n"
                "  fin_root_chord (mm, default 80): fin root length along tube\n"
                "  fin_tip_chord (mm, default 30): fin tip length\n"
                "  fin_height (mm, default 60): fin span from tube surface\n"
                "  fin_sweep (mm, default 30): leading-edge sweep distance\n"
                "  fin_thickness (mm, default 2): fin thickness\n"
                "  fins_through_rings (bool, default True): cut slots in rings for fins\n"
                "Constraint: fin_root_chord <= tube_length\n"
                "Constraint: if ring_count>=2 and ring_spacing set, ring_spacing + ring_count*ring_width <= tube_length\n"
                "Typical use: model rocket bodies, high-power rockets, fin cans\n"
                "Keywords: rocket, fin, tube, motor mount, centering ring, fin can"
            ),
            "metadata": {"assembly_type": "finned_rocket_body", "kind": "template_spec"},
        },
        {
            "content": (
                "Template: gear_train\n"
                "Purpose: 2-6 meshing spur gears with correct center-distance spacing along X axis\n"
                "Parameters:\n"
                "  gear_count (2-6): number of gears in the train\n"
                "  teeth (list of ints, 8-80 each): tooth count per gear; length must equal gear_count\n"
                "  module_val (mm, 0.5-10): gear module — pitch diameter = module * teeth\n"
                "  thickness (mm, 1-50): gear face width\n"
                "  bore_d (mm, default 5): center bore diameter\n"
                "Center distance between adjacent gears: (teeth[i] + teeth[i+1]) * module_val / 2\n"
                "Meshing: odd-indexed gears rotate by half tooth pitch to interleave teeth\n"
                "Typical use: reduction drives, clock mechanisms, power transmission\n"
                "Keywords: gear, spur gear, reduction, gear train, transmission, mesh, teeth"
            ),
            "metadata": {"assembly_type": "gear_train", "kind": "template_spec"},
        },
        {
            "content": (
                "Template: planetary_gear\n"
                "Purpose: sun gear + N planet gears orbiting + optional outer ring gear (epicyclic)\n"
                "Parameters:\n"
                "  sun_teeth (8-60): sun gear tooth count\n"
                "  planet_teeth (8-60): planet gear tooth count\n"
                "  planet_count (2-6): number of planet gears\n"
                "  module_val (mm, 0.5-10): gear module\n"
                "  thickness (mm, 1-50): gear face width\n"
                "  bore_d (mm, default 5): center bore diameter\n"
                "  include_ring_gear (bool, default True): add outer ring gear\n"
                "Ring teeth auto-computed: sun_teeth + 2*planet_teeth (must be <= 200)\n"
                "Orbit radius: (sun_teeth + planet_teeth) * module_val / 2\n"
                "Typical use: compact inline reductions, power tools, bicycles, watch mechanisms\n"
                "Keywords: planetary, epicyclic, sun gear, planet gear, ring gear, carrier, reduction"
            ),
            "metadata": {"assembly_type": "planetary_gear", "kind": "template_spec"},
        },
        {
            "content": (
                "Template: bushing_assembly\n"
                "Purpose: cylindrical bushing or sleeve bearing with optional flange\n"
                "Parameters:\n"
                "  bore_d (mm, 1-200): inner bore diameter; must be < outer_d\n"
                "  outer_d (mm, 2-300): outer diameter\n"
                "  length (mm, 5-500): axial length of bushing\n"
                "  flange (bool, default False): add a flange at one end\n"
                "  flange_outer_d (mm, optional): flange OD; defaults to outer_d * 1.5\n"
                "  flange_thickness (mm, optional): flange thickness; defaults to 3mm\n"
                "Constraint: bore_d < outer_d\n"
                "Constraint: if flange=True, flange_outer_d > outer_d\n"
                "Typical use: pillow blocks, plain bearings, shaft guides, press-fit sleeves\n"
                "Keywords: bushing, bearing, sleeve, bore, shaft, press fit, flange"
            ),
            "metadata": {"assembly_type": "bushing_assembly", "kind": "template_spec"},
        },
        {
            "content": (
                "Template: flanged_tube\n"
                "Purpose: hollow tube with bolt-pattern flange(s) for pipe connections and pressure vessels\n"
                "Parameters:\n"
                "  tube_outer_d (mm, 5-500): tube outer diameter; must be < tube_inner_d by wall\n"
                "  tube_inner_d (mm, 1-500): tube inner diameter; must be < tube_outer_d\n"
                "  tube_length (mm, 10-2000): tube axial length\n"
                "  flange_outer_d (mm, 5-600): flange disc outer diameter; must be >= tube_outer_d\n"
                "  flange_thickness (mm, 1-50): flange disc thickness\n"
                "  bolt_count (3-24): number of bolt holes on bolt circle\n"
                "  bolt_circle_d (mm): bolt-hole circle diameter; must be > tube_outer_d and < flange_outer_d\n"
                "  bolt_hole_d (mm, default 5): bolt hole diameter\n"
                "  flange_both_ends (bool, default False): add flanges at both ends\n"
                "Constraint: tube_inner_d < tube_outer_d\n"
                "Constraint: flange_outer_d >= tube_outer_d\n"
                "Constraint: tube_outer_d < bolt_circle_d < flange_outer_d\n"
                "Typical use: pipe flanges, pressure vessels, exhaust flanges, manifolds\n"
                "Keywords: flange, pipe, tube, bolt pattern, pressure vessel, manifold, coupling"
            ),
            "metadata": {"assembly_type": "flanged_tube", "kind": "template_spec"},
        },
        {
            "content": (
                "Template: rack_and_pinion\n"
                "Purpose: flat toothed rack with meshing spur pinion for linear motion\n"
                "Parameters:\n"
                "  rack_length (mm, 50-1000): total rack length\n"
                "  rack_width (mm, 5-100): rack bar width\n"
                "  rack_height (mm, 5-100): rack base height (excluding teeth)\n"
                "  module_val (mm, 0.5-10): gear module\n"
                "  pinion_teeth (8-80): pinion tooth count\n"
                "  pinion_thickness (mm, 1-50): pinion face width\n"
                "  bore_d (mm, default 5): pinion bore diameter\n"
                "Constraint: rack_width >= 2 * module_val\n"
                "Linear travel per revolution = PI * module_val * pinion_teeth\n"
                "Typical use: CNC gantries, drawers, steering racks, linear actuators\n"
                "Keywords: rack, pinion, linear motion, CNC, gantry, lead screw alternative"
            ),
            "metadata": {"assembly_type": "rack_and_pinion", "kind": "template_spec"},
        },
        {
            "content": (
                "Template: worm_gear\n"
                "Purpose: helical worm shaft meshing with spur worm wheel at 90 degrees\n"
                "Parameters:\n"
                "  worm_starts (1-4): number of thread starts\n"
                "  wheel_teeth (8-80): worm wheel tooth count\n"
                "  module_val (mm, 0.5-10): gear module\n"
                "  worm_length (mm, 10-200): worm shaft axial length\n"
                "  wheel_thickness (mm, 1-50): wheel face width\n"
                "  bore_d (mm, default 5): wheel bore diameter\n"
                "  worm_bore_d (mm, default 5): worm shaft bore diameter\n"
                "Ratio = wheel_teeth / worm_starts (self-locking when ratio > ~20:1)\n"
                "Typical use: lifts, valve actuators, rotary stages, high-reduction drives\n"
                "Keywords: worm gear, worm drive, self-locking, reduction, lifts, actuator"
            ),
            "metadata": {"assembly_type": "worm_gear", "kind": "template_spec"},
        },
        {
            "content": (
                "Template: helical_spring\n"
                "Purpose: parametric helical spring — compression, extension, or torsion\n"
                "Parameters:\n"
                "  wire_d (mm, 0.3-20): wire diameter\n"
                "  coil_od (mm, 2-200): coil outer diameter\n"
                "  free_length (mm, 5-500): unloaded spring length\n"
                "  coil_count (1-50): number of active coils\n"
                "  spring_type: 'compression' | 'extension' | 'torsion'\n"
                "Constraint: coil_od > 2 * wire_d\n"
                "Pitch = free_length / coil_count  |  Coil ID = coil_od - 2*wire_d\n"
                "Typical use: suspension, return mechanisms, valve springs, energy storage\n"
                "Keywords: spring, coil spring, compression spring, extension spring, torsion"
            ),
            "metadata": {"assembly_type": "helical_spring", "kind": "template_spec"},
        },
        {
            "content": (
                "Template: shaft_coupling\n"
                "Purpose: rigid two-piece coupling connecting two shafts end-to-end\n"
                "Parameters:\n"
                "  shaft_d1 (mm, 1-100): first shaft bore diameter\n"
                "  shaft_d2 (mm, 1-100): second shaft bore diameter\n"
                "  coupling_od (mm, 3-200): coupling outer diameter\n"
                "  coupling_length (mm, 5-300): total coupling body length\n"
                "  gap (mm, default 1.5): gap between the two halves\n"
                "Constraint: coupling_od >= 1.5 * max(shaft_d1, shaft_d2)\n"
                "Constraint: coupling_length > gap\n"
                "Typical use: motor-to-shaft, leadscrew connections, drive train assembly\n"
                "Keywords: coupling, shaft coupling, rigid coupling, motor mount, jaw coupling"
            ),
            "metadata": {"assembly_type": "shaft_coupling", "kind": "template_spec"},
        },
        {
            "content": (
                "Template: hex_standoff\n"
                "Purpose: hex-body standoff/spacer with optional male threaded stud\n"
                "Parameters:\n"
                "  bore_d (mm, 1-30): bore / thread diameter\n"
                "  flat_to_flat (mm, 3-50): hex flat-to-flat (AF) distance\n"
                "  length (mm, 3-200): standoff body length\n"
                "  male_stud (bool, default False): add male stud at one end\n"
                "  stud_d (mm, default 3): male stud outer diameter\n"
                "  stud_length (mm, default 6): male stud length\n"
                "Constraint: flat_to_flat >= 1.5 * bore_d\n"
                "Constraint: if male_stud=True, stud_d < flat_to_flat\n"
                "Typical use: PCB mounting, frame spacers, pillar nuts, panel standoffs\n"
                "Keywords: standoff, spacer, hex standoff, PCB mount, pillar, M3 M4 M5"
            ),
            "metadata": {"assembly_type": "hex_standoff", "kind": "template_spec"},
        },
    ]


def _build_concrete_example_items() -> list[dict]:
    """Return 20 concrete engineering-realistic parameter examples (4 per template type).

    These anchor the LLM to real numeric values: hobby/medium/industrial/variant
    scales covering the most common use cases. Seeded alongside the abstract
    schemas so recall() returns both structural knowledge and numeric anchors.
    """
    return [
        # ── finned_rocket_body ───────────────────────────────────────────────
        {
            "content": (
                "Concrete example: finned_rocket_body — 29mm hobby motor tube\n"
                "Parameters used: tube_outer_d=29, tube_wall=1.5, tube_length=150, "
                "ring_count=0, fin_count=3, fin_root_chord=40, fin_tip_chord=15, "
                "fin_height=30, fin_sweep=15, fin_thickness=2, fins_through_rings=false\n"
                "Engineering notes: Estes-class 3-fin delta; no rings needed for short motor tube; "
                "fin_root_chord(40) well within tube_length(150)"
            ),
            "metadata": {"assembly_type": "finned_rocket_body", "kind": "concrete_example", "scale": "hobby"},
        },
        {
            "content": (
                "Concrete example: finned_rocket_body — 54mm mid-power with centering rings\n"
                "Parameters used: tube_outer_d=54, tube_wall=2.5, tube_length=300, "
                "ring_count=2, ring_width=12, ring_radial_thickness=5, ring_spacing=None, "
                "fin_count=4, fin_root_chord=80, fin_tip_chord=30, fin_height=60, "
                "fin_sweep=25, fin_thickness=3, fins_through_rings=true\n"
                "Engineering notes: Aerotech 54mm, through-the-wall fins require ring slots; "
                "ring_spacing=None auto-distributes 2 rings over 300mm tube"
            ),
            "metadata": {"assembly_type": "finned_rocket_body", "kind": "concrete_example", "scale": "medium"},
        },
        {
            "content": (
                "Concrete example: finned_rocket_body — 98mm high-power L2/L3 rocket\n"
                "Parameters used: tube_outer_d=98, tube_wall=4, tube_length=600, "
                "ring_count=4, ring_width=20, ring_radial_thickness=8, ring_spacing=None, "
                "fin_count=4, fin_root_chord=120, fin_tip_chord=50, fin_height=90, "
                "fin_sweep=40, fin_thickness=5, fins_through_rings=true\n"
                "Engineering notes: 4 rings for heavy 98mm motor; thick 4mm wall for structural load; "
                "fin_root_chord(120) << tube_length(600)"
            ),
            "metadata": {"assembly_type": "finned_rocket_body", "kind": "concrete_example", "scale": "industrial"},
        },
        {
            "content": (
                "Concrete example: finned_rocket_body — 75mm detachable fin can, swept fins\n"
                "Parameters used: tube_outer_d=75, tube_wall=3, tube_length=200, "
                "ring_count=0, fin_count=3, fin_root_chord=100, fin_tip_chord=20, "
                "fin_height=80, fin_sweep=60, fin_thickness=4, fins_through_rings=false\n"
                "Engineering notes: Detachable fin section only; high sweep(60) for aerodynamic profile; "
                "no rings since fins are structural"
            ),
            "metadata": {"assembly_type": "finned_rocket_body", "kind": "concrete_example", "scale": "variant"},
        },
        # ── gear_train ───────────────────────────────────────────────────────
        {
            "content": (
                "Concrete example: gear_train — 2-gear 1:2 reduction, clock mechanism\n"
                "Parameters used: gear_count=2, teeth=[20, 40], module_val=2.0, thickness=5, bore_d=4\n"
                "Engineering notes: pitch diameters 40mm + 80mm; center distance 60mm; "
                "output shaft rotates at half input speed; typical clock or timer mechanism"
            ),
            "metadata": {"assembly_type": "gear_train", "kind": "concrete_example", "scale": "hobby"},
        },
        {
            "content": (
                "Concrete example: gear_train — 3-gear robotics arm drive\n"
                "Parameters used: gear_count=3, teeth=[12, 36, 20], module_val=1.5, thickness=8, bore_d=5\n"
                "Engineering notes: first stage 3:1 reduction, idler reverses direction; "
                "module 1.5 balances tooth strength vs compactness for servo output shafts"
            ),
            "metadata": {"assembly_type": "gear_train", "kind": "concrete_example", "scale": "medium"},
        },
        {
            "content": (
                "Concrete example: gear_train — 4-gear 3D printer extruder gearbox\n"
                "Parameters used: gear_count=4, teeth=[10, 40, 10, 40], module_val=1.0, thickness=10, bore_d=4\n"
                "Engineering notes: compound 16:1 reduction using two identical stages; "
                "module 1.0 for fine pitch in compact housing; thick face for filament torque loads"
            ),
            "metadata": {"assembly_type": "gear_train", "kind": "concrete_example", "scale": "medium"},
        },
        {
            "content": (
                "Concrete example: gear_train — 6-gear industrial power transmission\n"
                "Parameters used: gear_count=6, teeth=[20, 30, 25, 35, 20, 40], module_val=3.0, thickness=20, bore_d=10\n"
                "Engineering notes: module 3.0 for heavy load capacity; 20mm face width for wide contact; "
                "multi-stage train for high-ratio output in industrial gearbox"
            ),
            "metadata": {"assembly_type": "gear_train", "kind": "concrete_example", "scale": "industrial"},
        },
        # ── planetary_gear ───────────────────────────────────────────────────
        {
            "content": (
                "Concrete example: planetary_gear — compact 3-planet inline reduction\n"
                "Parameters used: sun_teeth=12, planet_teeth=18, planet_count=3, "
                "module_val=1.5, thickness=8, bore_d=6, include_ring_gear=true\n"
                "Engineering notes: ring_teeth=48; orbit_radius=22.5mm; 3 planets for balanced load; "
                "suitable for bicycle derailleur or small gearmotor"
            ),
            "metadata": {"assembly_type": "planetary_gear", "kind": "concrete_example", "scale": "hobby"},
        },
        {
            "content": (
                "Concrete example: planetary_gear — 4-planet power tool gearbox\n"
                "Parameters used: sun_teeth=20, planet_teeth=15, planet_count=4, "
                "module_val=2.0, thickness=15, bore_d=8, include_ring_gear=true\n"
                "Engineering notes: ring_teeth=50; 4 planets distribute torque evenly for drill/impact; "
                "module 2.0 for robust tooth contact under high cyclical load"
            ),
            "metadata": {"assembly_type": "planetary_gear", "kind": "concrete_example", "scale": "medium"},
        },
        {
            "content": (
                "Concrete example: planetary_gear — 3-planet, no ring gear (external ring fixed)\n"
                "Parameters used: sun_teeth=30, planet_teeth=20, planet_count=3, "
                "module_val=2.5, thickness=20, bore_d=10, include_ring_gear=false\n"
                "Engineering notes: ring_teeth=70 (external constraint); carrier provides output; "
                "useful when ring gear is part of housing rather than a separate printed part"
            ),
            "metadata": {"assembly_type": "planetary_gear", "kind": "concrete_example", "scale": "industrial"},
        },
        {
            "content": (
                "Concrete example: planetary_gear — 6-planet fine-pitch precision mechanism\n"
                "Parameters used: sun_teeth=18, planet_teeth=12, planet_count=6, "
                "module_val=1.0, thickness=6, bore_d=4, include_ring_gear=true\n"
                "Engineering notes: ring_teeth=42; 6 planets maximise tooth contact for smooth low-backlash output; "
                "module 1.0 for watch-scale or instrument mechanism"
            ),
            "metadata": {"assembly_type": "planetary_gear", "kind": "concrete_example", "scale": "variant"},
        },
        # ── bushing_assembly ─────────────────────────────────────────────────
        {
            "content": (
                "Concrete example: bushing_assembly — 8mm bore press-fit sleeve\n"
                "Parameters used: bore_d=8, outer_d=14, length=20, flange=false\n"
                "Engineering notes: 3mm wall; drop-in 608-bearing substitute; "
                "no flange needed for through-hole press fit in printed bracket"
            ),
            "metadata": {"assembly_type": "bushing_assembly", "kind": "concrete_example", "scale": "hobby"},
        },
        {
            "content": (
                "Concrete example: bushing_assembly — 20mm flanged motor mount bushing\n"
                "Parameters used: bore_d=20, outer_d=30, length=40, flange=true, "
                "flange_outer_d=50, flange_thickness=4\n"
                "Engineering notes: 5mm wall for NEMA 23 shaft guide; flange retains against housing face; "
                "flange_outer_d(50) > outer_d(30) constraint satisfied"
            ),
            "metadata": {"assembly_type": "bushing_assembly", "kind": "concrete_example", "scale": "medium"},
        },
        {
            "content": (
                "Concrete example: bushing_assembly — 50mm industrial conveyor sleeve\n"
                "Parameters used: bore_d=50, outer_d=70, length=100, flange=false\n"
                "Engineering notes: 10mm wall for heavy radial load; 100mm length for wide belt idler; "
                "bronze-substitute for lubricated running fit"
            ),
            "metadata": {"assembly_type": "bushing_assembly", "kind": "concrete_example", "scale": "industrial"},
        },
        {
            "content": (
                "Concrete example: bushing_assembly — 5mm RC miniature flanged bushing\n"
                "Parameters used: bore_d=5, outer_d=9, length=12, flange=true, "
                "flange_outer_d=16, flange_thickness=3\n"
                "Engineering notes: 2mm wall; flanged retention for RC car wheel hub; "
                "compact 12mm length to fit within chassis clearance"
            ),
            "metadata": {"assembly_type": "bushing_assembly", "kind": "concrete_example", "scale": "variant"},
        },
        # ── flanged_tube ─────────────────────────────────────────────────────
        {
            "content": (
                "Concrete example: flanged_tube — DN25 single-end pipe flange\n"
                "Parameters used: tube_outer_d=33.4, tube_inner_d=26.6, tube_length=100, "
                "flange_outer_d=65, flange_thickness=8, bolt_count=4, "
                "bolt_circle_d=50, bolt_hole_d=14, flange_both_ends=false\n"
                "Engineering notes: 1-inch nominal pipe wall 3.4mm; ANSI 150# 4-bolt pattern; "
                "bolt_circle_d(50) is between tube_outer_d(33.4) and flange_outer_d(65)"
            ),
            "metadata": {"assembly_type": "flanged_tube", "kind": "concrete_example", "scale": "hobby"},
        },
        {
            "content": (
                "Concrete example: flanged_tube — DN50 spool piece, flanges both ends\n"
                "Parameters used: tube_outer_d=60.3, tube_inner_d=52.5, tube_length=200, "
                "flange_outer_d=120, flange_thickness=10, bolt_count=8, "
                "bolt_circle_d=95, bolt_hole_d=16, flange_both_ends=true\n"
                "Engineering notes: 2-inch pipe 3.9mm wall; 8-bolt for higher pressure rating; "
                "200mm spool for instrumentation tap between two flanges"
            ),
            "metadata": {"assembly_type": "flanged_tube", "kind": "concrete_example", "scale": "medium"},
        },
        {
            "content": (
                "Concrete example: flanged_tube — 100mm exhaust manifold coupling\n"
                "Parameters used: tube_outer_d=100, tube_inner_d=90, tube_length=80, "
                "flange_outer_d=160, flange_thickness=12, bolt_count=6, "
                "bolt_circle_d=130, bolt_hole_d=12, flange_both_ends=false\n"
                "Engineering notes: ISO 9624 6-bolt pattern; 12mm wall for thermal cycling; "
                "80mm short stub to connect exhaust section to turbo outlet"
            ),
            "metadata": {"assembly_type": "flanged_tube", "kind": "concrete_example", "scale": "industrial"},
        },
        {
            "content": (
                "Concrete example: flanged_tube — 25mm high-pressure vessel nozzle stub\n"
                "Parameters used: tube_outer_d=25, tube_inner_d=19, tube_length=60, "
                "flange_outer_d=55, flange_thickness=15, bolt_count=8, "
                "bolt_circle_d=42, bolt_hole_d=8, flange_both_ends=false\n"
                "Engineering notes: 3mm wall; close 8-bolt pattern for high working pressure; "
                "15mm thick flange to maintain gasket seating stress under pressure cycling"
            ),
            "metadata": {"assembly_type": "flanged_tube", "kind": "concrete_example", "scale": "variant"},
        },
        # ── rack_and_pinion ──────────────────────────────────────────────────
        {
            "content": (
                "Concrete example: rack_and_pinion — 300mm CNC gantry rack, module 2\n"
                "Parameters used: rack_length=300, rack_width=10, rack_height=12, "
                "module_val=2.0, pinion_teeth=20, pinion_thickness=10, bore_d=5\n"
                "Engineering notes: module 2 for adequate tooth strength at stepper torques; "
                "travel per rev = PI*2*20 = 125.7mm; 300mm rack gives 2.4 revolutions full traverse"
            ),
            "metadata": {"assembly_type": "rack_and_pinion", "kind": "concrete_example", "scale": "medium"},
        },
        {
            "content": (
                "Concrete example: rack_and_pinion — 600mm linear slide, module 3\n"
                "Parameters used: rack_length=600, rack_width=15, rack_height=20, "
                "module_val=3.0, pinion_teeth=16, pinion_thickness=15, bore_d=8\n"
                "Engineering notes: heavy-duty module 3 for industrial load; "
                "travel per rev = 150.8mm; 16-tooth pinion keeps pitch radius compact at 24mm"
            ),
            "metadata": {"assembly_type": "rack_and_pinion", "kind": "concrete_example", "scale": "industrial"},
        },
        {
            "content": (
                "Concrete example: rack_and_pinion — 150mm desk drawer, module 1.5\n"
                "Parameters used: rack_length=150, rack_width=8, rack_height=8, "
                "module_val=1.5, pinion_teeth=12, pinion_thickness=6, bore_d=4\n"
                "Engineering notes: fine module 1.5 for quiet smooth operation; "
                "travel per rev = 56.5mm; 150mm rack gives 2.65 revolutions full travel"
            ),
            "metadata": {"assembly_type": "rack_and_pinion", "kind": "concrete_example", "scale": "hobby"},
        },
        {
            "content": (
                "Concrete example: rack_and_pinion — 200mm steering rack, module 2.5, large pinion\n"
                "Parameters used: rack_length=200, rack_width=12, rack_height=15, "
                "module_val=2.5, pinion_teeth=28, pinion_thickness=12, bore_d=8\n"
                "Engineering notes: large 28-tooth pinion for sensitive steering (high mm/rev); "
                "travel per rev = 219.9mm; nearly 1:1 on short rack for full lock-to-lock"
            ),
            "metadata": {"assembly_type": "rack_and_pinion", "kind": "concrete_example", "scale": "variant"},
        },
        # ── worm_gear ────────────────────────────────────────────────────────
        {
            "content": (
                "Concrete example: worm_gear — 40:1 single-start valve actuator\n"
                "Parameters used: worm_starts=1, wheel_teeth=40, module_val=2.0, "
                "worm_length=50, wheel_thickness=12, bore_d=6, worm_bore_d=5\n"
                "Engineering notes: 40:1 self-locking ratio; module 2 for moderate torque; "
                "worm_length=50 accommodates 25 full turns; used in gate valve positioners"
            ),
            "metadata": {"assembly_type": "worm_gear", "kind": "concrete_example", "scale": "medium"},
        },
        {
            "content": (
                "Concrete example: worm_gear — 20:1 lift drive, 2-start\n"
                "Parameters used: worm_starts=2, wheel_teeth=40, module_val=3.0, "
                "worm_length=60, wheel_thickness=20, bore_d=10, worm_bore_d=8\n"
                "Engineering notes: 2-start doubles efficiency vs 1-start at same ratio; "
                "module 3 for heavy load; thick 20mm wheel face for sustained axial thrust"
            ),
            "metadata": {"assembly_type": "worm_gear", "kind": "concrete_example", "scale": "industrial"},
        },
        {
            "content": (
                "Concrete example: worm_gear — 10:1 camera pan drive, 4-start\n"
                "Parameters used: worm_starts=4, wheel_teeth=40, module_val=1.0, "
                "worm_length=25, wheel_thickness=6, bore_d=4, worm_bore_d=3\n"
                "Engineering notes: 4-start not self-locking (good for back-driveable pan head); "
                "fine module 1.0 for quiet low-backlash operation"
            ),
            "metadata": {"assembly_type": "worm_gear", "kind": "concrete_example", "scale": "hobby"},
        },
        {
            "content": (
                "Concrete example: worm_gear — 15:1 rotary stage, 3-start\n"
                "Parameters used: worm_starts=3, wheel_teeth=45, module_val=1.5, "
                "worm_length=35, wheel_thickness=10, bore_d=6, worm_bore_d=5\n"
                "Engineering notes: 15:1 border of self-lock; module 1.5 for precision positioning; "
                "45-tooth wheel gives fine angular resolution with stepper"
            ),
            "metadata": {"assembly_type": "worm_gear", "kind": "concrete_example", "scale": "variant"},
        },
        # ── helical_spring ───────────────────────────────────────────────────
        {
            "content": (
                "Concrete example: helical_spring — light return spring, compression\n"
                "Parameters used: wire_d=0.8, coil_od=8, free_length=30, coil_count=10, "
                "spring_type=compression\n"
                "Engineering notes: index ratio (OD/wire_d) = 10, well within 4-12 optimal range; "
                "pitch = 3mm; typical ballpoint pen or small switch return spring"
            ),
            "metadata": {"assembly_type": "helical_spring", "kind": "concrete_example", "scale": "hobby"},
        },
        {
            "content": (
                "Concrete example: helical_spring — suspension spring, compression\n"
                "Parameters used: wire_d=4, coil_od=40, free_length=150, coil_count=8, "
                "spring_type=compression\n"
                "Engineering notes: index ratio = 10; pitch = 18.75mm; "
                "suitable for bicycle suspension or light vehicle spring; high energy storage"
            ),
            "metadata": {"assembly_type": "helical_spring", "kind": "concrete_example", "scale": "industrial"},
        },
        {
            "content": (
                "Concrete example: helical_spring — tension spring, extension\n"
                "Parameters used: wire_d=1.5, coil_od=15, free_length=60, coil_count=20, "
                "spring_type=extension\n"
                "Engineering notes: tightly wound (coil_count=20, length=60 → pitch=3mm); "
                "extension springs have initial tension; used in door closers and return mechanisms"
            ),
            "metadata": {"assembly_type": "helical_spring", "kind": "concrete_example", "scale": "medium"},
        },
        {
            "content": (
                "Concrete example: helical_spring — torsion spring for hinge\n"
                "Parameters used: wire_d=2, coil_od=20, free_length=40, coil_count=6, "
                "spring_type=torsion\n"
                "Engineering notes: fewer coils = stiffer angular spring; "
                "40mm free length with 6 active coils gives good angular deflection for hinge arms"
            ),
            "metadata": {"assembly_type": "helical_spring", "kind": "concrete_example", "scale": "variant"},
        },
        # ── shaft_coupling ───────────────────────────────────────────────────
        {
            "content": (
                "Concrete example: shaft_coupling — M3 hobbyist motor-to-shaft, 6mm bores\n"
                "Parameters used: shaft_d1=6, shaft_d2=6, coupling_od=12, "
                "coupling_length=20, gap=1.5\n"
                "Engineering notes: 3mm wall each side; gap=1.5 for slight misalignment flex; "
                "typical 775 motor to 6mm shaft on RC/robotic chassis"
            ),
            "metadata": {"assembly_type": "shaft_coupling", "kind": "concrete_example", "scale": "hobby"},
        },
        {
            "content": (
                "Concrete example: shaft_coupling — NEMA 23 stepper to 10mm leadscrew\n"
                "Parameters used: shaft_d1=6.35, shaft_d2=10, coupling_od=20, "
                "coupling_length=35, gap=2\n"
                "Engineering notes: 6.35mm (1/4\") NEMA 23 output to 10mm leadscrew; "
                "mismatched bores common in CNC; 20mm OD gives 4.8mm wall on larger bore side"
            ),
            "metadata": {"assembly_type": "shaft_coupling", "kind": "concrete_example", "scale": "medium"},
        },
        {
            "content": (
                "Concrete example: shaft_coupling — industrial motor coupling, 30mm shafts\n"
                "Parameters used: shaft_d1=30, shaft_d2=30, coupling_od=55, "
                "coupling_length=70, gap=3\n"
                "Engineering notes: 12.5mm wall thickness for high-torque pump coupling; "
                "70mm length provides good set-screw spread; gap=3mm standard industrial clearance"
            ),
            "metadata": {"assembly_type": "shaft_coupling", "kind": "concrete_example", "scale": "industrial"},
        },
        {
            "content": (
                "Concrete example: shaft_coupling — encoder coupling, different bores\n"
                "Parameters used: shaft_d1=5, shaft_d2=8, coupling_od=16, "
                "coupling_length=25, gap=1\n"
                "Engineering notes: encoder shaft (5mm) to motor shaft (8mm); "
                "tight 1mm gap for encoders where axial float causes measurement error"
            ),
            "metadata": {"assembly_type": "shaft_coupling", "kind": "concrete_example", "scale": "variant"},
        },
        # ── hex_standoff ─────────────────────────────────────────────────────
        {
            "content": (
                "Concrete example: hex_standoff — M3 PCB standoff 10mm\n"
                "Parameters used: bore_d=3, flat_to_flat=5.5, length=10, "
                "male_stud=false, stud_d=3, stud_length=6\n"
                "Engineering notes: standard M3 AF=5.5mm (DIN 934); 10mm stacks PCBs 10mm apart; "
                "F-F through bore for bolt-through mounting"
            ),
            "metadata": {"assembly_type": "hex_standoff", "kind": "concrete_example", "scale": "hobby"},
        },
        {
            "content": (
                "Concrete example: hex_standoff — M4 panel standoff 20mm with male stud\n"
                "Parameters used: bore_d=4, flat_to_flat=7, length=20, "
                "male_stud=true, stud_d=4, stud_length=8\n"
                "Engineering notes: M-F standoff; male stud screws into panel, "
                "female bore accepts PCB bolt; common in panel-mount electronics enclosures"
            ),
            "metadata": {"assembly_type": "hex_standoff", "kind": "concrete_example", "scale": "medium"},
        },
        {
            "content": (
                "Concrete example: hex_standoff — M6 industrial pillar 50mm\n"
                "Parameters used: bore_d=6, flat_to_flat=10, length=50, "
                "male_stud=false, stud_d=6, stud_length=10\n"
                "Engineering notes: M6 AF=10mm (DIN 934); 50mm pillars for control panel spacing; "
                "thick hex body withstands wrench torque in vibrating machinery"
            ),
            "metadata": {"assembly_type": "hex_standoff", "kind": "concrete_example", "scale": "industrial"},
        },
        {
            "content": (
                "Concrete example: hex_standoff — M5 stacked standoff, male stud both used\n"
                "Parameters used: bore_d=5, flat_to_flat=8, length=15, "
                "male_stud=true, stud_d=5, stud_length=10\n"
                "Engineering notes: M-F standoff stackable design; stud_length=10 allows stacking "
                "additional identical standoffs for taller column; common in HAT/shield stacking"
            ),
            "metadata": {"assembly_type": "hex_standoff", "kind": "concrete_example", "scale": "variant"},
        },
    ]


def _seed_content_hash(items: list[dict]) -> str:
    combined = "".join(item["content"] for item in items)
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


async def seed_template_library() -> None:
    """Seed MuBit with canonical template knowledge.

    Called once at startup. A content hash written to .mubit_seed.hash prevents
    re-seeding identical content on every restart — MuBit does not deduplicate
    across calls so repeated seeding accumulates duplicate nodes. The hash file
    is only written after all items succeed; a partial seed retries on next boot.
    """
    client = _get_client()
    if client is None:
        return

    all_items = _build_abstract_schema_items() + _build_concrete_example_items()
    current_hash = _seed_content_hash(all_items)

    if _SEED_HASH_FILE.exists() and _SEED_HASH_FILE.read_text().strip() == current_hash:
        logger.info("MuBit template library already seeded (hash %s), skipping", current_hash)
        return

    logger.info("Seeding %d items into MuBit template library (hash %s)…", len(all_items), current_hash)

    # Limit concurrency to 5 to avoid overwhelming MuBit on cold-start.
    # Use a longer per-call timeout since seeding is non-blocking background work.
    _SEED_TIMEOUT = 20.0
    _SEED_CONCURRENCY = 5
    sem = asyncio.Semaphore(_SEED_CONCURRENCY)

    async def _seed_one(item: dict) -> Any:
        async with sem:
            return await _run_sync(
                client.remember,
                session_id=_TEMPLATE_LIBRARY_RUN_ID,
                agent_id=_AGENT_TEMPLATE,
                content=item["content"],
                intent="fact",
                metadata=item["metadata"],
                timeout=_SEED_TIMEOUT,
            )

    results = await asyncio.gather(*[_seed_one(item) for item in all_items], return_exceptions=True)

    # _run_sync returns None on timeout/error, not an Exception — count both.
    failures = sum(1 for r in results if r is None or isinstance(r, Exception))
    if failures == 0:
        _SEED_HASH_FILE.write_text(current_hash)
        logger.info("MuBit template library seeded (%d items, hash %s)", len(all_items), current_hash)
    else:
        logger.warning(
            "MuBit seed: %d/%d items failed — hash file not written, will retry on next startup",
            failures, len(all_items),
        )


async def get_template_context(user_prompt: str) -> str:
    """Retrieve template library context relevant to a user prompt via recall().

    Uses recall() (semantic search + synthesis) rather than get_context(), which
    returns an empty context_block in practice. Evidence content is joined into
    a plain-text block for injection into the LLM prompt.

    Returns an empty string if MuBit is unavailable (graceful degradation).
    """
    client = _get_client()
    if client is None:
        return ""

    try:
        result = await _run_sync(
            client.recall,
            session_id=_TEMPLATE_LIBRARY_RUN_ID,
            query=user_prompt,
        )
        if not result:
            logger.debug("MuBit template context empty")
            return ""

        parts = []

        # Synthesised answer from MuBit (short summary)
        final_answer = result.get("final_answer", "").strip()
        if final_answer:
            parts.append(f"Summary: {final_answer}")

        # Full content of each evidence item (facts, lessons, traces)
        for ev in result.get("evidence") or []:
            content = (ev.get("content") or "").strip()
            entry_type = ev.get("entry_type", "")
            if content and entry_type in ("fact", "lesson", "trace"):
                parts.append(content)

        text = "\n\n".join(parts)
        if text:
            logger.info("MuBit template context retrieved (%d chars, %d evidence items)",
                        len(text), len(result.get("evidence") or []))
        else:
            logger.debug("MuBit template context empty")
        return text
    except Exception as e:
        logger.warning("MuBit get_template_context failed: %s", e)
        return ""


async def remember_template_generation(
    prompt: str,
    assembly_type: str,
    scad_length: int,
    model_used: str,
) -> None:
    """Record a template classification + SCAD generation into the shared library session.

    Always writes to _TEMPLATE_LIBRARY_RUN_ID so traces accumulate in the same
    session that get_template_context() queries, enabling cross-request learning.
    """
    client = _get_client()
    if client is None:
        return

    try:
        content = (
            f"Template generation: {assembly_type}\n"
            f"Prompt: {prompt[:400]}\n"
            f"Model: {model_used}\n"
            f"SCAD output: {scad_length} chars"
        )
        await _run_sync(
            client.remember,
            session_id=_TEMPLATE_LIBRARY_RUN_ID,
            agent_id=_AGENT_TEMPLATE,
            content=content,
            intent="trace",
            metadata={
                "assembly_type": assembly_type,
                "model": model_used,
                "scad_length": scad_length,
            },
        )
        logger.info("MuBit memory saved: template generation assembly=%s scad_length=%d", assembly_type, scad_length)
    except Exception as e:
        logger.warning("MuBit template remember failed: %s", e)


async def record_template_outcome(
    assembly_type: str,
    success: bool,
    error_msg: str | None = None,
) -> None:
    """Record WASM compilation outcome into the shared library session.

    Always uses _TEMPLATE_LIBRARY_RUN_ID so reinforcement signals accumulate
    alongside the traces and seed facts that get_template_context() retrieves.
    MuBit's run→session→global promotion then surfaces lessons to future requests.
    """
    client = _get_client()
    if client is None:
        return

    try:
        reflection = await _run_sync(
            client.reflect,
            session_id=_TEMPLATE_LIBRARY_RUN_ID,
        )
        if not reflection:
            return

        lessons = reflection.get("lessons") or []
        logger.info("MuBit reflect: %d lesson(s) extracted for template library", len(lessons))
        lesson_id = next(
            (l.get("lesson_id") for l in lessons if l.get("lesson_id")),
            None,
        )
        if not lesson_id:
            logger.debug("MuBit reflect: no lesson_id found, skipping record_outcome")
            return

        outcome = "success" if success else "failure"
        signal = 1.0 if success else 0.0
        rationale = (
            f"Template {assembly_type}: WASM compilation succeeded"
            if success
            else f"Template {assembly_type}: WASM compilation failed: {error_msg or 'unknown'}"
        )

        await _run_sync(
            client.record_outcome,
            session_id=_TEMPLATE_LIBRARY_RUN_ID,
            agent_id=_AGENT_TEMPLATE,
            reference_id=lesson_id,
            outcome=outcome,
            signal=signal,
            rationale=rationale,
        )
        logger.info("MuBit outcome recorded: template assembly=%s outcome=%s", assembly_type, outcome)
    except Exception as e:
        logger.warning("MuBit record_template_outcome failed: %s", e)
