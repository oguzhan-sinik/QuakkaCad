"""Assembly dispatcher — maps assembly_type to composition function."""

from ..models import AssemblySpec
from . import (
    bushing_assembly,
    finned_rocket_body,
    flanged_tube,
    gear_train,
    helical_spring,
    hex_standoff,
    planetary_gear,
    rack_and_pinion,
    shaft_coupling,
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
}


def dispatch_compose(spec: AssemblySpec) -> str:
    """Route a validated spec to its composition function and return .scad source."""
    fn = _COMPOSERS.get(spec.assembly_type)
    if fn is None:
        raise ValueError(f"Unknown assembly_type: {spec.assembly_type}")
    return fn(spec)
