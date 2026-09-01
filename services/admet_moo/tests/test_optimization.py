from __future__ import annotations

import pytest
from app.optimization import ADMETOptimizer, OptimizationError
from app.properties import property_registry


def row(
    bio: float, sol: float, cyp: float, herg: float, dili: float
) -> dict[str, float]:
    return {
        "Bioavailability_Ma": bio,
        "Solubility_AqSolDB": sol,
        "CYP3A4_Veith": cyp,
        "hERG": herg,
        "DILI": dili,
    }


PREDICTIONS = [
    row(0.90, -5.0, 0.10, 0.10, 0.10),
    row(0.70, -2.0, 0.20, 0.20, 0.20),
    row(0.40, -5.5, 0.80, 0.80, 0.80),
]


@pytest.mark.parametrize(
    "method",
    ["knee_point", "desirability", "hypervolume_contribution", "nsga3"],
)
def test_each_strategy_selects_only_from_pareto_front(method: str) -> None:
    result = ADMETOptimizer(property_registry).optimize(
        PREDICTIONS,
        top_k=2,
        method=method,
    )

    assert set(result.pareto_indices) == {0, 1}
    assert set(result.selected_indices) == {0, 1}
    assert result.candidates[2].pareto_rank > 0
    assert result.candidates[2].selected is False


def test_desirability_weights_are_applied() -> None:
    result = ADMETOptimizer(property_registry).optimize(
        PREDICTIONS[:2],
        top_k=1,
        method="desirability",
        weights={"aqueous_solubility": 10.0},
    )

    assert result.selected_indices == (1,)


def test_top_k_does_not_pull_from_dominated_fronts() -> None:
    result = ADMETOptimizer(property_registry).optimize(
        PREDICTIONS,
        top_k=10,
        method="knee_point",
    )

    assert len(result.selected_indices) == 2


def test_hypervolume_reference_must_be_worse_than_normalized_front() -> None:
    with pytest.raises(OptimizationError, match="worse"):
        ADMETOptimizer(property_registry).optimize(
            PREDICTIONS,
            top_k=1,
            method="hypervolume_contribution",
            reference_point={"bioavailability": 0.5},
        )


def test_nsga3_can_apply_scaffold_diversity_and_synthesis_batches() -> None:
    from app.models import DiversityOptions

    result = ADMETOptimizer(property_registry).optimize(
        PREDICTIONS[:2],
        top_k=2,
        method="nsga3",
        smiles=["CCO", "c1ccccc1"],
        shared_intermediates=["batch-a", "batch-b"],
        diversity=DiversityOptions(enabled=True),
    )

    assert len(result.selected_indices) == 2
    assert {candidate.synthesis_batch for candidate in result.candidates} == {
        "batch-a",
        "batch-b",
    }
