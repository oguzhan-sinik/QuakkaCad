"""Assembly dispatcher — maps assembly_type to composition function."""

from ..models import AssemblySpec
from . import (
    belt_pulley,
    body_tube,
    bulkhead,
    bushing_assembly,
    cam_follower,
    differential_gear,
    finned_rocket_body,
    flanged_tube,
    four_bar_linkage,
    gear_train,
    helical_spring,
    hex_standoff,
    lead_screw,
    mounting_plate,
    planetary_gear,
    rack_and_pinion,
    shaft_coupling,
    stack_assembly,
    universal_joint,
    worm_gear,
)

_COMPOSERS = {
    "finned_rocket_body": finned_rocket_body.compose,
    "gear_train":         gear_train.compose,
    "planetary_gear":     planetary_gear.compose,
    "bushing_assembly":   bushing_assembly.compose,
    "flanged_tube":       flanged_tube.compose,
    "rack_and_pinion":    rack_and_pinion.compose,
    "worm_gear":          worm_gear.compose,
    "helical_spring":     helical_spring.compose,
    "shaft_coupling":     shaft_coupling.compose,
    "hex_standoff":       hex_standoff.compose,
    "four_bar_linkage":   four_bar_linkage.compose,
    "lead_screw":         lead_screw.compose,
    "cam_follower":       cam_follower.compose,
    "universal_joint":    universal_joint.compose,
    "belt_pulley":        belt_pulley.compose,
    "differential_gear":  differential_gear.compose,
    "bulkhead":           bulkhead.compose,
    "body_tube":          body_tube.compose,
    "mounting_plate":     mounting_plate.compose,
    "stack_assembly":     stack_assembly.compose,
}


def dispatch_compose(spec: AssemblySpec) -> str:
    """Route a validated spec to its composition function and return .scad source."""
    fn = _COMPOSERS.get(spec.assembly_type)
    if fn is None:
        raise ValueError(f"Unknown assembly_type: {spec.assembly_type}")
    return fn(spec)
