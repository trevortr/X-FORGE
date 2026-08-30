from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any, ClassVar, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field

from libs.schemas import Molecule

from .config import HTTPOptions, PipelineStage


class ServiceCallError(RuntimeError):
    pass


class GeneratedCandidate(BaseModel):
    smiles: str
    id: str
    parent_smiles: str
    parent_id: str
    tanimoto: float | None = None
    nll: float | None = None


class GenerateResponse(BaseModel):
    molecules: list[GeneratedCandidate]
    requested: int
    generated: int
    model: str


class ScoreResponse(BaseModel):
    molecules: list[Molecule]


class FilterResponse(BaseModel):
    passed: list[Molecule]
    rejected: list[Molecule]


class OptimizeResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    molecules: list[Molecule]
    selected: list[Molecule]
    pareto_front: list[Molecule]
    selection_method: str
    properties: list[dict[str, Any]] = Field(default_factory=list)


class ServiceClient:
    RETRYABLE_STATUS_CODES: ClassVar[frozenset[int]] = frozenset({429, 502, 503, 504})

    def __init__(
        self,
        services: dict[str, str],
        options: HTTPOptions,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.services = services
        self.options = options
        self._sleep = sleep
        self._client = httpx.Client(
            timeout=options.timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def wait_until_ready(self, service_names: list[str]) -> None:
        for service_name in service_names:
            self._request(service_name, "GET", "/health")

    def generate(
        self,
        seeds: list[Molecule],
        *,
        total_candidates: int,
        strategy: str,
        temperature: float,
        random_seed: int,
    ) -> GenerateResponse:
        per_seed = math.ceil(total_candidates / len(seeds))
        payload = {
            "seeds": [
                {"smiles": molecule.smiles, "id": molecule.id} for molecule in seeds
            ],
            "n_candidates_per_seed": per_seed,
            "strategy": strategy,
            "temperature": temperature,
            "random_seed": random_seed,
        }
        response = GenerateResponse.model_validate(
            self._request("generator", "POST", "/generate", payload)
        )
        response.molecules = response.molecules[:total_candidates]
        response.generated = len(response.molecules)
        return response

    def score(self, stage: PipelineStage, molecules: list[Molecule]) -> list[Molecule]:
        response = ScoreResponse.model_validate(
            self._request(
                stage.name,
                "POST",
                "/score",
                {
                    "molecules": self._molecule_payload(molecules),
                    "parameters": stage.parameters,
                },
            )
        )
        self._validate_same_population(
            molecules, response.molecules, stage.name, "score"
        )
        self._validate_histories(molecules, response.molecules, stage.name)
        return response.molecules

    def filter(self, stage: PipelineStage, molecules: list[Molecule]) -> FilterResponse:
        response = FilterResponse.model_validate(
            self._request(
                stage.name,
                "POST",
                "/filter",
                {
                    "molecules": self._molecule_payload(molecules),
                    "parameters": stage.parameters,
                },
            )
        )
        partition = [*response.passed, *response.rejected]
        self._validate_same_population(molecules, partition, stage.name, "filter")
        self._validate_histories(molecules, partition, stage.name)
        return response

    def optimize(
        self,
        molecules: list[Molecule],
        *,
        top_k: int,
        properties: list[str] | None,
        selection: BaseModel,
    ) -> OptimizeResponse:
        response = OptimizeResponse.model_validate(
            self._request(
                "admet_moo",
                "POST",
                "/optimize",
                {
                    "molecules": self._molecule_payload(molecules),
                    "top_k": top_k,
                    "properties": properties,
                    "selection": selection.model_dump(mode="json"),
                },
            )
        )
        self._validate_same_population(
            molecules, response.molecules, "admet_moo", "optimize"
        )
        self._validate_histories(molecules, response.molecules, "admet_moo")
        population_ids = {molecule.id for molecule in response.molecules}
        for group_name, group in (
            ("selected", response.selected),
            ("pareto_front", response.pareto_front),
        ):
            group_ids = [molecule.id for molecule in group]
            if (
                len(group_ids) != len(set(group_ids))
                or not set(group_ids) <= population_ids
            ):
                raise ServiceCallError(
                    f"admet_moo returned an invalid {group_name} subset"
                )
        selected_ids = {molecule.id for molecule in response.selected}
        pareto_ids = {molecule.id for molecule in response.pareto_front}
        if not selected_ids <= pareto_ids:
            raise ServiceCallError(
                "admet_moo selected molecules outside the Pareto front"
            )
        return response

    def _request(
        self,
        service_name: str,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.services[service_name]}{path}"
        last_error: Exception | None = None
        for attempt in range(1, self.options.max_attempts + 1):
            try:
                response = self._client.request(method, url, json=payload)
                if response.status_code in self.RETRYABLE_STATUS_CODES:
                    raise ServiceCallError(
                        f"{service_name} returned retryable status "
                        f"{response.status_code}: {response.text[-1_000:]}"
                    )
                response.raise_for_status()
                return response.json()
            except (httpx.RequestError, httpx.HTTPStatusError, ServiceCallError) as exc:
                last_error = exc
                retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                    exc.response.status_code in self.RETRYABLE_STATUS_CODES
                )
                if not retryable or attempt == self.options.max_attempts:
                    break
                self._sleep(self.options.backoff_seconds * (2 ** (attempt - 1)))
        raise ServiceCallError(
            f"request to {service_name} {path} failed after "
            f"{self.options.max_attempts} attempt(s): {last_error}"
        ) from last_error

    @staticmethod
    def _molecule_payload(molecules: list[Molecule]) -> list[dict[str, Any]]:
        return [molecule.model_dump(mode="json") for molecule in molecules]

    @staticmethod
    def _validate_same_population(
        before: list[Molecule],
        after: list[Molecule],
        service_name: str,
        operation: str,
    ) -> None:
        before_ids = [molecule.id for molecule in before]
        after_ids = [molecule.id for molecule in after]
        if len(after_ids) != len(set(after_ids)):
            raise ServiceCallError(
                f"{service_name} returned duplicate molecule IDs from /{operation}"
            )
        if set(before_ids) != set(after_ids):
            raise ServiceCallError(
                f"{service_name} changed the molecule population during /{operation}"
            )

    @staticmethod
    def _validate_histories(
        before: list[Molecule], after: list[Molecule], service_name: str
    ) -> None:
        before_by_id = {molecule.id: molecule for molecule in before}
        for molecule in after:
            previous = before_by_id[molecule.id]
            prefix_length = len(previous.scores)
            if molecule.scores[:prefix_length] != previous.scores:
                raise ServiceCallError(
                    f"{service_name} rewrote score history for molecule {molecule.id}"
                )
