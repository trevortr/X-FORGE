from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from libs.schemas import Molecule


class FilterStageResult(BaseModel):
    stage: str
    parameters: dict[str, Any]
    input_count: int
    passed: list[Molecule]
    rejected: list[Molecule]


class IterationResult(BaseModel):
    iteration: int
    seeds: list[Molecule]
    requested_candidates: int
    generator_model: str | None = None
    generated: list[Molecule]
    filter_stages: list[FilterStageResult] = Field(default_factory=list)
    survivors: list[Molecule]
    evaluated: list[Molecule]
    pareto_front: list[Molecule]
    selected: list[Molecule]


class RunResult(BaseModel):
    run_id: str
    target: str
    status: Literal["running", "completed", "failed"]
    started_at: datetime
    completed_at: datetime | None = None
    requested_iterations: int
    completed_iterations: int
    termination_reason: str | None = None
    initial_seeds: list[Molecule]
    iterations: list[IterationResult] = Field(default_factory=list)
    final_selected: list[Molecule] = Field(default_factory=list)
    molecule_catalog: list[Molecule] = Field(default_factory=list)


class ResultWriter:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def write_iteration(self, iteration: IterationResult) -> Path:
        return self._write_json(
            self.output_dir / f"iteration_{iteration.iteration:03d}.json",
            iteration,
        )

    def write_run(self, result: RunResult) -> Path:
        return self._write_json(self.output_dir / "run.json", result)

    def _write_json(self, path: Path, value: BaseModel) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(value.model_dump_json(indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
        return path
