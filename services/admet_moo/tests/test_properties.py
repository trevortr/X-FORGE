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


def test_tier_five_properties_consume_pipeline_evidence() -> None:
    properties = property_registry.create(
        [
            "binding_free_energy",
            "selectivity_gap",
            "metabolic_clearance",
            "herg_pic50",
            "synthetic_feasibility",
        ]
    )
    evidence = {
        "binding_free_energy_kcal_mol": -9.0,
        "selectivity_gap_target_minus_offtarget": 2.0,
        "microsomal_clint": 20.0,
        "herg_pic50": 4.0,
        "route_steps": 3.0,
        "route_confidence": 0.8,
    }

    assert [prop.prediction(evidence) for prop in properties] == [
        -9.0,
        2.0,
        20.0,
        4.0,
        4.0,
    ]


def test_low_cost_properties_consume_tier_three_docking_evidence() -> None:
    properties = property_registry.create(
        ["docking_affinity", "docking_selectivity_gap"]
    )
    evidence = {
        "vina_score": -8.3,
        "selectivity_gap_target_minus_offtarget": -2.1,
    }

    assert [prop.prediction(evidence) for prop in properties] == [-8.3, -2.1]
