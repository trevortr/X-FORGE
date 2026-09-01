from __future__ import annotations

import asyncio
from importlib.metadata import version

from fastapi import FastAPI, HTTPException, status

from libs.schemas import ScoreRecord

from .models import (
    FilterResponse,
    HealthResponse,
    LivenessResponse,
    PhyschemRequest,
    ScoreResponse,
)
from .scorer import PhyschemScorer

app = FastAPI(
    title="X-FORGE Tier-1 Physicochemical Filter",
    version="0.1.0",
    description="Fast 2D, liability, pKa-evidence, and route-viability screening.",
)
scorer = PhyschemScorer()


@app.get("/live", response_model=LivenessResponse)
async def live() -> LivenessResponse:
    return LivenessResponse()


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(rdkit=version("rdkit"))


@app.post("/score", response_model=ScoreResponse)
async def score(request: PhyschemRequest) -> ScoreResponse:
    results = await asyncio.to_thread(
        scorer.score_batch, request.molecules, request.parameters
    )
    molecules = [
        molecule.with_score(
            ScoreRecord(
                stage="physchem",
                values=result.values,
                passed=result.passed,
                computed_at_iteration=molecule.iteration,
            ),
            physchem={**result.values, **result.details, "error": result.error},
        )
        for molecule, result in zip(request.molecules, results, strict=True)
    ]
    return ScoreResponse(molecules=molecules)


@app.post("/filter", response_model=FilterResponse)
async def filter_molecules(request: PhyschemRequest) -> FilterResponse:
    passed = []
    rejected = []
    for molecule in request.molecules:
        record = molecule.scores[-1] if molecule.scores else None
        if record is None or record.stage != "physchem":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"molecule {molecule.id} has not been scored by physchem",
            )
        (passed if record.passed else rejected).append(molecule)
    return FilterResponse(passed=passed, rejected=rejected)
