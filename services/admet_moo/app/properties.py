from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Literal

Goal = Literal["maximize", "minimize"]


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return min(upper, max(lower, value))


def _require_finite(value: float, property_name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{property_name} prediction must be finite")
    return value


class ADMETProperty(ABC):
    """One independently configurable objective predicted by ADMET-AI."""

    key: str
    source_column: str
    display_name: str
    category: str
    units: str
    goal: Goal
    desirability_description: str
    default: bool = True

    def prediction(self, predictions: dict[str, float]) -> float:
        try:
            value = predictions[self.source_column]
        except KeyError as exc:
            raise KeyError(
                f"ADMET-AI did not return required column {self.source_column!r} "
                f"for property {self.key!r}"
            ) from exc
        return _require_finite(value, self.key)

    @abstractmethod
    def objective(self, value: float) -> float:
        """Convert a prediction to pymoo's minimization convention."""

    @abstractmethod
    def desirability(self, value: float) -> float:
        """Convert a prediction to a unitless value in [0, 1]."""

    def metadata(self) -> dict[str, str]:
        return {
            "key": self.key,
            "source_column": self.source_column,
            "display_name": self.display_name,
            "category": self.category,
            "units": self.units,
            "goal": self.goal,
            "desirability": self.desirability_description,
        }


class BioavailabilityProperty(ADMETProperty):
    key = "bioavailability"
    source_column = "Bioavailability_Ma"
    display_name = "Oral bioavailability"
    category = "absorption"
    units = "probability"
    goal: Goal = "maximize"
    desirability_description = "Predicted probability, clipped to [0, 1]"

    def objective(self, value: float) -> float:
        return -_require_finite(value, self.key)

    def desirability(self, value: float) -> float:
        return _clamp(_require_finite(value, self.key))


class AqueousSolubilityProperty(ADMETProperty):
    key = "aqueous_solubility"
    source_column = "Solubility_AqSolDB"
    display_name = "Aqueous solubility"
    category = "absorption"
    units = "log(mol/L)"
    goal: Goal = "maximize"
    desirability_description = "Linear ramp from 0 at -6 to 1 at -2 log(mol/L)"

    def objective(self, value: float) -> float:
        return -_require_finite(value, self.key)

    def desirability(self, value: float) -> float:
        value = _require_finite(value, self.key)
        return _clamp((value + 6.0) / 4.0)


class CYP3A4InhibitionProperty(ADMETProperty):
    key = "cyp3a4_inhibition"
    source_column = "CYP3A4_Veith"
    display_name = "CYP3A4 inhibition risk"
    category = "metabolism"
    units = "probability"
    goal: Goal = "minimize"
    desirability_description = "One minus predicted inhibition probability"

    def objective(self, value: float) -> float:
        return _require_finite(value, self.key)

    def desirability(self, value: float) -> float:
        return 1.0 - _clamp(_require_finite(value, self.key))


class HERGProperty(ADMETProperty):
    key = "herg_blocking"
    source_column = "hERG"
    display_name = "hERG blocking risk"
    category = "toxicity"
    units = "probability"
    goal: Goal = "minimize"
    desirability_description = "One minus predicted hERG blocking probability"

    def objective(self, value: float) -> float:
        return _require_finite(value, self.key)

    def desirability(self, value: float) -> float:
        return 1.0 - _clamp(_require_finite(value, self.key))


class DILIProperty(ADMETProperty):
    key = "dili"
    source_column = "DILI"
    display_name = "Drug-induced liver injury risk"
    category = "toxicity"
    units = "probability"
    goal: Goal = "minimize"
    desirability_description = "One minus predicted DILI probability"

    def objective(self, value: float) -> float:
        return _require_finite(value, self.key)

    def desirability(self, value: float) -> float:
        return 1.0 - _clamp(_require_finite(value, self.key))


class BindingFreeEnergyProperty(ADMETProperty):
    key = "binding_free_energy"
    source_column = "binding_free_energy_kcal_mol"
    display_name = "Target binding free energy"
    category = "binding"
    units = "kcal/mol"
    goal: Goal = "minimize"
    desirability_description = "Linear improvement from 0 at -4 to 1 at -12 kcal/mol"
    default = False

    def objective(self, value: float) -> float:
        return _require_finite(value, self.key)

    def desirability(self, value: float) -> float:
        return _clamp((-_require_finite(value, self.key) - 4.0) / 8.0)


class DockingAffinityProperty(ADMETProperty):
    key = "docking_affinity"
    source_column = "vina_score"
    display_name = "Target docking score"
    category = "binding"
    units = "kcal/mol"
    goal: Goal = "minimize"
    desirability_description = "Linear improvement from 0 at -4 to 1 at -12 kcal/mol"
    default = False

    def objective(self, value: float) -> float:
        return _require_finite(value, self.key)

    def desirability(self, value: float) -> float:
        return _clamp((-_require_finite(value, self.key) - 4.0) / 8.0)


class SelectivityGapProperty(ADMETProperty):
    key = "selectivity_gap"
    source_column = "selectivity_gap_target_minus_offtarget"
    display_name = "Target-minus-off-target selectivity gap"
    category = "selectivity"
    units = "kcal/mol"
    goal: Goal = "maximize"
    desirability_description = "Linear ramp from 0 at -5 to 1 at 5 kcal/mol"
    default = False

    def objective(self, value: float) -> float:
        return -_require_finite(value, self.key)

    def desirability(self, value: float) -> float:
        return _clamp((_require_finite(value, self.key) + 5.0) / 10.0)


class DockingSelectivityGapProperty(ADMETProperty):
    key = "docking_selectivity_gap"
    source_column = "selectivity_gap_target_minus_offtarget"
    display_name = "Target-minus-off-target docking gap"
    category = "selectivity"
    units = "kcal/mol"
    goal: Goal = "maximize"
    desirability_description = "Linear ramp from 0 at -5 to 1 at 5 kcal/mol"
    default = False

    def objective(self, value: float) -> float:
        return -_require_finite(value, self.key)

    def desirability(self, value: float) -> float:
        return _clamp((_require_finite(value, self.key) + 5.0) / 10.0)


class MetabolicClearanceProperty(ADMETProperty):
    key = "metabolic_clearance"
    source_column = "microsomal_clint"
    display_name = "Microsomal intrinsic clearance"
    category = "metabolism"
    units = "model-native"
    goal: Goal = "minimize"
    desirability_description = "Reciprocal penalty relative to 50 model-native units"
    default = False

    def objective(self, value: float) -> float:
        return _require_finite(value, self.key)

    def desirability(self, value: float) -> float:
        return 1.0 / (1.0 + max(0.0, _require_finite(value, self.key)) / 50.0)


class HERGPIC50Property(ADMETProperty):
    key = "herg_pic50"
    source_column = "herg_pic50"
    display_name = "hERG pIC50"
    category = "toxicity"
    units = "pIC50"
    goal: Goal = "minimize"
    desirability_description = "Linear decline from 1 at pIC50 3 to 0 at pIC50 7"
    default = False

    def objective(self, value: float) -> float:
        return _require_finite(value, self.key)

    def desirability(self, value: float) -> float:
        return _clamp((7.0 - _require_finite(value, self.key)) / 4.0)


class SyntheticFeasibilityProperty(ADMETProperty):
    key = "synthetic_feasibility"
    source_column = "route_steps+route_confidence"
    display_name = "Synthetic route burden"
    category = "synthesis"
    units = "composite"
    goal: Goal = "minimize"
    desirability_description = "Route steps penalized by lack of route confidence"
    default = False

    def prediction(self, predictions: dict[str, float]) -> float:
        steps = _require_finite(predictions["route_steps"], "route_steps")
        confidence = _clamp(
            _require_finite(predictions["route_confidence"], "route_confidence")
        )
        return steps + 5.0 * (1.0 - confidence)

    def objective(self, value: float) -> float:
        return _require_finite(value, self.key)

    def desirability(self, value: float) -> float:
        return _clamp(1.0 - _require_finite(value, self.key) / 12.0)


class ADMETPropertyRegistry:
    def __init__(self) -> None:
        self._property_types: dict[str, type[ADMETProperty]] = {}

    def register(self, property_type: type[ADMETProperty]) -> None:
        if not issubclass(property_type, ADMETProperty):
            raise TypeError("registered properties must inherit from ADMETProperty")
        key = property_type.key
        if key in self._property_types:
            raise ValueError(f"ADMET property {key!r} is already registered")
        self._property_types[key] = property_type

    def create(self, keys: list[str] | None = None) -> list[ADMETProperty]:
        requested = keys if keys is not None else [
            key
            for key, property_type in self._property_types.items()
            if property_type.default
        ]
        unknown = sorted(set(requested) - self._property_types.keys())
        if unknown:
            raise KeyError(f"unknown ADMET properties: {', '.join(unknown)}")
        if len(requested) != len(set(requested)):
            raise ValueError("ADMET property names must be unique")
        if not requested:
            raise ValueError("at least one ADMET property is required")
        return [self._property_types[key]() for key in requested]

    def __iter__(self) -> Iterator[ADMETProperty]:
        return (
            property_type()
            for property_type in self._property_types.values()
            if property_type.default
        )

    def all(self) -> Iterator[ADMETProperty]:
        return (property_type() for property_type in self._property_types.values())


property_registry = ADMETPropertyRegistry()
for _property_type in (
    BioavailabilityProperty,
    AqueousSolubilityProperty,
    CYP3A4InhibitionProperty,
    HERGProperty,
    DILIProperty,
    BindingFreeEnergyProperty,
    DockingAffinityProperty,
    SelectivityGapProperty,
    DockingSelectivityGapProperty,
    MetabolicClearanceProperty,
    HERGPIC50Property,
    SyntheticFeasibilityProperty,
):
    property_registry.register(_property_type)
