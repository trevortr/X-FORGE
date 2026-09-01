from __future__ import annotations

import hashlib
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SelectionMethod = Literal[
    "knee_point",
    "desirability",
    "hypervolume_contribution",
    "nsga3",
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


class ADMETScreenParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    solubility_column: str = "Solubility_AqSolDB"
    min_log_s: float = -4.0
    microsomal_clearance_column: str | None = "Clearance_Microsome_AZ"
    max_microsomal_clint: float | None = None
    hepatocyte_clearance_column: str | None = "Clearance_Hepatocyte_AZ"
    max_hepatocyte_clint: float | None = None
    half_life_column: str | None = "Half_Life_Obach"
    min_half_life: float | None = None
    caco2_log_papp_column: str | None = "Caco2_Wang"
    mdck_log_papp_column: str | None = None
    # ADMET-AI Caco2_Wang is log10(Papp / (10^-6 cm/s)); > 0 means Papp > 10^-6.
    min_log_papp: float = 0.0
    pgp_efflux_ratio_column: str | None = None
    max_pgp_efflux_ratio: float = 2.5
    pgp_risk_column: str | None = "Pgp_Broccatelli"
    max_pgp_risk: float = 0.5
    herg_pic50_column: str | None = None
    max_herg_pic50: float = 5.0
    herg_risk_column: str | None = "hERG"
    max_herg_risk: float = 0.5
    cyp_risk_columns: dict[str, str] = Field(
        default_factory=lambda: {
            "cyp3a4": "CYP3A4_Veith",
            "cyp2d6": "CYP2D6_Veith",
            "cyp2c9": "CYP2C9_Veith",
        }
    )
    max_cyp_risk: float = 0.5
    max_candidates: int | None = Field(default=None, ge=1)

    @field_validator(
        "min_log_s",
        "max_microsomal_clint",
        "max_hepatocyte_clint",
        "min_half_life",
        "min_log_papp",
        "max_pgp_efflux_ratio",
        "max_pgp_risk",
        "max_herg_pic50",
        "max_herg_risk",
        "max_cyp_risk",
    )
    @classmethod
    def finite_screen_thresholds(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("ADMET screen thresholds must be finite")
        return value


class ADMETScreenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    molecules: list[MoleculeInput] = Field(min_length=1, max_length=100_000)
    parameters: ADMETScreenParameters = Field(default_factory=ADMETScreenParameters)


class ScreenScoreResponse(BaseModel):
    molecules: list[MoleculeInput]


class ScreenFilterResponse(BaseModel):
    passed: list[MoleculeInput]
    rejected: list[MoleculeInput]


class DiversityOptions(BaseModel):
    enabled: bool = False
    tanimoto_distance_threshold: float = Field(default=0.4, gt=0, le=1)
    morgan_radius: int = Field(default=2, ge=1, le=4)
    fingerprint_bits: int = Field(default=2048, ge=128, le=8192)


class SelectionOptions(BaseModel):
    method: SelectionMethod = "knee_point"
    weights: dict[str, float] | None = None
    reference_point: dict[str, float] | None = None
    nsga3_reference_partitions: int = Field(default=4, ge=1, le=20)
    diversity: DiversityOptions = Field(default_factory=DiversityOptions)

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
    scaffold_cluster: int | None = None
    synthesis_batch: str | None = None


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
