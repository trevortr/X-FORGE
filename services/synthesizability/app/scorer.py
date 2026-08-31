from __future__ import annotations

import math
import os
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from rdkit import Chem
from rdkit.Chem import rdFingerprintGenerator
from rdkit.Contrib.SA_Score import sascorer

from libs.schemas import Molecule

from .models import SynthesizabilityParameters

DEFAULT_RASCORE_MODEL_PATH = "/opt/rascore/XGB_chembl_ecfp_counts/model.pkl"
EPSILON = 1e-12


class RAScoreBackend(Protocol):
    model_path: Path

    def predict(self, molecule: Chem.Mol) -> float: ...


class RAScorePredictor:
    """Load the trusted upstream XGBoost pickle and reproduce its ECFP6 input."""

    def __init__(self, model_path: str | Path | None = None) -> None:
        self.model_path = Path(
            model_path or os.getenv("RASCORE_MODEL_PATH") or DEFAULT_RASCORE_MODEL_PATH
        )
        if not self.model_path.is_file():
            raise FileNotFoundError(f"RA-Score model does not exist: {self.model_path}")
        with self.model_path.open("rb") as handle:
            self._model = pickle.load(handle)  # noqa: S301 - pinned, checksummed model
        if not callable(getattr(self._model, "predict_proba", None)):
            raise TypeError("RA-Score model does not provide predict_proba")
        self._fingerprints = rdFingerprintGenerator.GetMorganGenerator(
            radius=3,
            fpSize=2048,
        )

    def predict(self, molecule: Chem.Mol) -> float:
        fingerprint = self._fingerprints.GetCountFingerprintAsNumPy(molecule)
        probability = self._model.predict_proba(fingerprint.reshape(1, -1))[0][1]
        return float(probability)


@dataclass(frozen=True)
class SynthesizabilityResult:
    values: dict[str, float]
    passed: bool
    error: str | None = None


def _logistic(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)


def evaluate_activation(
    *,
    rascore: float,
    sascore: float,
    parameters: SynthesizabilityParameters,
) -> tuple[dict[str, float], bool]:
    """Combine RA-Score and SAscore through a sigmoid-gated p=-2 mean."""
    if not math.isfinite(rascore) or not math.isfinite(sascore):
        raise ValueError("RA-Score and SAscore must be finite")

    rascore_desirability = min(max(rascore, EPSILON), 1.0)
    sascore_desirability = (parameters.sascore_worst - sascore) / (
        parameters.sascore_worst - parameters.sascore_best
    )
    sascore_desirability = min(max(sascore_desirability, EPSILON), 1.0)

    total_weight = parameters.rascore_weight + parameters.sascore_weight
    power_mean = (
        (
            parameters.rascore_weight * rascore_desirability**parameters.power
            + parameters.sascore_weight * sascore_desirability**parameters.power
        )
        / total_weight
    ) ** (1.0 / parameters.power)
    activation = _logistic(
        parameters.gate_steepness * (power_mean - parameters.gate_midpoint)
    )
    passed = activation >= parameters.min_activation
    values = {
        "scoring_succeeded": 1.0,
        "rascore": rascore,
        "sascore": sascore,
        "rascore_desirability": rascore_desirability,
        "sascore_desirability": sascore_desirability,
        "power_mean_p_neg2": power_mean,
        "synthesizability_activation": activation,
    }
    return values, passed


class SynthesizabilityScorer:
    def __init__(self, rascore: RAScoreBackend | None = None) -> None:
        self.rascore = rascore or RAScorePredictor()

    def score_batch(
        self,
        molecules: list[Molecule],
        parameters: SynthesizabilityParameters,
    ) -> list[SynthesizabilityResult]:
        return [self._score_molecule(molecule, parameters) for molecule in molecules]

    def _score_molecule(
        self,
        molecule: Molecule,
        parameters: SynthesizabilityParameters,
    ) -> SynthesizabilityResult:
        try:
            rdkit_molecule = Chem.MolFromSmiles(molecule.smiles)
            if rdkit_molecule is None:
                raise ValueError("RDKit could not parse SMILES")
            rascore = self.rascore.predict(rdkit_molecule)
            sascore = float(sascorer.calculateScore(rdkit_molecule))
            values, passed = evaluate_activation(
                rascore=rascore,
                sascore=sascore,
                parameters=parameters,
            )
            return SynthesizabilityResult(values=values, passed=passed)
        except Exception as exc:  # reject one invalid molecule, not the batch
            return SynthesizabilityResult(
                values={
                    "scoring_succeeded": 0.0,
                    "synthesizability_activation": 0.0,
                },
                passed=False,
                error=f"{type(exc).__name__}: {exc}",
            )
