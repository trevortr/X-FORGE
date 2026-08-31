from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from libs.schemas import Molecule


class SynthesizabilityParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    power: Literal[-2] = -2
    rascore_weight: float = Field(default=1.0, gt=0)
    sascore_weight: float = Field(default=1.0, gt=0)
    sascore_best: float = Field(default=1.0, ge=0)
    sascore_worst: float = Field(default=10.0, gt=0)
    gate_midpoint: float = Field(default=0.5, ge=0, le=1)
    gate_steepness: float = Field(default=12.0, gt=0, le=100)
    min_activation: float = Field(default=0.5, ge=0, le=1)

    @field_validator(
        "rascore_weight",
        "sascore_weight",
        "sascore_best",
        "sascore_worst",
        "gate_midpoint",
        "gate_steepness",
        "min_activation",
    )
    @classmethod
    def values_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("synthesizability parameters must be finite")
        return value

    @model_validator(mode="after")
    def sascore_range_must_increase(self) -> SynthesizabilityParameters:
        if self.sascore_worst <= self.sascore_best:
            raise ValueError("sascore_worst must be greater than sascore_best")
        return self


class SynthesizabilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    molecules: list[Molecule] = Field(min_length=1, max_length=10_000)
    parameters: SynthesizabilityParameters = Field(
        default_factory=SynthesizabilityParameters
    )


class ScoreResponse(BaseModel):
    molecules: list[Molecule]


class FilterResponse(BaseModel):
    passed: list[Molecule]
    rejected: list[Molecule]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    rdkit: str
    xgboost: str
    scikit_learn: str
    rascore_model: str


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"
