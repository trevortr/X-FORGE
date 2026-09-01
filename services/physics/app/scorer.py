from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from libs.schemas import Molecule

from .models import PhysicsParameters


@dataclass(frozen=True)
class PhysicsScore:
    values: dict[str, float]
    details: dict[str, Any]
    passed: bool
    error: str | None = None


class PhysicsScorer:
    """Validate results produced by an external FEP/MM-GBSA and MD engine."""

    REQUIRED_NUMERIC = (
        "binding_free_energy_kcal_mol",
        "ligand_rmsd_angstrom",
        "key_contact_persistence",
    )

    def score_batch(
        self, molecules: list[Molecule], parameters: PhysicsParameters
    ) -> list[PhysicsScore]:
        evidence = self._load(parameters.results_path)
        scored = [
            self._score(molecule, parameters, evidence)
            for molecule in molecules
        ]
        eligible = [index for index, result in enumerate(scored) if result.passed]
        eligible.sort(
            key=lambda index: (
                scored[index].values["binding_free_energy_kcal_mol"],
                -scored[index].values["key_contact_persistence"],
                scored[index].values["ligand_rmsd_angstrom"],
                molecules[index].id or "",
            )
        )
        if parameters.top_k is not None:
            retained = set(eligible[: parameters.top_k])
            scored = [
                PhysicsScore(
                    values=result.values,
                    details=result.details,
                    passed=result.passed and index in retained,
                    error=result.error,
                )
                for index, result in enumerate(scored)
            ]
        return scored

    @staticmethod
    def _load(path: str) -> dict[str, dict[str, Any]]:
        source = Path(path)
        if not source.is_file():
            raise ValueError(f"physics result file does not exist: {source}")
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("physics result file must be an object keyed by molecule")
        return {
            str(key): value
            for key, value in payload.items()
            if isinstance(value, dict)
        }

    def _score(
        self,
        molecule: Molecule,
        parameters: PhysicsParameters,
        evidence: dict[str, dict[str, Any]],
    ) -> PhysicsScore:
        try:
            result = evidence.get(molecule.id or "") or evidence.get(molecule.smiles)
            if result is None:
                raise ValueError("no high-fidelity result exists for molecule")
            method = result.get("method")
            if method not in parameters.allowed_methods:
                raise ValueError(f"unapproved or missing physics method: {method!r}")
            values = {
                key: self._finite(result, key) for key in self.REQUIRED_NUMERIC
            }
            if not 0.0 <= values["key_contact_persistence"] <= 1.0:
                raise ValueError("key_contact_persistence must be within [0, 1]")
            for optional in (
                "off_target_binding_free_energy_kcal_mol",
                "residence_time_proxy",
                "binding_free_energy_uncertainty_kcal_mol",
            ):
                if optional in result:
                    values[optional] = self._finite(result, optional)
            off_target = values.get("off_target_binding_free_energy_kcal_mol")
            if parameters.require_off_target and off_target is None:
                raise ValueError("off-target free energy is required")
            if off_target is not None:
                values["selectivity_gap_target_minus_offtarget"] = (
                    values["binding_free_energy_kcal_mol"] - off_target
                )
                values["selectivity_gap_offtarget_minus_target"] = (
                    off_target - values["binding_free_energy_kcal_mol"]
                )
            passed = (
                values["ligand_rmsd_angstrom"]
                < parameters.max_ligand_rmsd_angstrom
                and values["key_contact_persistence"]
                > parameters.min_key_contact_persistence
                and (
                    parameters.max_binding_free_energy is None
                    or values["binding_free_energy_kcal_mol"]
                    <= parameters.max_binding_free_energy
                )
                and (
                    parameters.min_residence_time_proxy is None
                    or values.get("residence_time_proxy", -math.inf)
                    >= parameters.min_residence_time_proxy
                )
            )
            return PhysicsScore(
                values={**values, "physics_evidence_available": 1.0},
                details={
                    "method": method,
                    "protocol": result.get("protocol"),
                    "engine_version": result.get("engine_version"),
                    "trajectory_id": result.get("trajectory_id"),
                },
                passed=passed,
            )
        except Exception as exc:
            return PhysicsScore(
                values={"physics_evidence_available": 0.0},
                details={},
                passed=False,
                error=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _finite(result: dict[str, Any], key: str) -> float:
        if key not in result:
            raise ValueError(f"physics result is missing {key}")
        value = float(result[key])
        if not math.isfinite(value):
            raise ValueError(f"physics result {key} must be finite")
        return value
