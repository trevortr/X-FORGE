from __future__ import annotations

import json

from app.models import PhysicsParameters
from app.scorer import PhysicsScorer
from libs.schemas import Molecule


def test_physics_gate_requires_method_energy_and_md_evidence(tmp_path) -> None:
    molecule = Molecule(smiles="CCO")
    path = tmp_path / "physics.json"
    path.write_text(
        json.dumps(
            {
                molecule.id: {
                    "method": "openfe_alchemical",
                    "binding_free_energy_kcal_mol": -9.0,
                    "off_target_binding_free_energy_kcal_mol": -5.0,
                    "ligand_rmsd_angstrom": 1.4,
                    "key_contact_persistence": 0.8,
                    "protocol": "rbfe-v1",
                }
            }
        ),
        encoding="utf-8",
    )

    result = PhysicsScorer().score_batch(
        [molecule],
        PhysicsParameters(
            results_path=str(path),
            allowed_methods=["openfe_alchemical"],
            require_off_target=True,
        ),
    )[0]

    assert result.passed is True
    assert result.values["selectivity_gap_target_minus_offtarget"] == -4.0


def test_missing_evidence_is_rejected_not_replaced_by_a_proxy(tmp_path) -> None:
    path = tmp_path / "physics.json"
    path.write_text("{}", encoding="utf-8")
    result = PhysicsScorer().score_batch(
        [Molecule(smiles="CCO")],
        PhysicsParameters(results_path=str(path), allowed_methods=["mm_gbsa"]),
    )[0]

    assert result.passed is False
    assert result.values["physics_evidence_available"] == 0.0
