from __future__ import annotations

import pytest
from app.properties import (
    ADMETProperty,
    AqueousSolubilityProperty,
    BioavailabilityProperty,
    DILIProperty,
    property_registry,
)


def test_every_registered_property_inherits_from_base() -> None:
    properties = list(property_registry)

    assert len(properties) == 5
    assert all(isinstance(prop, ADMETProperty) for prop in properties)


def test_property_objectives_follow_minimization_convention() -> None:
    bioavailability = BioavailabilityProperty()
    dili = DILIProperty()

    assert bioavailability.objective(0.9) < bioavailability.objective(0.2)
    assert dili.objective(0.1) < dili.objective(0.8)


@pytest.mark.parametrize(
    ("prediction", "expected"),
    [(-7.0, 0.0), (-6.0, 0.0), (-4.0, 0.5), (-2.0, 1.0), (-1.0, 1.0)],
)
def test_solubility_desirability_is_bounded(prediction: float, expected: float) -> None:
    assert AqueousSolubilityProperty().desirability(prediction) == expected


def test_registry_rejects_unknown_property() -> None:
    with pytest.raises(KeyError, match="unknown ADMET properties"):
        property_registry.create(["not_a_property"])
