from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from libs.schemas import Molecule

PhysicsMethod = Literal["fep_plus", "mm_gbsa", "openfe_alchemical"]


class PhysicsParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results_path: str = Field(min_length=1)
    allowed_methods: list[PhysicsMethod] = Field(min_length=1)
    max_binding_free_energy: float | None = None
    max_ligand_rmsd_angstrom: float = Field(default=2.0, gt=0)
    min_key_contact_persistence: float = Field(default=0.70, ge=0, le=1)
    min_residence_time_proxy: float | None = None
    require_off_target: bool = False
    top_k: int | None = Field(default=None, ge=1)

    @field_validator(
        "max_binding_free_energy",
        "max_ligand_rmsd_angstrom",
        "min_key_contact_persistence",
        "min_residence_time_proxy",
    )
    @classmethod
    def finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("physics thresholds must be finite")
        return value


class PhysicsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    molecules: list[Molecule] = Field(min_length=1, max_length=10_000)
    parameters: PhysicsParameters


class ScoreResponse(BaseModel):
    molecules: list[Molecule]


class FilterResponse(BaseModel):
    passed: list[Molecule]
    rejected: list[Molecule]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    backend: Literal["validated_external_results"] = "validated_external_results"


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"
