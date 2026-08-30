from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Seed:
    smiles: str
    id: str | None = None


@dataclass(frozen=True)
class GenerationJob:
    seeds: tuple[Seed, ...]
    n_candidates_per_seed: int
    strategy: str
    temperature: float
    random_seed: int


@dataclass(frozen=True)
class GeneratedCandidate:
    smiles: str
    id: str
    parent_smiles: str
    parent_id: str
    tanimoto: float | None = None
    nll: float | None = None


@dataclass(frozen=True)
class GenerationResult:
    molecules: tuple[GeneratedCandidate, ...]
    requested: int
    generated: int
    model: str


@dataclass(frozen=True)
class RuntimeReadiness:
    executable_available: bool
    model_available: bool
    runtime_available: bool
    detail: str | None = None
