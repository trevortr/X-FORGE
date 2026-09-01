from __future__ import annotations

import pytest

from app.models import BindingParameters
from app.scorer import evaluate_metrics


def _parameters(**updates) -> BindingParameters:
    return BindingParameters(
        receptor_pdbqt="/target/receptor.pdbqt",
        receptor_pdb="/target/receptor.pdb",
        box_center=(1.0, 2.0, 3.0),
        box_size=(20.0, 20.0, 20.0),
        max_vina_score=-7.0,
        min_ligand_efficiency=0.3,
        min_lipe_proxy=1.0,
        critical_interactions=[
            {
                "residue": "ARG120.A",
                "interaction_types": ["HBAcceptor", "Anionic"],
            }
        ],
        **updates,
    )


def test_composite_metrics_pass_when_every_configured_gate_passes() -> None:
    values, passed = evaluate_metrics(
        vina_score=-8.0,
        heavy_atom_count=20,
        clogp=2.0,
        interactions={"HBAcceptor:ARG120.A", "Hydrophobic:VAL349.A"},
        parameters=_parameters(),
    )

    assert passed is True
    assert values["vina_ligand_efficiency"] == pytest.approx(0.4)
    assert values["vina_pkd_proxy"] > 5.0
    assert values["vina_lipe_proxy"] > 3.0
    assert values["critical_interaction_fraction"] == 1.0
    assert 0.0 < values["binding_desirability"] <= 1.0


def test_critical_interaction_and_efficiency_are_independent_gates() -> None:
    values, passed = evaluate_metrics(
        vina_score=-7.5,
        heavy_atom_count=30,
        clogp=2.0,
        interactions={"Hydrophobic:ARG120.A"},
        parameters=_parameters(),
    )

    assert passed is False
    assert values["vina_ligand_efficiency"] == pytest.approx(0.25)
    assert values["critical_interaction_fraction"] == 0.0


def test_internal_strain_and_off_target_selectivity_are_gated() -> None:
    values, passed = evaluate_metrics(
        vina_score=-8.0,
        heavy_atom_count=20,
        clogp=2.0,
        interactions={"HBAcceptor:ARG120.A"},
        parameters=_parameters(
            max_internal_strain_kcal_mol=5.0,
            min_selectivity_gap_target_minus_offtarget=-3.0,
        ),
        internal_strain=6.0,
        off_target_score=-5.0,
    )

    assert passed is False
    assert values["internal_ligand_strain_kcal_mol"] == 6.0
    assert values["selectivity_gap_target_minus_offtarget"] == -3.0
