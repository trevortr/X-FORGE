from __future__ import annotations

import asyncio
from importlib.metadata import version

from fastapi import FastAPI, HTTPException, status

from libs.schemas import ScoreRecord

from .models import (
    FilterResponse,
    HealthResponse,
    LivenessResponse,
    PolicyScoringRequest,
    ScoreResponse,
)
from .scorer import PolicyScorer

app = FastAPI(
    title="X-FORGE Tier-0 Policy Scoring",
    version="0.1.0",
    description="Reward-guided sampling with target QSAR and molecular desirability.",
)
scorer = PolicyScorer()


@app.get("/live", response_model=LivenessResponse)
async def live() -> LivenessResponse:
    return LivenessResponse()


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(rdkit=version("rdkit"))


@app.post("/score", response_model=ScoreResponse)
async def score(request: PolicyScoringRequest) -> ScoreResponse:
    results = await asyncio.to_thread(
        scorer.score_batch, request.molecules, request.parameters
    )
    annotated = []
    for molecule, result in zip(request.molecules, results, strict=True):
        annotated.append(
            molecule.with_score(
                ScoreRecord(
                    stage="policy_scoring",
                    values=result.values,
                    passed=result.passed,
                    computed_at_iteration=molecule.iteration,
                ),
                policy_reward={
                    **result.values,
                    "desirabilities": result.desirabilities,
                    "error": result.error,
                },
            )
        )
    return ScoreResponse(molecules=annotated)


@app.post("/filter", response_model=FilterResponse)
async def filter_molecules(request: PolicyScoringRequest) -> FilterResponse:
    passed = []
    rejected = []
    for molecule in request.molecules:
        record = molecule.scores[-1] if molecule.scores else None
        if record is None or record.stage != "policy_scoring":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"molecule {molecule.id} has not been scored by policy_scoring",
            )
        (passed if record.passed else rejected).append(molecule)
    return FilterResponse(passed=passed, rejected=rejected)
