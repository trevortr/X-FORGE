from __future__ import annotations

import asyncio
from functools import lru_cache
from importlib.metadata import version
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status

from libs.schemas import ScoreRecord

from .models import (
    BindingRequest,
    FilterResponse,
    HealthResponse,
    LivenessResponse,
    ScoreResponse,
)
from .scorer import BindingResult, BindingScorer, TargetConfigurationError

app = FastAPI(
    title="X-FORGE Binding Filter",
    version="0.1.0",
    description="Prepare, dock, and evaluate protein-ligand binding poses.",
)


@lru_cache
def _cached_scorer() -> BindingScorer:
    return BindingScorer()


async def get_scorer() -> BindingScorer:
    return _cached_scorer()


ScorerDependency = Annotated[BindingScorer, Depends(get_scorer)]


@app.get("/live", response_model=LivenessResponse)
async def live() -> LivenessResponse:
    return LivenessResponse()


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        rdkit=version("rdkit"),
        meeko=version("meeko"),
        vina=version("vina"),
        prolif=version("prolif"),
    )


def _annotate(request: BindingRequest, results: list[BindingResult]) -> ScoreResponse:
    annotated = []
    for molecule, result in zip(request.molecules, results, strict=True):
        binding = {
            **result.values,
            "interactions": list(result.interactions),
            "error": result.error,
        }
        annotated.append(
            molecule.with_score(
                ScoreRecord(
                    stage="binding",
                    values=result.values,
                    passed=result.passed,
                    computed_at_iteration=molecule.iteration,
                ),
                binding=binding,
            )
        )
    return ScoreResponse(molecules=annotated)


@app.post("/score", response_model=ScoreResponse)
async def score(
    request: BindingRequest,
    scorer: ScorerDependency,
) -> ScoreResponse:
    try:
        results = await asyncio.to_thread(
            scorer.score_batch,
            request.molecules,
            request.parameters,
        )
    except TargetConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return _annotate(request, results)


@app.post("/filter", response_model=FilterResponse)
async def filter_molecules(request: BindingRequest) -> FilterResponse:
    passed = []
    rejected = []
    for molecule in request.molecules:
        score_record = molecule.scores[-1] if molecule.scores else None
        if score_record is None or score_record.stage != "binding":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"molecule {molecule.id} has not been scored by the binding service"
                ),
            )
        (passed if score_record.passed else rejected).append(molecule)
    return FilterResponse(passed=passed, rejected=rejected)
