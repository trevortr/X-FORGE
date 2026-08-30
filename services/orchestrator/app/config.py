from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from libs.schemas import Molecule


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class PipelineStage:
    name: str
    parameters: dict[str, Any]


class GeneratorOptions(BaseModel):
    strategy: Literal["multinomial", "beamsearch"] = "multinomial"
    temperature: float = Field(default=1.0, ge=0.1, le=2.0)
    random_seed: int = Field(default=42, ge=0)


class SelectionOptions(BaseModel):
    method: Literal["knee_point", "desirability", "hypervolume_contribution"] = (
        "knee_point"
    )
    weights: dict[str, float] | None = None
    reference_point: dict[str, float] | None = None


class ADMETOptions(BaseModel):
    properties: list[str] | None = None
    selection: SelectionOptions = Field(default_factory=SelectionOptions)


class HTTPOptions(BaseModel):
    timeout_seconds: float = Field(default=900.0, gt=0)
    max_attempts: int = Field(default=5, ge=1, le=20)
    backoff_seconds: float = Field(default=1.0, ge=0, le=60)


class PipelineFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = "targets/example_target.yaml"
    pipeline: list[dict[str, dict[str, Any] | None]] = Field(default_factory=list)
    iterations: int = Field(default=3, ge=1, le=100)
    candidates_per_iteration: int = Field(default=10, ge=1, le=1_000)
    top_k_feedback: int = Field(default=3, ge=1, le=1_000)
    generator: GeneratorOptions = Field(default_factory=GeneratorOptions)
    admet_moo: ADMETOptions = Field(default_factory=ADMETOptions)
    http: HTTPOptions = Field(default_factory=HTTPOptions)
    output_dir: str = "results/example_run"


class TargetFile(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1)
    seeds: list[Molecule] = Field(min_length=1, max_length=100)


class ServicesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    services: dict[str, str]

    @field_validator("services")
    @classmethod
    def service_urls_must_be_http(cls, services: dict[str, str]) -> dict[str, str]:
        for name, url in services.items():
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"service {name!r} must have an HTTP URL")
        return {name: url.rstrip("/") for name, url in services.items()}


@dataclass(frozen=True)
class RunConfiguration:
    target: TargetFile
    stages: tuple[PipelineStage, ...]
    services: dict[str, str]
    iterations: int
    candidates_per_iteration: int
    top_k_feedback: int
    generator: GeneratorOptions
    admet_moo: ADMETOptions
    http: HTTPOptions
    output_dir: Path


class ConfigurationLoader:
    _stage_name = re.compile(r"^[a-z][a-z0-9_-]*$")

    @classmethod
    def load(
        cls,
        pipeline_path: Path,
        services_path: Path,
        *,
        output_override: Path | None = None,
    ) -> RunConfiguration:
        pipeline = PipelineFile.model_validate(cls._read_yaml(pipeline_path))
        service_file = ServicesFile.model_validate(cls._read_yaml(services_path))
        target_path = Path(pipeline.target)
        if not target_path.is_absolute():
            target_path = pipeline_path.parent / target_path
        target = TargetFile.model_validate(cls._read_yaml(target_path))
        stages = cls._parse_stages(pipeline.pipeline)

        required = {"generator", "admet_moo", *(stage.name for stage in stages)}
        missing = sorted(required - service_file.services.keys())
        if missing:
            raise ConfigurationError(
                f"services.yaml is missing required services: {', '.join(missing)}"
            )

        configured_output = Path(
            output_override or os.getenv("XFORGE_OUTPUT_DIR") or pipeline.output_dir
        )
        return RunConfiguration(
            target=target,
            stages=stages,
            services=service_file.services,
            iterations=pipeline.iterations,
            candidates_per_iteration=pipeline.candidates_per_iteration,
            top_k_feedback=pipeline.top_k_feedback,
            generator=pipeline.generator,
            admet_moo=pipeline.admet_moo,
            http=pipeline.http,
            output_dir=configured_output,
        )

    @classmethod
    def _parse_stages(
        cls, configured: list[dict[str, dict[str, Any] | None]]
    ) -> tuple[PipelineStage, ...]:
        stages: list[PipelineStage] = []
        for index, entry in enumerate(configured):
            if len(entry) != 1:
                raise ConfigurationError(
                    f"pipeline entry {index} must contain exactly one stage"
                )
            name, parameters = next(iter(entry.items()))
            if not cls._stage_name.fullmatch(name):
                raise ConfigurationError(f"invalid pipeline stage name: {name!r}")
            stages.append(PipelineStage(name=name, parameters=parameters or {}))
        return tuple(stages)

    @staticmethod
    def _read_yaml(path: Path) -> Any:
        try:
            with path.open(encoding="utf-8") as handle:
                content = yaml.safe_load(handle)
        except OSError as exc:
            raise ConfigurationError(f"could not read {path}: {exc}") from exc
        if content is None:
            raise ConfigurationError(f"configuration file is empty: {path}")
        return content
