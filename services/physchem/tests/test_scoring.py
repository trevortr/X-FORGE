from __future__ import annotations

import json

from app.models import PhyschemParameters
from app.scorer import PhyschemScorer
from libs.schemas import Molecule


def parameters(**updates) -> PhyschemParameters:
    return PhyschemParameters(
        require_retrosynthesis=False,
        min_heavy_atoms=1,
        **updates,
    )


def test_lipinski_veber_and_liability_metrics_are_recorded() -> None:
    result = PhyschemScorer().score_batch(
        [Molecule(smiles="CCO")], parameters()
    )[0]

    assert result.passed is True
    assert result.values["lipinski_pass"] == 1.0
    assert result.values["veber_pass"] == 1.0
    assert result.values["formal_charge"] == 0.0
    assert result.values["pains_count"] == 0.0


def test_reactive_warhead_is_rejected_unless_covalent_project() -> None:
    molecule = Molecule(smiles="CC(=O)Cl")
    rejected = PhyschemScorer().score_batch([molecule], parameters())[0]
    accepted = PhyschemScorer().score_batch(
        [molecule], parameters(allow_covalent_warheads=True)
    )[0]

    assert "acyl_halide" in rejected.details["warhead_alerts"]
    assert rejected.passed is False
    assert accepted.values["warhead_count"] >= 1.0


def test_external_route_and_pka_evidence_are_gated_and_retained(tmp_path) -> None:
    molecule = Molecule(smiles="CCN", predicted_basic_pka=9.5)
    routes = tmp_path / "routes.json"
    routes.write_text(
        json.dumps(
            {
                molecule.id: {
                    "route_confidence": 0.8,
                    "route_steps": 3,
                    "shared_intermediate_id": "amine-core",
                }
            }
        ),
        encoding="utf-8",
    )

    result = PhyschemScorer().score_batch(
        [molecule],
        PhyschemParameters(
            min_heavy_atoms=1,
            require_pka_prediction=True,
            max_basic_pka=10.5,
            route_results_path=str(routes),
        ),
    )[0]

    assert result.passed is True
    assert result.values["pka_pass"] == 1.0
    assert result.values["retrosynthesis_pass"] == 1.0
    assert result.details["shared_intermediate_id"] == "amine-core"
