"""Pydantic specs for composable mechanical assembly templates.

Each spec type maps to one assembly composition function. The LLM fills
parameters; Python handles all geometry.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator


class FinnedRocketBodySpec(BaseModel):
    reasoning: str = Field(description="Brief explanation of parameter choices")
    assembly_type: Literal["finned_rocket_body"] = "finned_rocket_body"
    tube_outer_d: float = Field(gt=10, lt=500, description="Tube outer diameter mm")
    tube_wall: float = Field(gt=0.5, lt=20, description="Tube wall thickness mm")
    tube_length: float = Field(gt=20, lt=2000, description="Tube length mm")
    ring_count: int = Field(ge=0, le=4, description="Number of centering rings")
    ring_width: float = Field(default=10, gt=0, lt=100, description="Ring axial width mm")
    ring_radial_thickness: float = Field(default=4, gt=0, lt=50, description="Ring radial thickness mm")
    ring_spacing: float | None = Field(default=None, description="Axial gap between rings (auto if None)")
    fin_count: int = Field(ge=0, le=8, description="Number of fins")
    fin_root_chord: float = Field(default=80, gt=0, description="Fin root chord mm")
    fin_tip_chord: float = Field(default=30, ge=0, description="Fin tip chord mm")
    fin_height: float = Field(default=60, gt=0, description="Fin span from tube surface mm")
    fin_sweep: float = Field(default=30, ge=0, description="Fin sweep distance mm")
    fin_thickness: float = Field(default=2, gt=0.5, lt=20, description="Fin thickness mm")
    fins_through_rings: bool = Field(default=True, description="Cut slots in rings for fins")
    body_color: str = Field(default="SteelBlue", description="OpenSCAD color name for tube body")
    ring_color: str = Field(default="Gold", description="OpenSCAD color name for centering rings")
    fin_color: str = Field(default="Tomato", description="OpenSCAD color name for fins")

    @model_validator(mode="after")
    def check_fits(self):
        if self.fin_root_chord > self.tube_length:
            raise ValueError(
                f"fin_root_chord ({self.fin_root_chord}) cannot exceed "
                f"tube_length ({self.tube_length})"
            )
        if self.ring_count >= 2 and self.ring_spacing is not None:
            total = self.ring_spacing + self.ring_count * self.ring_width
            if total > self.tube_length:
                raise ValueError(
                    f"ring_spacing + ring widths ({total}) exceed "
                    f"tube_length ({self.tube_length}); reduce spacing"
                )
        return self


class GearTrainSpec(BaseModel):
    reasoning: str = Field(description="Brief explanation of parameter choices")
    assembly_type: Literal["gear_train"] = "gear_train"
    gear_count: int = Field(ge=2, le=6, description="Number of meshing gears")
    teeth: list[int] = Field(min_length=2, max_length=6, description="Tooth count per gear")
    module_val: float = Field(gt=0.5, lt=10, description="Gear module (mm)")
    thickness: float = Field(gt=1, lt=50, description="Gear thickness mm")
    bore_d: float = Field(default=5, gt=0, lt=50, description="Bore diameter mm")

    @model_validator(mode="after")
    def check_teeth_count(self):
        if len(self.teeth) != self.gear_count:
            raise ValueError(
                f"teeth list length ({len(self.teeth)}) must match "
                f"gear_count ({self.gear_count})"
            )
        for i, t in enumerate(self.teeth):
            if t < 8 or t > 80:
                raise ValueError(f"teeth[{i}]={t} out of range [8, 80]")
        return self


class PlanetaryGearSpec(BaseModel):
    reasoning: str = Field(description="Brief explanation of parameter choices")
    assembly_type: Literal["planetary_gear"] = "planetary_gear"
    sun_teeth: int = Field(ge=8, le=60, description="Sun gear tooth count")
    planet_teeth: int = Field(ge=8, le=60, description="Planet gear tooth count")
    planet_count: int = Field(ge=2, le=6, description="Number of planet gears")
    module_val: float = Field(gt=0.5, lt=10, description="Gear module (mm)")
    thickness: float = Field(gt=1, lt=50, description="Gear thickness mm")
    bore_d: float = Field(default=5, gt=0, lt=50, description="Bore diameter mm")
    include_ring_gear: bool = Field(default=True, description="Include the outer ring gear")

    @model_validator(mode="after")
    def check_geometry(self):
        # Ring teeth = sun + 2*planet for proper meshing
        ring_teeth = self.sun_teeth + 2 * self.planet_teeth
        if ring_teeth > 200:
            raise ValueError(f"Resulting ring gear ({ring_teeth} teeth) too large; reduce sun or planet teeth")
        return self


class BushingAssemblySpec(BaseModel):
    reasoning: str = Field(description="Brief explanation of parameter choices")
    assembly_type: Literal["bushing_assembly"] = "bushing_assembly"
    bore_d: float = Field(gt=1, lt=200, description="Inner bore diameter mm")
    outer_d: float = Field(gt=2, lt=300, description="Outer diameter mm")
    length: float = Field(gt=5, lt=500, description="Bushing length mm")
    flange: bool = Field(default=False, description="Add a flange at one end")
    flange_outer_d: float | None = Field(default=None, description="Flange OD mm")
    flange_thickness: float | None = Field(default=None, description="Flange thickness mm")

    @model_validator(mode="after")
    def check_diameters(self):
        if self.bore_d >= self.outer_d:
            raise ValueError(
                f"bore_d ({self.bore_d}) must be less than outer_d ({self.outer_d})"
            )
        if self.flange:
            if self.flange_outer_d is None:
                self.flange_outer_d = self.outer_d * 1.5
            if self.flange_thickness is None:
                self.flange_thickness = 3.0
            if self.flange_outer_d <= self.outer_d:
                raise ValueError("flange_outer_d must exceed outer_d")
        return self


class FlangedTubeSpec(BaseModel):
    reasoning: str = Field(description="Brief explanation of parameter choices")
    assembly_type: Literal["flanged_tube"] = "flanged_tube"
    tube_outer_d: float = Field(gt=5, lt=500, description="Tube outer diameter mm")
    tube_inner_d: float = Field(gt=1, lt=500, description="Tube inner diameter mm")
    tube_length: float = Field(gt=10, lt=2000, description="Tube length mm")
    flange_outer_d: float = Field(gt=5, lt=600, description="Flange outer diameter mm")
    flange_thickness: float = Field(gt=1, lt=50, description="Flange thickness mm")
    bolt_count: int = Field(ge=3, le=24, description="Number of bolt holes")
    bolt_circle_d: float = Field(gt=5, lt=500, description="Bolt circle diameter mm")
    bolt_hole_d: float = Field(default=5, gt=1, lt=30, description="Bolt hole diameter mm")
    flange_both_ends: bool = Field(default=False, description="Flanges on both ends")

    @model_validator(mode="after")
    def check_diameters(self):
        if self.tube_inner_d >= self.tube_outer_d:
            raise ValueError("tube_inner_d must be less than tube_outer_d")
        if self.flange_outer_d < self.tube_outer_d:
            raise ValueError("flange_outer_d must be >= tube_outer_d")
        if self.bolt_circle_d <= self.tube_outer_d:
            raise ValueError("bolt_circle_d must be > tube_outer_d")
        if self.bolt_circle_d >= self.flange_outer_d:
            raise ValueError("bolt_circle_d must be < flange_outer_d")
        return self


class RackAndPinionSpec(BaseModel):
    reasoning: str = Field(description="Brief explanation of parameter choices")
    assembly_type: Literal["rack_and_pinion"] = "rack_and_pinion"
    rack_length: float = Field(gt=50, lt=1000, description="Rack total length mm")
    rack_width: float = Field(gt=5, lt=100, description="Rack bar width mm")
    rack_height: float = Field(gt=5, lt=100, description="Rack base height mm (excluding teeth)")
    module_val: float = Field(gt=0.5, lt=10, description="Gear module mm")
    pinion_teeth: int = Field(ge=8, le=80, description="Pinion tooth count")
    pinion_thickness: float = Field(gt=1, lt=50, description="Pinion face width mm")
    bore_d: float = Field(default=5, gt=0, lt=50, description="Pinion bore diameter mm")

    @model_validator(mode="after")
    def check_geometry(self):
        if self.rack_width < self.module_val * 2:
            raise ValueError(f"rack_width must be >= {self.module_val * 2:.1f} (2 × module_val)")
        return self


class WormGearSpec(BaseModel):
    reasoning: str = Field(description="Brief explanation of parameter choices")
    assembly_type: Literal["worm_gear"] = "worm_gear"
    worm_starts: int = Field(ge=1, le=4, description="Number of worm thread starts (determines ratio)")
    wheel_teeth: int = Field(ge=8, le=80, description="Worm wheel tooth count")
    module_val: float = Field(gt=0.5, lt=10, description="Gear module mm")
    worm_length: float = Field(gt=10, lt=200, description="Worm shaft axial length mm")
    wheel_thickness: float = Field(gt=1, lt=50, description="Wheel face width mm")
    bore_d: float = Field(default=5, gt=0, lt=50, description="Wheel bore diameter mm")
    worm_bore_d: float = Field(default=5, gt=0, lt=50, description="Worm shaft bore diameter mm")


class HelicalSpringSpec(BaseModel):
    reasoning: str = Field(description="Brief explanation of parameter choices")
    assembly_type: Literal["helical_spring"] = "helical_spring"
    wire_d: float = Field(gt=0.3, lt=20, description="Wire diameter mm")
    coil_od: float = Field(gt=2, lt=200, description="Coil outer diameter mm")
    free_length: float = Field(gt=5, lt=500, description="Free (unloaded) length mm")
    coil_count: float = Field(gt=1, lt=50, description="Number of active coils")
    spring_type: Literal["compression", "extension", "torsion"] = Field(default="compression")

    @model_validator(mode="after")
    def check_geometry(self):
        if self.coil_od <= self.wire_d * 2:
            raise ValueError(f"coil_od ({self.coil_od}) must be > 2 × wire_d ({self.wire_d * 2:.1f})")
        return self


class ShaftCouplingSpec(BaseModel):
    reasoning: str = Field(description="Brief explanation of parameter choices")
    assembly_type: Literal["shaft_coupling"] = "shaft_coupling"
    shaft_d1: float = Field(gt=1, lt=100, description="First shaft bore diameter mm")
    shaft_d2: float = Field(gt=1, lt=100, description="Second shaft bore diameter mm")
    coupling_od: float = Field(gt=3, lt=200, description="Coupling outer diameter mm")
    coupling_length: float = Field(gt=5, lt=300, description="Total coupling body length mm")
    gap: float = Field(default=1.5, gt=0, lt=20, description="Gap between the two halves mm")

    @model_validator(mode="after")
    def check_geometry(self):
        min_od = max(self.shaft_d1, self.shaft_d2) * 1.5
        if self.coupling_od < min_od:
            raise ValueError(f"coupling_od must be >= {min_od:.1f} (1.5 × max shaft diameter)")
        if self.coupling_length <= self.gap:
            raise ValueError("coupling_length must exceed gap")
        return self


class HexStandoffSpec(BaseModel):
    reasoning: str = Field(description="Brief explanation of parameter choices")
    assembly_type: Literal["hex_standoff"] = "hex_standoff"
    bore_d: float = Field(gt=1, lt=30, description="Bore / thread diameter mm")
    flat_to_flat: float = Field(gt=3, lt=50, description="Hex flat-to-flat (AF) distance mm")
    length: float = Field(gt=3, lt=200, description="Standoff body length mm")
    male_stud: bool = Field(default=False, description="Add male threaded stud at one end")
    stud_d: float = Field(default=3, gt=0, lt=30, description="Male stud outer diameter mm")
    stud_length: float = Field(default=6, gt=0, lt=50, description="Male stud length mm")

    @model_validator(mode="after")
    def check_geometry(self):
        if self.flat_to_flat < self.bore_d * 1.5:
            raise ValueError(f"flat_to_flat must be >= {self.bore_d * 1.5:.1f} (1.5 × bore_d)")
        if self.male_stud and self.stud_d >= self.flat_to_flat:
            raise ValueError("stud_d must be < flat_to_flat")
        return self


class FourBarLinkageSpec(BaseModel):
    reasoning: str = Field(description="Brief explanation of parameter choices")
    assembly_type: Literal["four_bar_linkage"] = "four_bar_linkage"
    ground_length: float = Field(gt=10, lt=500, description="Ground (fixed) link length mm")
    crank_length: float = Field(gt=5, lt=300, description="Crank (input) link length mm")
    coupler_length: float = Field(gt=5, lt=500, description="Coupler link length mm")
    rocker_length: float = Field(gt=5, lt=300, description="Rocker (output) link length mm")
    link_width: float = Field(default=10, gt=2, lt=50, description="Link bar width mm")
    link_thickness: float = Field(default=5, gt=1, lt=30, description="Link bar thickness mm")
    pivot_d: float = Field(default=5, gt=1, lt=30, description="Pivot pin diameter mm")
    crank_angle: float = Field(default=45, ge=0, lt=360, description="Initial crank angle degrees")
    ground_color: str = Field(default="DimGray", description="OpenSCAD color for ground link")
    crank_color: str = Field(default="Tomato", description="OpenSCAD color for crank")
    coupler_color: str = Field(default="SteelBlue", description="OpenSCAD color for coupler")
    rocker_color: str = Field(default="Gold", description="OpenSCAD color for rocker")

    @model_validator(mode="after")
    def check_grashof(self):
        links = sorted([self.ground_length, self.crank_length,
                        self.coupler_length, self.rocker_length])
        if links[3] >= links[0] + links[1] + links[2]:
            raise ValueError(
                "Linkage cannot close — longest link exceeds sum of other three"
            )
        return self


class LeadScrewSpec(BaseModel):
    reasoning: str = Field(description="Brief explanation of parameter choices")
    assembly_type: Literal["lead_screw"] = "lead_screw"
    screw_length: float = Field(gt=20, lt=1000, description="Screw shaft length mm")
    screw_diameter: float = Field(gt=3, lt=80, description="Screw major diameter mm")
    lead: float = Field(gt=0.5, lt=50, description="Lead (axial travel per revolution) mm")
    starts: int = Field(default=1, ge=1, le=6, description="Number of thread starts")
    nut_od: float = Field(gt=5, lt=120, description="Nut outer diameter mm")
    nut_length: float = Field(gt=5, lt=150, description="Nut length mm")
    bore_d: float = Field(default=3, gt=0, lt=50, description="Shaft bore diameter mm")
    ball_screw: bool = Field(default=False, description="Ball screw (true) or lead screw (false)")
    nut_position: float = Field(default=0.5, ge=0.0, le=1.0, description="Nut position along screw (0=start, 1=end)")

    @model_validator(mode="after")
    def check_geometry(self):
        if self.nut_od <= self.screw_diameter:
            raise ValueError(f"nut_od ({self.nut_od}) must exceed screw_diameter ({self.screw_diameter})")
        if self.nut_length > self.screw_length * 0.8:
            raise ValueError("nut_length must be < 80% of screw_length")
        return self


class CamFollowerSpec(BaseModel):
    reasoning: str = Field(description="Brief explanation of parameter choices")
    assembly_type: Literal["cam_follower"] = "cam_follower"
    base_radius: float = Field(gt=5, lt=200, description="Cam base circle radius mm")
    lift: float = Field(gt=1, lt=100, description="Maximum follower lift (rise) mm")
    cam_thickness: float = Field(gt=2, lt=80, description="Cam disc thickness mm")
    follower_diameter: float = Field(default=10, gt=2, lt=60, description="Follower roller diameter mm")
    follower_length: float = Field(default=60, gt=10, lt=300, description="Follower stem length mm")
    shaft_d: float = Field(default=8, gt=1, lt=50, description="Camshaft diameter mm")
    cam_profile: Literal["eccentric", "pear", "heart"] = Field(default="eccentric", description="Cam profile shape")

    @model_validator(mode="after")
    def check_geometry(self):
        if self.lift >= self.base_radius:
            raise ValueError(f"lift ({self.lift}) must be < base_radius ({self.base_radius})")
        if self.shaft_d >= self.base_radius:
            raise ValueError(f"shaft_d ({self.shaft_d}) must be < base_radius ({self.base_radius})")
        return self


class UniversalJointSpec(BaseModel):
    reasoning: str = Field(description="Brief explanation of parameter choices")
    assembly_type: Literal["universal_joint"] = "universal_joint"
    shaft_d: float = Field(gt=3, lt=100, description="Input/output shaft diameter mm")
    yoke_width: float = Field(gt=5, lt=150, description="Yoke arm width mm")
    yoke_thickness: float = Field(gt=2, lt=50, description="Yoke arm thickness mm")
    cross_diameter: float = Field(gt=2, lt=60, description="Spider/cross journal diameter mm")
    cross_length: float = Field(gt=5, lt=100, description="Spider arm length (tip to tip) mm")
    joint_angle: float = Field(default=30, ge=0, lt=90, description="Angle between shafts degrees")
    shaft_length: float = Field(default=60, gt=10, lt=500, description="Visible shaft length each side mm")
    double_joint: bool = Field(default=False, description="Double cardan (CV-like) joint")

    @model_validator(mode="after")
    def check_geometry(self):
        if self.cross_diameter >= self.yoke_width:
            raise ValueError("cross_diameter must be < yoke_width")
        if self.shaft_d >= self.yoke_width:
            raise ValueError("shaft_d must be < yoke_width")
        return self


class BeltPulleySpec(BaseModel):
    reasoning: str = Field(description="Brief explanation of parameter choices")
    assembly_type: Literal["belt_pulley"] = "belt_pulley"
    driver_diameter: float = Field(gt=10, lt=500, description="Driver pulley/sprocket pitch diameter mm")
    driven_diameter: float = Field(gt=10, lt=500, description="Driven pulley/sprocket pitch diameter mm")
    center_distance: float = Field(gt=20, lt=2000, description="Center-to-center distance mm")
    belt_width: float = Field(default=10, gt=2, lt=80, description="Belt/chain width mm")
    belt_thickness: float = Field(default=3, gt=0.5, lt=15, description="Belt thickness mm")
    pulley_thickness: float = Field(default=12, gt=2, lt=60, description="Pulley face width mm")
    bore_d: float = Field(default=8, gt=1, lt=80, description="Shaft bore diameter mm")
    drive_type: Literal["belt", "chain"] = Field(default="belt", description="Belt or chain drive")

    @model_validator(mode="after")
    def check_geometry(self):
        min_cd = (self.driver_diameter + self.driven_diameter) / 2 + 5
        if self.center_distance < min_cd:
            raise ValueError(
                f"center_distance ({self.center_distance}) must be >= {min_cd:.1f} "
                f"(sum of radii + clearance)"
            )
        if self.bore_d >= self.driver_diameter * 0.8:
            raise ValueError("bore_d must be < 80% of driver_diameter")
        return self


# ---------------------------------------------------------------------------
# Reusable hole / cutout sub-models — embedded by bulkhead, body tube, plate
# ---------------------------------------------------------------------------

class CircularHoleSpec(BaseModel):
    """A single circular hole (screw clearance, vent, lightening, etc.)."""
    hole_type: Literal["circular"] = "circular"
    diameter: float = Field(gt=0, lt=200, description="Hole diameter mm")
    x: float = Field(default=0, description="X offset from part centre mm")
    y: float = Field(default=0, description="Y offset from part centre mm")
    countersink: bool = Field(default=False, description="Add 90° countersink")


class BoltCircleSpec(BaseModel):
    """A ring of equally spaced screw holes."""
    hole_type: Literal["bolt_circle"] = "bolt_circle"
    bolt_count: int = Field(ge=2, le=24, description="Number of bolt holes")
    bolt_circle_d: float = Field(gt=0, lt=500, description="Bolt circle diameter mm")
    bolt_hole_d: float = Field(default=3.4, gt=0, lt=30, description="Individual hole diameter mm (e.g. 3.4 for M3 clearance)")
    start_angle: float = Field(default=0, ge=0, lt=360, description="Angle of first hole degrees")
    countersink: bool = Field(default=False, description="Add 90° countersink on each hole")


class RectSlotSpec(BaseModel):
    """A rounded-rectangle slot / cutout (cable management, lightening, etc.)."""
    hole_type: Literal["rect_slot"] = "rect_slot"
    width: float = Field(gt=0, lt=500, description="Slot width mm (X direction)")
    height: float = Field(gt=0, lt=500, description="Slot height mm (Y direction)")
    corner_r: float = Field(default=2, ge=0, lt=50, description="Corner radius mm (0 = sharp)")
    x: float = Field(default=0, description="X offset from part centre mm")
    y: float = Field(default=0, description="Y offset from part centre mm")


HolePattern = Annotated[
    Union[CircularHoleSpec, BoltCircleSpec, RectSlotSpec],
    Field(discriminator="hole_type"),
]


# ---------------------------------------------------------------------------
# Hobby-rocketry and general-purpose plate templates
# ---------------------------------------------------------------------------

# Standard Estes body-tube designations (OD in mm)
_BT_DIAMETERS: dict[str, float] = {
    "BT-5":   13.8,
    "BT-20":  18.7,
    "BT-50":  24.8,
    "BT-55":  33.7,
    "BT-60":  41.6,
    "BT-70":  56.3,
    "BT-80":  66.0,
    "BT-101": 103.6,
}


class BulkheadSpec(BaseModel):
    """Flat disc that seals the end of a body tube.

    Supports a centre bore, one or more bolt circles, and arbitrary extra
    holes / rectangular slots (e.g. wiring pass-throughs).
    """
    reasoning: str = Field(description="Brief explanation of parameter choices")
    assembly_type: Literal["bulkhead"] = "bulkhead"
    outer_d: float = Field(gt=5, lt=500, description="Bulkhead outer diameter mm (should match tube ID)")
    thickness: float = Field(gt=0.5, lt=50, description="Disc thickness mm")
    center_bore_d: float = Field(default=0, ge=0, lt=200, description="Centre bore diameter mm (0 = solid)")
    shoulder_d: float = Field(default=0, ge=0, lt=500, description="Shoulder (lip) diameter mm that nests inside tube (0 = no shoulder)")
    shoulder_length: float = Field(default=0, ge=0, lt=50, description="Shoulder insertion depth mm")
    holes: list[HolePattern] = Field(default_factory=list, description="Additional holes / cutouts (bolt circles, screw holes, slots)")
    color: str = Field(default="BurlyWood", description="OpenSCAD color name")

    @model_validator(mode="after")
    def check_geometry(self):
        if self.center_bore_d >= self.outer_d:
            raise ValueError("center_bore_d must be < outer_d")
        if self.shoulder_d > 0 and self.shoulder_d >= self.outer_d:
            raise ValueError("shoulder_d must be < outer_d")
        return self


class BodyTubeSpec(BaseModel):
    """Hobby-rocketry body tube — optionally pick a standard BT designation,
    or supply custom OD / wall.  Supports arbitrary hole cutouts along the wall.
    """
    reasoning: str = Field(description="Brief explanation of parameter choices")
    assembly_type: Literal["body_tube"] = "body_tube"
    bt_designation: str | None = Field(default=None, description="Standard tube name e.g. 'BT-50', 'BT-80' (overrides outer_d)")
    outer_d: float = Field(default=24.8, gt=5, lt=500, description="Tube outer diameter mm (ignored when bt_designation is set)")
    wall: float = Field(default=0.8, gt=0.2, lt=20, description="Wall thickness mm")
    length: float = Field(gt=10, lt=2000, description="Tube length mm")
    holes: list[HolePattern] = Field(default_factory=list, description="Holes / slots cut through the tube wall")
    color: str = Field(default="SteelBlue", description="OpenSCAD color name")

    @model_validator(mode="after")
    def resolve_designation(self):
        if self.bt_designation:
            key = self.bt_designation.upper().replace(" ", "")
            if key in _BT_DIAMETERS:
                self.outer_d = _BT_DIAMETERS[key]
            else:
                raise ValueError(
                    f"Unknown designation '{self.bt_designation}'; "
                    f"choose from {list(_BT_DIAMETERS.keys())}"
                )
        if self.wall * 2 >= self.outer_d:
            raise ValueError("wall * 2 must be < outer_d")
        return self


class MountingPlateSpec(BaseModel):
    """Flat rectangular plate / table / bracket with arbitrary holes and slots.

    Perfect for electronics mounting, cable routing tables, avionics sleds, etc.
    """
    reasoning: str = Field(description="Brief explanation of parameter choices")
    assembly_type: Literal["mounting_plate"] = "mounting_plate"
    width: float = Field(gt=5, lt=1000, description="Plate width mm (X)")
    depth: float = Field(gt=5, lt=1000, description="Plate depth mm (Y)")
    thickness: float = Field(gt=0.5, lt=50, description="Plate thickness mm")
    corner_r: float = Field(default=0, ge=0, lt=100, description="Outer corner radius mm (0 = sharp)")
    holes: list[HolePattern] = Field(default_factory=list, description="Holes / cutouts / bolt patterns")
    color: str = Field(default="Silver", description="OpenSCAD color name")

    @model_validator(mode="after")
    def check_geometry(self):
        if self.corner_r > min(self.width, self.depth) / 2:
            raise ValueError("corner_r exceeds half the smallest side")
        return self


class DifferentialGearSpec(BaseModel):
    reasoning: str = Field(description="Brief explanation of parameter choices")
    assembly_type: Literal["differential_gear"] = "differential_gear"
    ring_gear_teeth: int = Field(ge=20, le=120, description="Ring (crown) gear tooth count")
    pinion_teeth: int = Field(ge=8, le=40, description="Drive pinion tooth count")
    side_gear_teeth: int = Field(ge=10, le=60, description="Side (axle) gear tooth count")
    spider_gear_teeth: int = Field(ge=8, le=40, description="Spider (planet) gear tooth count")
    spider_count: int = Field(default=2, ge=2, le=4, description="Number of spider gears")
    module_val: float = Field(gt=0.5, lt=10, description="Gear module mm")
    thickness: float = Field(gt=2, lt=50, description="Gear thickness mm")
    bore_d: float = Field(default=8, gt=1, lt=60, description="Axle bore diameter mm")
    case_od: float = Field(default=0, ge=0, lt=400, description="Differential case OD mm (auto if 0)")
    include_case: bool = Field(default=True, description="Include the differential housing/case")

    @model_validator(mode="after")
    def check_geometry(self):
        if self.side_gear_teeth != self.spider_gear_teeth:
            # For a standard open diff, side and spider gears usually mesh
            pass  # Allow mismatch for bevel gearing representation
        ring_pitch_r = self.module_val * self.ring_gear_teeth / 2
        if self.case_od == 0:
            self.case_od = round(ring_pitch_r * 1.5, 1)
        if self.case_od < self.module_val * self.side_gear_teeth:
            raise ValueError("case_od too small to contain side gears")
        return self


# Single-part spec union — every template type except stack_assembly.
# Used as the element type inside StackAssemblySpec.parts.
SinglePartSpec = Annotated[
    Union[
        FinnedRocketBodySpec,
        GearTrainSpec,
        PlanetaryGearSpec,
        BushingAssemblySpec,
        FlangedTubeSpec,
        RackAndPinionSpec,
        WormGearSpec,
        HelicalSpringSpec,
        ShaftCouplingSpec,
        HexStandoffSpec,
        FourBarLinkageSpec,
        LeadScrewSpec,
        CamFollowerSpec,
        UniversalJointSpec,
        BeltPulleySpec,
        DifferentialGearSpec,
        BulkheadSpec,
        BodyTubeSpec,
        MountingPlateSpec,
    ],
    Field(discriminator="assembly_type"),
]


class StackedPart(BaseModel):
    """One part inside a stack assembly, positioned and optionally rotated."""
    x_offset: float = Field(default=0, description="X-axis offset (mm) — 0 = centred")
    y_offset: float = Field(default=0, description="Y-axis offset (mm) — 0 = centred")
    z_offset: float = Field(default=0, description="Z-axis offset (mm) — 0 = build-plate level")
    rx: float = Field(default=0, description="Rotation around X axis (degrees). 90 = stand a flat plate upright facing Y.")
    ry: float = Field(default=0, description="Rotation around Y axis (degrees). 90 = stand a flat plate upright facing X.")
    rz: float = Field(default=0, description="Rotation around Z axis (degrees). Spin in the horizontal plane.")
    spec: SinglePartSpec = Field(description="The template spec for this part")


class StackAssemblySpec(BaseModel):
    """Multiple templates positioned and rotated relative to each other.

    Use when the user describes several components arranged together
    (e.g. "bulkhead with a perpendicular table on top").
    Each part has xyz offsets and rotation angles.
    """
    reasoning: str = Field(description="Brief explanation of the overall assembly")
    assembly_type: Literal["stack_assembly"] = "stack_assembly"
    parts: list[StackedPart] = Field(min_length=2, description="Ordered list of parts")


# Full assembly spec union — includes both single parts and stacks.
AssemblySpec = Annotated[
    Union[
        FinnedRocketBodySpec,
        GearTrainSpec,
        PlanetaryGearSpec,
        BushingAssemblySpec,
        FlangedTubeSpec,
        RackAndPinionSpec,
        WormGearSpec,
        HelicalSpringSpec,
        ShaftCouplingSpec,
        HexStandoffSpec,
        FourBarLinkageSpec,
        LeadScrewSpec,
        CamFollowerSpec,
        UniversalJointSpec,
        BeltPulleySpec,
        DifferentialGearSpec,
        BulkheadSpec,
        BodyTubeSpec,
        MountingPlateSpec,
        StackAssemblySpec,
    ],
    Field(discriminator="assembly_type"),
]
