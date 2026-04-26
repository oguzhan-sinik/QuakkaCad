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


AssemblySpec = Annotated[
    Union[FinnedRocketBodySpec, GearTrainSpec, PlanetaryGearSpec, BushingAssemblySpec, FlangedTubeSpec],
    Field(discriminator="assembly_type"),
]
