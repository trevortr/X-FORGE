from __future__ import annotations

import hashlib
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SelectionMethod = Literal[
    "knee_point",
    "desirability",
    "hypervolume_contribution",
]


def molecule_id(smiles: str) -> str:
    return hashlib.sha256(smiles.encode("utf-8")).hexdigest()[:16]


class MoleculeInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    smiles: str = Field(min_length=1, max_length=10_000)
    id: str | None = None
    parent_id: str | None = None
    iteration: int = Field(default=0, ge=0)
    scores: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("smiles")
    @classmethod
    def smiles_must_fit_one_line(cls, value: str) -> str:
        value = value.strip()
        if not value or "\n" in value or "\r" in value:
            raise ValueError("SMILES must be a non-empty single-line string")
        return value

    @model_validator(mode="after")
    def supply_id(self) -> MoleculeInput:
        if self.id is None:
            self.id = molecule_id(self.smiles)
        return self


class SelectionOptions(BaseModel):
    method: SelectionMethod = "knee_point"
    weights: dict[str, float] | None = None
    reference_point: dict[str, float] | None = None

    @field_validator("weights")
    @classmethod
    def validate_weights(
        cls, value: dict[str, float] | None
    ) -> dict[str, float] | None:
        if value is not None and any(
            not math.isfinite(weight) or weight <= 0 for weight in value.values()
        ):
            raise ValueError("weights must be finite and greater than zero")
        return value

    @field_validator("reference_point")
    @classmethod
    def validate_reference_point(
        cls, value: dict[str, float] | None
    ) -> dict[str, float] | None:
        if value is not None and any(
            not math.isfinite(point) for point in value.values()
        ):
            raise ValueError("reference point values must be finite")
        return value


class OptimizeRequest(BaseModel):
    molecules: list[MoleculeInput] = Field(min_length=1, max_length=1_000)
    top_k: int = Field(default=10, ge=1, le=1_000)
    properties: list[str] | None = None
    selection: SelectionOptions = Field(default_factory=SelectionOptions)


class PropertyMetadata(BaseModel):
    key: str
    source_column: str
    display_name: str
    category: str
    units: str
    goal: Literal["maximize", "minimize"]
    desirability: str


class EvaluatedMolecule(MoleculeInput):
    admet_predictions: dict[str, float]
    objectives: dict[str, float]
    desirabilities: dict[str, float]
    pareto_rank: int
    selection_score: float | None
    selected: bool


class OptimizeResponse(BaseModel):
    molecules: list[EvaluatedMolecule]
    selected: list[EvaluatedMolecule]
    pareto_front: list[EvaluatedMolecule]
    selection_method: SelectionMethod
    properties: list[PropertyMetadata]


class HealthResponse(BaseModel):
    status: Literal["ok", "not_ready"]
    model_loaded: bool
    device: str | None = None
    detail: str | None = None


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"
