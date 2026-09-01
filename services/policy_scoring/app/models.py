from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from libs.schemas import Molecule


class CurvePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    desirability: float = Field(ge=0.0, le=1.0)

    @field_validator("x", "desirability")
    @classmethod
    def finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("curve values must be finite")
        return value


class DesirabilityCurve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    points: list[CurvePoint] = Field(min_length=2)

    @model_validator(mode="after")
    def strictly_increasing(self) -> DesirabilityCurve:
        xs = [point.x for point in self.points]
        if any(right <= left for left, right in zip(xs, xs[1:])):
            raise ValueError("curve point x values must be strictly increasing")
        return self


class AffinityExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    smiles: str = Field(min_length=1)
    value: float

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("affinity values must be finite")
        return value


def _curve(points: list[tuple[float, float]]) -> DesirabilityCurve:
    return DesirabilityCurve(
        points=[CurvePoint(x=x, desirability=d) for x, d in points]
    )


class PolicyScoringParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    affinity_training_set: list[AffinityExample] = Field(min_length=1)
    affinity_k: int = Field(default=5, ge=1, le=100)
    affinity_similarity_power: float = Field(default=2.0, gt=0.0, le=10.0)
    curves: dict[str, DesirabilityCurve] = Field(
        default_factory=lambda: {
            "target_affinity_surrogate": _curve(
                [(-14.0, 1.0), (-10.0, 1.0), (-6.0, 0.2), (-4.0, 0.0)]
            ),
            "qed": _curve([(0.0, 0.0), (0.35, 0.25), (0.65, 1.0), (1.0, 1.0)]),
            "sascore": _curve([(1.0, 1.0), (3.0, 1.0), (6.0, 0.25), (10.0, 0.0)]),
            "clogp": _curve([(-2.0, 0.0), (1.0, 1.0), (3.0, 1.0), (5.0, 0.0)]),
            "molecular_weight": _curve(
                [(100.0, 0.0), (250.0, 1.0), (450.0, 1.0), (650.0, 0.0)]
            ),
        }
    )
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "target_affinity_surrogate": 1.0,
            "qed": 1.0,
            "sascore": 1.0,
            "clogp": 1.0,
            "molecular_weight": 1.0,
        }
    )
    min_composite_desirability: float = Field(default=0.0, ge=0.0, le=1.0)
    top_k: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def matching_metrics(self) -> PolicyScoringParameters:
        required = {
            "target_affinity_surrogate",
            "qed",
            "sascore",
            "clogp",
            "molecular_weight",
        }
        if set(self.curves) != required or set(self.weights) != required:
            raise ValueError(f"curves and weights must define exactly {sorted(required)}")
        if any(not math.isfinite(weight) or weight <= 0 for weight in self.weights.values()):
            raise ValueError("all desirability weights must be finite and positive")
        return self


class PolicyScoringRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    molecules: list[Molecule] = Field(min_length=1, max_length=100_000)
    parameters: PolicyScoringParameters


class ScoreResponse(BaseModel):
    molecules: list[Molecule]


class FilterResponse(BaseModel):
    passed: list[Molecule]
    rejected: list[Molecule]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    rdkit: str
    affinity_surrogate: str = "morgan_knn_qsar"


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"
