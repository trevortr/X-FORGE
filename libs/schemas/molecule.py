from __future__ import annotations

import hashlib
import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def molecule_id(smiles: str) -> str:
    """Return the project-wide stable identifier for a normalized SMILES string."""
    return hashlib.sha256(smiles.encode("utf-8")).hexdigest()[:16]


class ScoreRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str = Field(min_length=1)
    values: dict[str, float] = Field(default_factory=dict)
    passed: bool | None = None
    computed_at_iteration: int = Field(ge=0)

    @field_validator("values")
    @classmethod
    def values_must_be_finite(cls, values: dict[str, float]) -> dict[str, float]:
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError("score values must be finite")
        return values


class Molecule(BaseModel):
    """The append-only molecule envelope passed through the pipeline."""

    model_config = ConfigDict(extra="allow")

    smiles: str = Field(min_length=1, max_length=10_000)
    id: str | None = None
    parent_id: str | None = None
    iteration: int = Field(default=0, ge=0)
    scores: list[ScoreRecord] = Field(default_factory=list)

    @field_validator("smiles")
    @classmethod
    def smiles_must_fit_one_line(cls, value: str) -> str:
        value = value.strip()
        if not value or "\n" in value or "\r" in value:
            raise ValueError("SMILES must be a non-empty single-line string")
        return value

    @model_validator(mode="after")
    def supply_id(self) -> Molecule:
        if self.id is None:
            self.id = molecule_id(self.smiles)
        return self

    def with_score(self, score: ScoreRecord, **updates: Any) -> Molecule:
        """Return a new snapshot while preserving the existing score prefix."""
        return self.model_copy(
            update={
                **updates,
                "scores": [*self.scores, score],
            },
            deep=True,
        )
