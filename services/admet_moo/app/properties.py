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
        requested = keys if keys is not None else list(self._property_types)
        unknown = sorted(set(requested) - self._property_types.keys())
        if unknown:
            raise KeyError(f"unknown ADMET properties: {', '.join(unknown)}")
        if len(requested) != len(set(requested)):
            raise ValueError("ADMET property names must be unique")
        if not requested:
            raise ValueError("at least one ADMET property is required")
        return [self._property_types[key]() for key in requested]

    def __iter__(self) -> Iterator[ADMETProperty]:
        return (property_type() for property_type in self._property_types.values())


property_registry = ADMETPropertyRegistry()
for _property_type in (
    BioavailabilityProperty,
    AqueousSolubilityProperty,
    CYP3A4InhibitionProperty,
    HERGProperty,
    DILIProperty,
):
    property_registry.register(_property_type)
