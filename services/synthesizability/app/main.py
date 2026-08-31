from __future__ import annotations

import asyncio
from functools import lru_cache
from importlib.metadata import version
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status

from libs.schemas import ScoreRecord

from .models import (
    FilterResponse,
    HealthResponse,
    LivenessResponse,
    ScoreResponse,
    SynthesizabilityRequest,
)
from .scorer import SynthesizabilityResult, SynthesizabilityScorer

app = FastAPI(
    title="X-FORGE Synthesizability Filter",
    version="0.1.0",
    description="Combine RA-Score and SAscore into a configurable synthetic gate.",
)


@lru_cache
def _cached_scorer() -> SynthesizabilityScorer:
    return SynthesizabilityScorer()


async def get_scorer() -> SynthesizabilityScorer:
    return _cached_scorer()


ScorerDependency = Annotated[SynthesizabilityScorer, Depends(get_scorer)]


@app.get("/live", response_model=LivenessResponse)
async def live() -> LivenessResponse:
    return LivenessResponse()


@app.get("/health", response_model=HealthResponse)
async def health(scorer: ScorerDependency) -> HealthResponse:
    return HealthResponse(
        rdkit=version("rdkit"),
        xgboost=version("xgboost"),
        scikit_learn=version("scikit-learn"),
        rascore_model=str(scorer.rascore.model_path),
    )


def _annotate(
    request: SynthesizabilityRequest,
    results: list[SynthesizabilityResult],
) -> ScoreResponse:
    annotated = []
    for molecule, result in zip(request.molecules, results, strict=True):
        details = {
            **result.values,
            "power": request.parameters.power,
            "error": result.error,
        }
        annotated.append(
            molecule.with_score(
                ScoreRecord(
                    stage="synthesizability",
                    values=result.values,
                    passed=result.passed,
                    computed_at_iteration=molecule.iteration,
                ),
                synthesizability=details,
            )
        )
    return ScoreResponse(molecules=annotated)


@app.post("/score", response_model=ScoreResponse)
async def score(
    request: SynthesizabilityRequest,
    scorer: ScorerDependency,
) -> ScoreResponse:
    results = await asyncio.to_thread(
        scorer.score_batch,
        request.molecules,
        request.parameters,
    )
    return _annotate(request, results)


@app.post("/filter", response_model=FilterResponse)
async def filter_molecules(request: SynthesizabilityRequest) -> FilterResponse:
    passed = []
    rejected = []
    for molecule in request.molecules:
        score_record = molecule.scores[-1] if molecule.scores else None
        if score_record is None or score_record.stage != "synthesizability":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"molecule {molecule.id} has not been scored by the "
                    "synthesizability service"
                ),
            )
        (passed if score_record.passed else rejected).append(molecule)
    return FilterResponse(passed=passed, rejected=rejected)
