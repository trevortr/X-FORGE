from __future__ import annotations

import asyncio
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, status

from .domain import GenerationJob, Seed
from .models import GenerateRequest, GenerateResponse, HealthResponse, LivenessResponse
from .reinvent import (
    ReinventError,
    ReinventGenerator,
    ReinventNotReadyError,
    ReinventTimeoutError,
)
from .settings import Settings


app = FastAPI(
    title="X-FORGE Generator",
    version="0.1.0",
    description="Generate hit analogues with REINVENT4 Mol2Mol.",
)


@lru_cache
def _cached_generator() -> ReinventGenerator:
    return ReinventGenerator(Settings.from_env())


async def get_generator() -> ReinventGenerator:
    return _cached_generator()


@app.get("/health", response_model=HealthResponse)
async def health(generator: ReinventGenerator = Depends(get_generator)) -> HealthResponse:
    readiness = await asyncio.to_thread(generator.runtime_readiness)
    response = HealthResponse(
        status="ok" if readiness.runtime_available else "not_ready",
        model_available=readiness.model_available,
        executable_available=readiness.executable_available,
        runtime_available=readiness.runtime_available,
        detail=readiness.detail,
    )
    if not readiness.runtime_available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=response.model_dump(),
        )
    return response


@app.get("/live", response_model=LivenessResponse)
async def live() -> LivenessResponse:
    return LivenessResponse()


@app.post("/generate", response_model=GenerateResponse)
async def generate(
    request: GenerateRequest,
    generator: ReinventGenerator = Depends(get_generator),
) -> GenerateResponse:
    job = GenerationJob(
        seeds=tuple(Seed(smiles=seed.smiles, id=seed.id) for seed in request.seeds),
        n_candidates_per_seed=request.n_candidates_per_seed,
        strategy=request.strategy,
        temperature=request.temperature,
        random_seed=request.random_seed,
    )
    try:
        result = await asyncio.to_thread(generator.generate, job)
        return GenerateResponse.model_validate(result, from_attributes=True)
    except ReinventNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except ReinventTimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc)) from exc
    except ReinventError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
