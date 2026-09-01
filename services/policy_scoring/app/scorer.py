from __future__ import annotations

import math
from dataclasses import dataclass

from rdkit import Chem, DataStructs
from rdkit.Chem import Crippen, Descriptors, QED, rdFingerprintGenerator
from rdkit.Contrib.SA_Score import sascorer

from libs.schemas import Molecule

from .models import DesirabilityCurve, PolicyScoringParameters


@dataclass(frozen=True)
class PolicyScore:
    values: dict[str, float]
    desirabilities: dict[str, float]
    passed: bool
    error: str | None = None


def evaluate_curve(value: float, curve: DesirabilityCurve) -> float:
    """Evaluate a continuous piecewise-linear desirability curve."""
    points = curve.points
    if value <= points[0].x:
        return points[0].desirability
    if value >= points[-1].x:
        return points[-1].desirability
    for left, right in zip(points, points[1:]):
        if value <= right.x:
            fraction = (value - left.x) / (right.x - left.x)
            return left.desirability + fraction * (
                right.desirability - left.desirability
            )
    raise AssertionError("validated curve did not bracket value")


def weighted_geometric_mean(
    desirabilities: dict[str, float], weights: dict[str, float]
) -> float:
    """D = (product(d_i ** w_i)) ** (1 / sum(w_i)), evaluated stably."""
    if any(desirabilities[key] <= 0.0 for key in weights):
        return 0.0
    total_weight = sum(weights.values())
    return math.exp(
        sum(weights[key] * math.log(desirabilities[key]) for key in weights)
        / total_weight
    )


class MorganKNNQSAR:
    """A target-specific ECFP k-nearest-neighbour affinity surrogate."""

    def __init__(self, parameters: PolicyScoringParameters) -> None:
        self.parameters = parameters
        self.generator = rdFingerprintGenerator.GetMorganGenerator(
            radius=2, fpSize=2048
        )
        self.examples: list[tuple[object, float]] = []
        for example in parameters.affinity_training_set:
            molecule = Chem.MolFromSmiles(example.smiles)
            if molecule is None:
                raise ValueError(f"invalid affinity training SMILES: {example.smiles}")
            self.examples.append(
                (self.generator.GetFingerprint(molecule), example.value)
            )

    def predict(self, molecule: Chem.Mol) -> float:
        fingerprint = self.generator.GetFingerprint(molecule)
        neighbours = sorted(
            (
                (float(DataStructs.TanimotoSimilarity(fingerprint, reference)), value)
                for reference, value in self.examples
            ),
            reverse=True,
        )[: self.parameters.affinity_k]
        powered = [
            (max(similarity, 1e-6) ** self.parameters.affinity_similarity_power, value)
            for similarity, value in neighbours
        ]
        denominator = sum(weight for weight, _ in powered)
        return sum(weight * value for weight, value in powered) / denominator


class PolicyScorer:
    def score_batch(
        self, molecules: list[Molecule], parameters: PolicyScoringParameters
    ) -> list[PolicyScore]:
        surrogate = MorganKNNQSAR(parameters)
        scored = [self._score(molecule, parameters, surrogate) for molecule in molecules]
        eligible = [
            index
            for index, result in enumerate(scored)
            if result.passed
        ]
        eligible.sort(
            key=lambda index: (
                -scored[index].values["composite_desirability"],
                molecules[index].id or "",
            )
        )
        if parameters.top_k is not None:
            selected = set(eligible[: parameters.top_k])
            scored = [
                PolicyScore(
                    values=result.values,
                    desirabilities=result.desirabilities,
                    passed=result.passed and index in selected,
                    error=result.error,
                )
                for index, result in enumerate(scored)
            ]
        return scored

    @staticmethod
    def _score(
        molecule: Molecule,
        parameters: PolicyScoringParameters,
        surrogate: MorganKNNQSAR,
    ) -> PolicyScore:
        try:
            rd_molecule = Chem.MolFromSmiles(molecule.smiles)
            if rd_molecule is None:
                raise ValueError("RDKit could not parse SMILES")
            values = {
                "target_affinity_surrogate": surrogate.predict(rd_molecule),
                "qed": float(QED.qed(rd_molecule)),
                "sascore": float(sascorer.calculateScore(rd_molecule)),
                "clogp": float(Crippen.MolLogP(rd_molecule)),
                "molecular_weight": float(Descriptors.MolWt(rd_molecule)),
            }
            desirabilities = {
                key: evaluate_curve(value, parameters.curves[key])
                for key, value in values.items()
            }
            composite = weighted_geometric_mean(
                desirabilities, parameters.weights
            )
            values = {**values, "composite_desirability": composite}
            return PolicyScore(
                values=values,
                desirabilities=desirabilities,
                passed=composite >= parameters.min_composite_desirability,
            )
        except Exception as exc:
            return PolicyScore(
                values={"composite_desirability": 0.0},
                desirabilities={},
                passed=False,
                error=f"{type(exc).__name__}: {exc}",
            )
