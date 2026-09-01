from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from libs.schemas import Molecule


class PhyschemParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_molecular_weight: float = Field(default=500.0, gt=0)
    max_clogp: float = 5.0
    max_hbond_donors: int = Field(default=5, ge=0)
    max_hbond_acceptors: int = Field(default=10, ge=0)
    max_tpsa: float = Field(default=140.0, gt=0)
    max_rotatable_bonds: int = Field(default=10, ge=0)
    min_formal_charge: int = -1
    max_formal_charge: int = 1
    min_heavy_atoms: int = Field(default=5, ge=1)
    max_heavy_atoms: int = Field(default=70, ge=1)
    allow_covalent_warheads: bool = False
    predicted_basic_pka_field: str = "predicted_basic_pka"
    min_basic_pka: float | None = None
    max_basic_pka: float | None = 10.5
    require_pka_prediction: bool = False
    require_retrosynthesis: bool = True
    building_blocks_path: str | None = None
    reaction_templates: list[str] = Field(default_factory=list)
    route_results_path: str | None = None
    min_route_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    max_route_steps: int = Field(default=6, ge=1)
    additional_warhead_smarts: list[str] = Field(default_factory=list)

    @field_validator(
        "max_molecular_weight",
        "max_clogp",
        "max_tpsa",
        "min_basic_pka",
        "max_basic_pka",
    )
    @classmethod
    def finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("physicochemical thresholds must be finite")
        return value

    @model_validator(mode="after")
    def valid_ranges(self) -> PhyschemParameters:
        if self.min_formal_charge > self.max_formal_charge:
            raise ValueError("formal-charge range is inverted")
        if self.min_heavy_atoms > self.max_heavy_atoms:
            raise ValueError("heavy-atom range is inverted")
        if (
            self.min_basic_pka is not None
            and self.max_basic_pka is not None
            and self.min_basic_pka > self.max_basic_pka
        ):
            raise ValueError("basic-pKa range is inverted")
        if self.require_retrosynthesis and not (
            self.building_blocks_path
            or self.reaction_templates
            or self.route_results_path
        ):
            raise ValueError(
                "retrosynthesis is required but no building-block catalog, "
                "reaction template, or route result source is configured"
            )
        return self


class PhyschemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    molecules: list[Molecule] = Field(min_length=1, max_length=100_000)
    parameters: PhyschemParameters


class ScoreResponse(BaseModel):
    molecules: list[Molecule]


class FilterResponse(BaseModel):
    passed: list[Molecule]
    rejected: list[Molecule]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    rdkit: str


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"
