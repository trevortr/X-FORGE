from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def molecule_id(smiles: str) -> str:
    """Return the stable identifier used until RDKit canonicalization is shared."""
    return hashlib.sha256(smiles.encode("utf-8")).hexdigest()[:16]


class SeedMolecule(BaseModel):
    smiles: str = Field(min_length=1, max_length=10_000)
    id: str | None = None

    @field_validator("smiles")
    @classmethod
    def smiles_must_fit_one_line(cls, value: str) -> str:
        value = value.strip()
        if not value or "\n" in value or "\r" in value:
            raise ValueError("SMILES must be a non-empty single-line string")
        return value


class GenerateRequest(BaseModel):
    seeds: list[SeedMolecule] = Field(min_length=1, max_length=100)
    n_candidates_per_seed: int = Field(default=100, ge=1, le=1_000)
    strategy: Literal["multinomial", "beamsearch"] = "multinomial"
    temperature: float = Field(default=1.0, ge=0.1, le=2.0)
    random_seed: int = Field(default=42, ge=0)


class GeneratedMolecule(BaseModel):
    smiles: str
    id: str
    parent_smiles: str
    parent_id: str
    tanimoto: float | None = None
    nll: float | None = None


class GenerateResponse(BaseModel):
    molecules: list[GeneratedMolecule]
    requested: int
    generated: int
    model: str


class HealthResponse(BaseModel):
    status: Literal["ok", "not_ready"]
    model_available: bool
    executable_available: bool
    runtime_available: bool
    detail: str | None = None


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"
