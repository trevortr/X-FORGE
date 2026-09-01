from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, HTTPException, status

from libs.schemas import ScoreRecord

from .models import (
    FilterResponse,
    HealthResponse,
    LivenessResponse,
    PhysicsRequest,
    ScoreResponse,
)
from .scorer import PhysicsScorer

app = FastAPI(
    title="X-FORGE Tier-4 Physics Gate",
    version="0.1.0",
    description="Validate and gate externally computed FEP/MM-GBSA and MD evidence.",
)
scorer = PhysicsScorer()


@app.get("/live", response_model=LivenessResponse)
async def live() -> LivenessResponse:
    return LivenessResponse()


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@app.post("/score", response_model=ScoreResponse)
async def score(request: PhysicsRequest) -> ScoreResponse:
    try:
        results = await asyncio.to_thread(
            scorer.score_batch, request.molecules, request.parameters
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    molecules = [
        molecule.with_score(
            ScoreRecord(
                stage="physics",
                values=result.values,
                passed=result.passed,
                computed_at_iteration=molecule.iteration,
            ),
            physics={**result.values, **result.details, "error": result.error},
        )
        for molecule, result in zip(request.molecules, results, strict=True)
    ]
    return ScoreResponse(molecules=molecules)


@app.post("/filter", response_model=FilterResponse)
async def filter_molecules(request: PhysicsRequest) -> FilterResponse:
    passed = []
    rejected = []
    for molecule in request.molecules:
        record = molecule.scores[-1] if molecule.scores else None
        if record is None or record.stage != "physics":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"molecule {molecule.id} has not been scored by physics",
            )
        (passed if record.passed else rejected).append(molecule)
    return FilterResponse(passed=passed, rejected=rejected)
