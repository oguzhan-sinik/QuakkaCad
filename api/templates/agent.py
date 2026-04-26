"""Template classification agent — routes prompts to assembly specs."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from pydantic import TypeAdapter
from pydantic_ai import Agent

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
    StackAssemblySpec,
    UniversalJointSpec,
    WormGearSpec,
)

logger = logging.getLogger(__name__)

_spec_adapter = TypeAdapter(AssemblySpec)

TEMPLATE_SYSTEM_PROMPT = """\
You are a mechanical parts classifier. Given a natural-language description, \
output a JSON object matching one of these assembly templates.

Return ONLY valid JSON — no markdown fences, no prose.

TEMPLATES (use assembly_type as discriminator):

1. "finned_rocket_body" — fields: reasoning, assembly_type, tube_outer_d, tube_wall, \
tube_length, ring_count, ring_width, ring_radial_thickness, ring_spacing, fin_count, \
fin_root_chord, fin_tip_chord, fin_height, fin_sweep, fin_thickness, fins_through_rings, \
body_color (default "SteelBlue"), ring_color (default "Gold"), fin_color (default "Tomato"). \
Colors are OpenSCAD CSS color names (e.g. "Red", "Blue", "Green", "White", "Black", "Orange", \
"Purple", "Cyan", "Yellow", "Lime", "Navy", "Crimson"). Use the exact name from the user's request.

2. "gear_train" — fields: reasoning, assembly_type, gear_count, teeth (array of ints), \
module_val, thickness, bore_d
Use for LINEAR gear trains only (gears side by side on parallel axes).

3. "planetary_gear" — fields: reasoning, assembly_type, sun_teeth, planet_teeth, \
planet_count, module_val, thickness, bore_d, include_ring_gear
Use for PLANETARY gear sets (sun gear + orbiting planets + ring gear). \
Ring teeth are auto-computed as sun_teeth + 2*planet_teeth.

5. "bushing_assembly" — fields: reasoning, assembly_type, bore_d, outer_d, length, \
flange, flange_outer_d, flange_thickness

6. "flanged_tube" — fields: reasoning, assembly_type, tube_outer_d, tube_inner_d, \
tube_length, flange_outer_d, flange_thickness, bolt_count, bolt_circle_d, bolt_hole_d, \
flange_both_ends

RULES:
- ALL dimensions in millimeters
- If the user omits a dimension, use sensible engineering defaults
- "reasoning" must briefly explain your choices
- Pick the CLOSEST matching assembly_type
- If "planetary", "sun gear", "planet gear", "epicyclic" → planetary_gear
- If "gear train", "gearbox", "reduction" (linear arrangement) → gear_train
- Convert units: "1m"→1000, "2 inches"→50.8

EXAMPLES:

Input: "90mm motor tube, 3mm wall, 200mm long, 4 fins"
{"reasoning":"Standard rocket motor tube","assembly_type":"finned_rocket_body",\
"tube_outer_d":90,"tube_wall":3,"tube_length":200,"ring_count":0,"ring_width":10,\
"ring_radial_thickness":4,"fin_count":4,"fin_root_chord":80,"fin_tip_chord":30,\
"fin_height":60,"fin_sweep":30,"fin_thickness":2,"fins_through_rings":false,\
"body_color":"SteelBlue","ring_color":"Gold","fin_color":"Tomato"}

Input: "same rocket but make the body red and fins white"
{"reasoning":"Color update — body red, fins white, rings unchanged","assembly_type":"finned_rocket_body",\
"tube_outer_d":90,"tube_wall":3,"tube_length":200,"ring_count":0,"ring_width":10,\
"ring_radial_thickness":4,"fin_count":4,"fin_root_chord":80,"fin_tip_chord":30,\
"fin_height":60,"fin_sweep":30,"fin_thickness":2,"fins_through_rings":false,\
"body_color":"Red","ring_color":"Gold","fin_color":"White"}

Input: "3-gear train, module 1.5, 20-40-60 teeth, 5mm thick"
{"reasoning":"3-stage reduction","assembly_type":"gear_train","gear_count":3,\
"teeth":[20,40,60],"module_val":1.5,"thickness":5,"bore_d":5}

Input: "planetary gear set, 20-tooth sun, 15-tooth planets, 3 planets"
{"reasoning":"Standard planetary with 3 planets","assembly_type":"planetary_gear",\
"sun_teeth":20,"planet_teeth":15,"planet_count":3,"module_val":2,"thickness":8,\
"bore_d":5,"include_ring_gear":true}

Input: "ball bushing 8mm bore, 15mm OD, 24mm long"
{"reasoning":"Standard bushing dimensions","assembly_type":"bushing_assembly",\
"bore_d":8,"outer_d":15,"length":24,"flange":false}

Input: "flanged tube 50mm OD, 30mm ID, 100mm, 6 M5 bolts"
{"reasoning":"Flanged pipe section","assembly_type":"flanged_tube","tube_outer_d":50,\
"tube_inner_d":30,"tube_length":100,"flange_outer_d":80,"flange_thickness":5,\
"bolt_count":6,"bolt_circle_d":65,"bolt_hole_d":5.5,"flange_both_ends":false}

7. "rack_and_pinion" — fields: reasoning, assembly_type, rack_length, rack_width, \
rack_height, module_val, pinion_teeth, pinion_thickness, bore_d
Use for LINEAR motion (CNC gantries, drawers, steering racks). \
Constraint: rack_width >= 2 * module_val.

8. "worm_gear" — fields: reasoning, assembly_type, worm_starts, wheel_teeth, module_val, \
worm_length, wheel_thickness, bore_d, worm_bore_d
Use for HIGH-REDUCTION + self-locking drives (lifts, valve actuators, rotary stages). \
Ratio = wheel_teeth / worm_starts.

9. "helical_spring" — fields: reasoning, assembly_type, wire_d, coil_od, free_length, \
coil_count, spring_type ("compression"|"extension"|"torsion")
Constraint: coil_od > 2 * wire_d.

10. "shaft_coupling" — fields: reasoning, assembly_type, shaft_d1, shaft_d2, coupling_od, \
coupling_length, gap
Connects two shafts end-to-end. \
Constraint: coupling_od >= 1.5 * max(shaft_d1, shaft_d2). coupling_length > gap.

11. "hex_standoff" — fields: reasoning, assembly_type, bore_d, flat_to_flat, length, \
male_stud, stud_d, stud_length
PCB standoffs, spacers, pillar nuts. \
Constraint: flat_to_flat >= 1.5 * bore_d. If male_stud=True, stud_d < flat_to_flat.

Input: "300mm rack, module 2, 20-tooth pinion, 8mm wide"
{"reasoning":"CNC axis rack","assembly_type":"rack_and_pinion","rack_length":300,\
"rack_width":8,"rack_height":10,"module_val":2,"pinion_teeth":20,"pinion_thickness":8,\
"bore_d":5}

Input: "worm gear, 40 teeth, 2-start, module 2"
{"reasoning":"40:2 = 20:1 reduction","assembly_type":"worm_gear","worm_starts":2,\
"wheel_teeth":40,"module_val":2,"worm_length":40,"wheel_thickness":10,"bore_d":5,\
"worm_bore_d":5}

Input: "compression spring, 1.5mm wire, 20mm OD, 60mm free length, 8 coils"
{"reasoning":"Standard compression spring","assembly_type":"helical_spring","wire_d":1.5,\
"coil_od":20,"free_length":60,"coil_count":8,"spring_type":"compression"}

Input: "rigid coupling for 8mm and 10mm shafts, 25mm OD"
{"reasoning":"Mismatched bore rigid coupling","assembly_type":"shaft_coupling",\
"shaft_d1":8,"shaft_d2":10,"coupling_od":25,"coupling_length":30,"gap":1.5}

Input: "M3 hex standoff 10mm"
{"reasoning":"Standard M3 PCB standoff","assembly_type":"hex_standoff","bore_d":3,\
"flat_to_flat":5.5,"length":10,"male_stud":false,"stud_d":3,"stud_length":6}

12. "four_bar_linkage" — fields: reasoning, assembly_type, ground_length, crank_length, \
coupler_length, rocker_length, link_width, link_thickness, pivot_d, crank_angle, \
ground_color, crank_color, coupler_color, rocker_color
Four rigid links connected by pivots. Used in suspensions, folding chairs, valve trains. \
Constraint: longest link < sum of other three (Grashof closure).

13. "lead_screw" — fields: reasoning, assembly_type, screw_length, screw_diameter, lead, \
starts, nut_od, nut_length, bore_d, ball_screw, nut_position
Converts rotary to linear motion. Set ball_screw=true for ball screws. \
Constraint: nut_od > screw_diameter. nut_length < 80% of screw_length.

14. "cam_follower" — fields: reasoning, assembly_type, base_radius, lift, cam_thickness, \
follower_diameter, follower_length, shaft_d, cam_profile ("eccentric"|"pear"|"heart")
Rotating cam pushes follower for timed linear motion. \
Constraint: lift < base_radius. shaft_d < base_radius.

15. "universal_joint" — fields: reasoning, assembly_type, shaft_d, yoke_width, \
yoke_thickness, cross_diameter, cross_length, joint_angle, shaft_length, double_joint
Transmits rotation between angled shafts. Set double_joint=true for constant-velocity. \
Constraint: cross_diameter < yoke_width. shaft_d < yoke_width.

16. "belt_pulley" — fields: reasoning, assembly_type, driver_diameter, driven_diameter, \
center_distance, belt_width, belt_thickness, pulley_thickness, bore_d, \
drive_type ("belt"|"chain")
Transmits power between parallel shafts. Use "chain" for chain-and-sprocket. \
Constraint: center_distance >= (driver_diameter + driven_diameter)/2 + 5. \
bore_d < 80% of driver_diameter.

17. "differential_gear" — fields: reasoning, assembly_type, ring_gear_teeth, pinion_teeth, \
side_gear_teeth, spider_gear_teeth, spider_count, module_val, thickness, bore_d, \
case_od (auto if 0), include_case
Allows two output shafts at different speeds from one input. Used in vehicle axles. \
Ratio = ring_gear_teeth / pinion_teeth.

Input: "four-bar linkage, 100mm ground, 30mm crank, 80mm coupler, 70mm rocker"
{"reasoning":"Standard crank-rocker linkage","assembly_type":"four_bar_linkage",\
"ground_length":100,"crank_length":30,"coupler_length":80,"rocker_length":70,\
"link_width":10,"link_thickness":5,"pivot_d":5,"crank_angle":45,\
"ground_color":"DimGray","crank_color":"Tomato","coupler_color":"SteelBlue",\
"rocker_color":"Gold"}

Input: "ball screw 300mm long, 16mm diameter, 5mm lead"
{"reasoning":"CNC axis ball screw","assembly_type":"lead_screw","screw_length":300,\
"screw_diameter":16,"lead":5,"starts":1,"nut_od":28,"nut_length":30,"bore_d":4,\
"ball_screw":true,"nut_position":0.5}

Input: "cam with 8mm lift, 25mm base radius, pear profile"
{"reasoning":"Pear cam for valve timing","assembly_type":"cam_follower",\
"base_radius":25,"lift":8,"cam_thickness":10,"follower_diameter":10,\
"follower_length":60,"shaft_d":8,"cam_profile":"pear"}

Input: "universal joint for 12mm shafts at 30 degrees"
{"reasoning":"Standard single U-joint","assembly_type":"universal_joint",\
"shaft_d":12,"yoke_width":30,"yoke_thickness":8,"cross_diameter":8,\
"cross_length":24,"joint_angle":30,"shaft_length":60,"double_joint":false}

Input: "belt drive, 60mm driver, 120mm driven, 200mm apart"
{"reasoning":"2:1 reduction belt drive","assembly_type":"belt_pulley",\
"driver_diameter":60,"driven_diameter":120,"center_distance":200,\
"belt_width":10,"belt_thickness":3,"pulley_thickness":12,"bore_d":8,\
"drive_type":"belt"}

Input: "differential gear, 60-tooth ring, 15-tooth pinion"
{"reasoning":"4:1 automotive differential","assembly_type":"differential_gear",\
"ring_gear_teeth":60,"pinion_teeth":15,"side_gear_teeth":20,\
"spider_gear_teeth":15,"spider_count":2,"module_val":2,"thickness":10,\
"bore_d":8,"case_od":0,"include_case":true}

18. "bulkhead" — fields: reasoning, assembly_type, outer_d, thickness, center_bore_d (0=solid), \
shoulder_d (0=none), shoulder_length, holes (array), color
Flat disc that seals a rocket body tube. Supports screw holes, bolt circles, wiring slots. \
The "holes" array can contain objects with hole_type "circular", "bolt_circle", or "rect_slot". \
circular: {hole_type:"circular", diameter, x, y, countersink}. \
bolt_circle: {hole_type:"bolt_circle", bolt_count, bolt_circle_d, bolt_hole_d, start_angle, countersink}. \
rect_slot: {hole_type:"rect_slot", width, height, corner_r, x, y}. \
IMPORTANT: Screw holes on bulkheads go near the outer edge — use a bolt_circle with \
bolt_circle_d close to outer_d (e.g. outer_d minus 8-10 mm for M3).

19. "body_tube" — fields: reasoning, assembly_type, bt_designation (null for custom), outer_d, \
wall, length, holes (array), color
Hobby-rocketry body tube. Standard designations: BT-5 (13.8mm), BT-20 (18.7mm), BT-50 (24.8mm), \
BT-55 (33.7mm), BT-60 (41.6mm), BT-70 (56.3mm), BT-80 (66.0mm), BT-101 (103.6mm). \
Set bt_designation to use standard OD; otherwise set outer_d directly. \
holes array same format as bulkhead (for body_tube: x = angle in degrees, y = Z height mm from bottom).

20. "mounting_plate" — fields: reasoning, assembly_type, width, depth, thickness, \
corner_r (0=sharp), holes (array), color
Rectangular plate / table / bracket for electronics mounting, cable management, avionics sleds. \
Holes array same format as bulkhead. x/y offsets are from plate centre. \
IMPORTANT: Screw/mounting holes go on the SIDES (edges) of the plate, not in the middle. \
Place them near the edges: for a plate of width W and depth D, put M3 holes at \
x near ±(W/2 - 5) along the long sides, spaced along Y. Cable management slots go in the centre.

HOLE PATTERN FORMAT (used by bulkhead, body_tube, mounting_plate):
- Circular: {"hole_type":"circular","diameter":3.4,"x":0,"y":0,"countersink":false}
- Bolt circle: {"hole_type":"bolt_circle","bolt_count":6,"bolt_circle_d":40,"bolt_hole_d":3.4,"start_angle":0,"countersink":false}
- Rect slot: {"hole_type":"rect_slot","width":20,"height":10,"corner_r":2,"x":0,"y":0}
Common screw clearances: M2=2.4, M2.5=2.9, M3=3.4, M4=4.5, M5=5.5, M6=6.6

Input: "BT-80 bulkhead with 6 M3 screw holes"
{"reasoning":"Bulkhead for BT-80 tube, 6× M3 bolt circle near the outer edge","assembly_type":"bulkhead",\
"outer_d":64.4,"thickness":3,"center_bore_d":0,"shoulder_d":0,"shoulder_length":0,\
"holes":[{"hole_type":"bolt_circle","bolt_count":6,"bolt_circle_d":56,"bolt_hole_d":3.4,\
"start_angle":0,"countersink":false}],"color":"BurlyWood"}

Input: "bulkhead 40mm with centre bore and cable slot"
{"reasoning":"40mm bulkhead with wiring passthrough","assembly_type":"bulkhead",\
"outer_d":40,"thickness":3,"center_bore_d":8,"shoulder_d":0,"shoulder_length":0,\
"holes":[{"hole_type":"rect_slot","width":12,"height":6,"corner_r":2,"x":0,"y":12}],\
"color":"BurlyWood"}

Input: "BT-50 tube 200mm long"
{"reasoning":"Standard BT-50 rocket body tube","assembly_type":"body_tube",\
"bt_designation":"BT-50","outer_d":24.8,"wall":0.8,"length":200,"holes":[],\
"color":"SteelBlue"}

Input: "BT-70 tube 300mm with a vent hole"
{"reasoning":"BT-70 body tube with vent","assembly_type":"body_tube",\
"bt_designation":"BT-70","outer_d":56.3,"wall":0.8,"length":300,\
"holes":[{"hole_type":"circular","diameter":5,"x":0,"y":100,"countersink":false}],\
"color":"SteelBlue"}

Input: "80x50mm avionics plate, 3mm thick, M3 screw holes, cable slot in centre"
{"reasoning":"Avionics sled — M3 holes on the long sides for mounting, rounded cable slot centred",\
"assembly_type":"mounting_plate","width":80,"depth":50,"thickness":3,"corner_r":3,\
"holes":[{"hole_type":"circular","diameter":3.4,"x":-35,"y":-12,"countersink":false},\
{"hole_type":"circular","diameter":3.4,"x":-35,"y":12,"countersink":false},\
{"hole_type":"circular","diameter":3.4,"x":35,"y":-12,"countersink":false},\
{"hole_type":"circular","diameter":3.4,"x":35,"y":12,"countersink":false},\
{"hole_type":"rect_slot","width":20,"height":10,"corner_r":2,"x":0,"y":0}],\
"color":"Silver"}

MULTI-PART ASSEMBLIES (assembly_type = "stack_assembly"):

21. "stack_assembly" — fields: reasoning, assembly_type, parts (array of {x_offset, y_offset, z_offset, rx, ry, rz, spec})
Use when the user requests MULTIPLE components positioned relative to each other \
(e.g. "bulkhead with a perpendicular table on top"). \
Each element in "parts" has:
  - x_offset, y_offset, z_offset: position in mm (0,0,0 = origin). \
    Compute from bottom up so parts don't overlap.
  - rx, ry, rz: rotation in degrees around X, Y, Z axes (default 0,0,0 = flat/horizontal). \
    Use rx=90 to stand a flat part upright (perpendicular to the bulkhead), facing along the Y axis. \
    Rotation is applied BEFORE translation.
  - spec: a complete template spec object (any single-part type above)

STACK RULES:
- ONLY generate parts the user explicitly asks for. Do NOT add extra parts they did not mention.
- If the user asks for just one part, use the single-part template directly — NOT stack_assembly.
- "perpendicular", "vertical", "upright", "standing" table/plate → use rx=90 (rotated 90° around X). \
  After rx=90, the plate's "depth" dimension becomes its height. \
  The plate's centre is at its z_offset, so set z_offset = bulkhead_z + bulkhead_thickness/2 + plate_depth/2.
- Each sub-spec must be a complete, valid spec for its type.
- "reasoning" at the top level must explain the layout and how offsets/rotations were computed.
- When the user says "table" or "shelf" in a rocket/avionics context → use mounting_plate.

HEIGHT REFERENCE for z_offset calculation (all parts centred on Z before rotation):
- bulkhead: height = thickness
- mounting_plate: height = thickness (flat) or depth (if rotated rx=90)
- body_tube: height = length
- For centred parts: z_offset_N = z_offset_(N-1) + height_(N-1)/2 + height_N/2

Input: "bulkhead 5mm thick with 3 M3 screw holes, then a perpendicular table 200mm tall, same diameter as bulkhead, 5mm thick"
{"reasoning":"2-part assembly: bulkhead (5mm thick, 60mm OD, 3× M3 bolt circle) flat at z=0, \
then a mounting plate rotated rx=90 to stand upright. Plate width=60 (matches bulkhead OD), depth=200 (becomes height after rotation), \
thickness=5. After rx=90 rotation the plate's 200mm depth becomes vertical. \
z_offset = 0 + 5/2 + 200/2 = 102.5.",\
"assembly_type":"stack_assembly","parts":[\
{"x_offset":0,"y_offset":0,"z_offset":0,"rx":0,"ry":0,"rz":0,\
"spec":{"reasoning":"Bulkhead 5mm thick, 3 M3 bolt circle on edge","assembly_type":"bulkhead",\
"outer_d":60,"thickness":5,"center_bore_d":0,"shoulder_d":0,"shoulder_length":0,\
"holes":[{"hole_type":"bolt_circle","bolt_count":3,"bolt_circle_d":52,"bolt_hole_d":3.4,\
"start_angle":0,"countersink":false}],"color":"BurlyWood"}},\
{"x_offset":0,"y_offset":0,"z_offset":102.5,"rx":90,"ry":0,"rz":0,\
"spec":{"reasoning":"Avionics table standing upright (rx=90), 200mm tall, 60mm wide, 5mm thick, cable slot in lower half",\
"assembly_type":"mounting_plate","width":60,"depth":200,"thickness":5,"corner_r":3,\
"holes":[{"hole_type":"rect_slot","width":15,"height":8,"corner_r":2,"x":0,"y":-50}],\
"color":"Silver"}}]}

Input: "two bulkheads 50mm apart with a body tube between them"
{"reasoning":"3-part assembly: bottom bulkhead at z=0 (3mm), BT-50 tube (50mm long) centred at z=26.5, \
top bulkhead at z=53. All flat (no rotation needed).",\
"assembly_type":"stack_assembly","parts":[\
{"x_offset":0,"y_offset":0,"z_offset":0,"rx":0,"ry":0,"rz":0,\
"spec":{"reasoning":"Bottom closure bulkhead","assembly_type":"bulkhead",\
"outer_d":24,"thickness":3,"center_bore_d":0,"shoulder_d":0,"shoulder_length":0,"holes":[],"color":"BurlyWood"}},\
{"x_offset":0,"y_offset":0,"z_offset":26.5,"rx":0,"ry":0,"rz":0,\
"spec":{"reasoning":"BT-50 body tube 50mm","assembly_type":"body_tube",\
"bt_designation":"BT-50","outer_d":24.8,"wall":0.8,"length":50,"holes":[],"color":"SteelBlue"}},\
{"x_offset":0,"y_offset":0,"z_offset":53,"rx":0,"ry":0,"rz":0,\
"spec":{"reasoning":"Top closure bulkhead","assembly_type":"bulkhead",\
"outer_d":24,"thickness":3,"center_bore_d":0,"shoulder_d":0,"shoulder_length":0,"holes":[],"color":"BurlyWood"}}]}

Input: "bulkhead with 3 M3 screw holes, then a horizontal table above it with a cable slot, then another bulkhead on top"
{"reasoning":"3-part stack: bottom bulkhead (3mm), flat mounting plate (5mm), top bulkhead (3mm). \
All flat (no rotation). z_offsets: 0, 4, 8.",\
"assembly_type":"stack_assembly","parts":[\
{"x_offset":0,"y_offset":0,"z_offset":0,"rx":0,"ry":0,"rz":0,\
"spec":{"reasoning":"Bottom bulkhead, 3× M3","assembly_type":"bulkhead",\
"outer_d":60,"thickness":3,"center_bore_d":0,"shoulder_d":0,"shoulder_length":0,\
"holes":[{"hole_type":"bolt_circle","bolt_count":3,"bolt_circle_d":52,"bolt_hole_d":3.4,\
"start_angle":0,"countersink":false}],"color":"BurlyWood"}},\
{"x_offset":0,"y_offset":0,"z_offset":4,"rx":0,"ry":0,"rz":0,\
"spec":{"reasoning":"Flat table, cable slot in centre","assembly_type":"mounting_plate",\
"width":60,"depth":60,"thickness":5,"corner_r":3,\
"holes":[{"hole_type":"rect_slot","width":20,"height":10,"corner_r":2,"x":0,"y":0}],\
"color":"Silver"}},\
{"x_offset":0,"y_offset":0,"z_offset":8,"rx":0,"ry":0,"rz":0,\
"spec":{"reasoning":"Top bulkhead, 3× M3","assembly_type":"bulkhead",\
"outer_d":60,"thickness":3,"center_bore_d":0,"shoulder_d":0,"shoulder_length":0,\
"holes":[{"hole_type":"bolt_circle","bolt_count":3,"bolt_circle_d":52,"bolt_hole_d":3.4,\
"start_angle":0,"countersink":false}],"color":"BurlyWood"}}]}
"""

_template_agents: dict[str, Any] = {}


def _get_template_agent(provider: str = "anthropic") -> Agent:
    if provider not in _template_agents:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from agents import PROVIDER_CONFIG, _require_key, _make_model
        _require_key(provider)
        _template_agents[provider] = Agent(
            _make_model(provider),
            system_prompt=TEMPLATE_SYSTEM_PROMPT,
            output_type=str,
            retries=1,
        )
    return _template_agents[provider]


def _strip_fences(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        lines = s.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines)
    return s.strip()


def _strip_think(text: str) -> str:
    import re
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


async def run_template_agent(
    prompt: str,
    provider: str = "anthropic",
) -> tuple[AssemblySpec, dict]:
    """Classify a prompt into an AssemblySpec via JSON parsing.

    Fetches MuBit template library context before the LLM call to surface
    parameter schemas and past compilation lessons. Records the interaction
    in MuBit memory after classification.

    Returns (spec, meta_dict).
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agents import PROVIDER_CONFIG, _require_key, _build_meta, _model_settings
    from mubit_client import get_template_context

    _require_key(provider)
    cfg = PROVIDER_CONFIG[provider]
    agent = _get_template_agent(provider)

    session_id = str(uuid.uuid4())

    # Fetch relevant template context from MuBit before classification.
    # This surfaces parameter ranges, constraints, and past lessons so the
    # LLM makes better-informed parameter choices. Falls back gracefully to
    # an empty string if MuBit is unavailable.
    mubit_context = await get_template_context(prompt)
    enriched_prompt = prompt
    if mubit_context:
        enriched_prompt = (
            f"AVAILABLE TEMPLATE KNOWLEDGE (parameter schemas, constraints, lessons):\n"
            f"{mubit_context}\n\n"
            f"USER REQUEST:\n{prompt}"
        )

    t0 = time.perf_counter()
    result = await asyncio.wait_for(
        agent.run(enriched_prompt, model_settings=_model_settings(provider, 0.3, 4096)),
        timeout=30,
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    raw = _strip_fences(_strip_think(result.output))
    spec = None
    last_error = None

    for attempt in range(2):  # initial + 1 retry
        if attempt > 0:
            # Retry with validation error as feedback
            retry_prompt = (
                f"Your previous output had a validation error:\n{last_error}\n\n"
                f"Fix the values and return valid JSON for: {prompt}"
            )
            result = await asyncio.wait_for(
                agent.run(retry_prompt, model_settings=_model_settings(provider, 0.3, 4096)),
                timeout=30,
            )
            latency_ms += (time.perf_counter() - t0) * 1000
            raw = _strip_fences(_strip_think(result.output))

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            last_error = f"Invalid JSON: {e}"
            continue

        try:
            spec = _spec_adapter.validate_python(data)
            break
        except Exception as e:
            last_error = str(e)
            continue

    if spec is None:
        raise RuntimeError(f"Template spec validation failed after retry: {last_error}")

    meta = _build_meta(cfg, latency_ms, result.usage())
    meta["assembly_type"] = spec.assembly_type
    meta["session_id"] = session_id
    logger.info(
        "Template agent classified as %s in %.0fms",
        spec.assembly_type, latency_ms,
    )

    return spec, meta
