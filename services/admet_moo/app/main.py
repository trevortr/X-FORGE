from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status

from .models import (
    EvaluatedMolecule,
    HealthResponse,
    LivenessResponse,
    OptimizeRequest,
    OptimizeResponse,
    PropertyMetadata,
)
from .optimization import ADMETOptimizer, OptimizationError, OptimizationResult
from .predictor import ADMETAIPredictor, ADMETPredictionError, InvalidMoleculeError
from .properties import property_registry
from .settings import Settings

app = FastAPI(
    title="X-FORGE ADMET-MOO",
    version="0.1.0",
    description="Predict ADMET endpoints and select leads from the Pareto front.",
)


@lru_cache
def _cached_predictor() -> ADMETAIPredictor:
    return ADMETAIPredictor(Settings.from_env())


async def get_predictor() -> ADMETAIPredictor:
    return _cached_predictor()


@lru_cache
def _cached_optimizer() -> ADMETOptimizer:
    return ADMETOptimizer(property_registry)


async def get_optimizer() -> ADMETOptimizer:
    return _cached_optimizer()


PredictorDependency = Annotated[ADMETAIPredictor, Depends(get_predictor)]
OptimizerDependency = Annotated[ADMETOptimizer, Depends(get_optimizer)]


@app.get("/live", response_model=LivenessResponse)
async def live() -> LivenessResponse:
    return LivenessResponse()


@app.get("/health", response_model=HealthResponse)
async def health(predictor: PredictorDependency) -> HealthResponse:
    readiness = await asyncio.to_thread(predictor.readiness)
    response = HealthResponse(
        status="ok" if readiness.available else "not_ready",
        model_loaded=readiness.model_loaded,
        device=readiness.device,
        detail=readiness.detail,
    )
    if not readiness.available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=response.model_dump(),
        )
    return response


@app.get("/properties", response_model=list[PropertyMetadata])
async def list_properties() -> list[PropertyMetadata]:
    return [
        PropertyMetadata.model_validate(prop.metadata()) for prop in property_registry
    ]


def _evaluated_molecules(
    request: OptimizeRequest, result: OptimizationResult
) -> list[EvaluatedMolecule]:
    evaluated: list[EvaluatedMolecule] = []
    reserved = {
        "admet_predictions",
        "objectives",
        "desirabilities",
        "pareto_rank",
        "selection_score",
        "selected",
    }
    for molecule, candidate in zip(request.molecules, result.candidates):
        data = molecule.model_dump()
        for field in reserved:
            data.pop(field, None)
        scores = list(data.pop("scores", []))
        scores.append(
            {
                "stage": "admet_moo",
                "values": candidate.predictions,
                "passed": candidate.selected,
                "computed_at_iteration": molecule.iteration,
            }
        )
        evaluated.append(
            EvaluatedMolecule(
                **data,
                scores=scores,
                admet_predictions=candidate.predictions,
                objectives=candidate.objectives,
                desirabilities=candidate.desirabilities,
                pareto_rank=candidate.pareto_rank,
                selection_score=candidate.selection_score,
                selected=candidate.selected,
            )
        )
    return evaluated


@app.post("/optimize", response_model=OptimizeResponse)
async def optimize(
    request: OptimizeRequest,
    predictor: PredictorDependency,
    optimizer: OptimizerDependency,
) -> OptimizeResponse:
    try:
        prediction_rows = await asyncio.to_thread(
            predictor.predict,
            [molecule.smiles for molecule in request.molecules],
        )
        result = await asyncio.to_thread(
            optimizer.optimize,
            prediction_rows,
            top_k=request.top_k,
            method=request.selection.method,
            property_keys=request.properties,
            weights=request.selection.weights,
            reference_point=request.selection.reference_point,
        )
    except InvalidMoleculeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ADMETPredictionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except OptimizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    molecules = _evaluated_molecules(request, result)
    return OptimizeResponse(
        molecules=molecules,
        selected=[molecules[index] for index in result.selected_indices],
        pareto_front=[molecules[index] for index in result.pareto_indices],
        selection_method=request.selection.method,
        properties=[
            PropertyMetadata.model_validate(prop.metadata())
            for prop in result.properties
        ],
    )
