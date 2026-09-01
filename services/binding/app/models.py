from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from libs.schemas import Molecule


class CriticalInteraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    residue: str = Field(min_length=1, examples=["ARG120.A"])
    interaction_types: list[str] = Field(min_length=1)


class OffTargetParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    receptor_pdbqt: str = Field(min_length=1)
    receptor_pdb: str = Field(min_length=1)
    box_center: tuple[float, float, float]
    box_size: tuple[float, float, float]

    @field_validator("box_center", "box_size")
    @classmethod
    def coordinates_must_be_finite(
        cls, value: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        if any(not math.isfinite(component) for component in value):
            raise ValueError("off-target box coordinates must be finite")
        return value

    @field_validator("box_size")
    @classmethod
    def box_dimensions_must_be_positive(
        cls, value: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        if any(component <= 0 for component in value):
            raise ValueError("off-target box dimensions must be greater than zero")
        return value


class BindingParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receptor_pdbqt: str = Field(min_length=1)
    receptor_pdb: str = Field(min_length=1)
    box_center: tuple[float, float, float]
    box_size: tuple[float, float, float]
    exhaustiveness: int = Field(default=4, ge=1, le=64)
    num_poses: int = Field(default=3, ge=1, le=20)
    energy_range: float = Field(default=3.0, gt=0, le=20)
    cpu: int = Field(default=1, ge=1, le=64)
    random_seed: int = Field(default=42, ge=0)
    max_vina_score: float = 0.0
    min_ligand_efficiency: float = 0.0
    min_lipe_proxy: float | None = None
    critical_interactions: list[CriticalInteraction] = Field(default_factory=list)
    critical_mode: Literal["all", "any"] = "all"
    interaction_types: list[str] | None = None
    temperature_kelvin: float = Field(default=298.15, gt=0)
    conformer_count: int = Field(default=20, ge=1, le=200)
    conformer_prune_rms_angstrom: float = Field(default=0.5, gt=0)
    max_internal_strain_kcal_mol: float = Field(default=6.0, gt=0)
    off_targets: list[OffTargetParameters] = Field(default_factory=list)
    min_selectivity_gap_target_minus_offtarget: float | None = None

    @field_validator("box_center", "box_size")
    @classmethod
    def coordinates_must_be_finite(
        cls, value: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        if any(not math.isfinite(component) for component in value):
            raise ValueError("box coordinates must be finite")
        return value

    @field_validator("box_size")
    @classmethod
    def box_dimensions_must_be_positive(
        cls, value: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        if any(component <= 0 for component in value):
            raise ValueError("box dimensions must be greater than zero")
        return value

    @field_validator(
        "max_vina_score",
        "min_ligand_efficiency",
        "min_lipe_proxy",
        "energy_range",
        "temperature_kelvin",
        "conformer_prune_rms_angstrom",
        "max_internal_strain_kcal_mol",
        "min_selectivity_gap_target_minus_offtarget",
    )
    @classmethod
    def thresholds_must_be_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("binding thresholds must be finite")
        return value


class BindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    molecules: list[Molecule] = Field(min_length=1, max_length=1_000)
    parameters: BindingParameters


class ScoreResponse(BaseModel):
    molecules: list[Molecule]


class FilterResponse(BaseModel):
    passed: list[Molecule]
    rejected: list[Molecule]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    rdkit: str
    meeko: str
    vina: str
    prolif: str


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"
