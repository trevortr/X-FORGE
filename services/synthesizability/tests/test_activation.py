from __future__ import annotations

import pytest

from app.models import SynthesizabilityParameters
from app.scorer import evaluate_activation


def test_p_neg2_activation_penalizes_a_single_weak_input() -> None:
    parameters = SynthesizabilityParameters(
        gate_midpoint=0.5,
        gate_steepness=12.0,
        min_activation=0.5,
    )

    balanced, balanced_passed = evaluate_activation(
        rascore=0.8,
        sascore=2.8,
        parameters=parameters,
    )
    weak_ra, weak_ra_passed = evaluate_activation(
        rascore=0.2,
        sascore=2.8,
        parameters=parameters,
    )

    assert balanced_passed is True
    assert weak_ra_passed is False
    assert balanced["power_mean_p_neg2"] == pytest.approx(0.8)
    assert weak_ra["power_mean_p_neg2"] < 0.3
    assert (
        weak_ra["synthesizability_activation"] < balanced["synthesizability_activation"]
    )


def test_sascore_is_inverted_and_clamped_before_aggregation() -> None:
    parameters = SynthesizabilityParameters()

    easy, _ = evaluate_activation(
        rascore=0.9,
        sascore=1.0,
        parameters=parameters,
    )
    difficult, _ = evaluate_activation(
        rascore=0.9,
        sascore=10.0,
        parameters=parameters,
    )

    assert easy["sascore_desirability"] == 1.0
    assert difficult["sascore_desirability"] > 0.0
    assert difficult["power_mean_p_neg2"] < easy["power_mean_p_neg2"]


def test_power_is_fixed_at_negative_two() -> None:
    with pytest.raises(ValueError):
        SynthesizabilityParameters(power=-1)
