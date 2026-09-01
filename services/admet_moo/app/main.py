from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status

from .models import (
    ADMETScreenRequest,
    EvaluatedMolecule,
    HealthResponse,
    LivenessResponse,
    OptimizeRequest,
    OptimizeResponse,
    PropertyMetadata,
    ScreenFilterResponse,
    ScreenScoreResponse,
)
from .optimization import ADMETOptimizer, OptimizationError, OptimizationResult
from .predictor import ADMETAIPredictor, ADMETPredictionError, InvalidMoleculeError
from .properties import property_registry
from .screening import ADMETScreen, ADMETScreenError
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
        PropertyMetadata.model_validate(prop.metadata()) for prop in property_registry.all()
    ]


def _screen_evidence(
    request: ADMETScreenRequest, predictions: list[dict[str, float]]
) -> list[dict[str, float]]:
    rows = []
    for molecule, prediction in zip(request.molecules, predictions, strict=True):
        evidence: dict[str, float] = {}
        data = molecule.model_dump()
        for score in data.get("scores", []):
            for key, value in score.get("values", {}).items():
                if isinstance(value, (int, float)):
                    evidence[key] = float(value)
        for key, value in data.items():
            if isinstance(value, (int, float)) and key not in {"iteration"}:
                evidence[key] = float(value)
        rows.append({**prediction, **evidence})
    return rows


@app.post("/score", response_model=ScreenScoreResponse)
async def score_admet_screen(
    request: ADMETScreenRequest,
    predictor: PredictorDependency,
) -> ScreenScoreResponse:
    try:
        predictions = await asyncio.to_thread(
            predictor.predict, [molecule.smiles for molecule in request.molecules]
        )
        screened = await asyncio.to_thread(
            ADMETScreen().evaluate,
            _screen_evidence(request, predictions),
            request.parameters,
        )
    except InvalidMoleculeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ADMETPredictionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except ADMETScreenError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    molecules = []
    for molecule, candidate in zip(request.molecules, screened, strict=True):
        data = molecule.model_dump()
        scores = list(data.pop("scores", []))
        scores.append(
            {
                "stage": "admet_screen",
                "values": {
                    **candidate.values,
                    "pareto_rank": float(candidate.pareto_rank),
                },
                "passed": candidate.passed,
                "computed_at_iteration": molecule.iteration,
            }
        )
        molecules.append(
            type(molecule)(
                **data,
                scores=scores,
                admet_screen={
                    **candidate.values,
                    "desirabilities": candidate.desirabilities,
                    "pareto_rank": candidate.pareto_rank,
                },
            )
        )
    return ScreenScoreResponse(molecules=molecules)


@app.post("/filter", response_model=ScreenFilterResponse)
async def filter_admet_screen(
    request: ADMETScreenRequest,
) -> ScreenFilterResponse:
    passed = []
    rejected = []
    for molecule in request.molecules:
        score = molecule.scores[-1] if molecule.scores else None
        if not isinstance(score, dict) or score.get("stage") != "admet_screen":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"molecule {molecule.id} has not been scored by admet_screen",
            )
        (passed if score.get("passed") else rejected).append(molecule)
    return ScreenFilterResponse(passed=passed, rejected=rejected)


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
        "scaffold_cluster",
        "synthesis_batch",
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
                scaffold_cluster=candidate.scaffold_cluster,
                synthesis_batch=candidate.synthesis_batch,
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
        evidence_rows = _screen_evidence(
            ADMETScreenRequest(
                molecules=request.molecules,
                parameters={},
            ),
            prediction_rows,
        )
        result = await asyncio.to_thread(
            optimizer.optimize,
            evidence_rows,
            top_k=request.top_k,
            method=request.selection.method,
            property_keys=request.properties,
            weights=request.selection.weights,
            reference_point=request.selection.reference_point,
            nsga3_reference_partitions=request.selection.nsga3_reference_partitions,
            smiles=[molecule.smiles for molecule in request.molecules],
            shared_intermediates=[
                getattr(molecule, "shared_intermediate_id", None)
                or (
                    getattr(molecule, "physchem", {}).get("shared_intermediate_id")
                    if isinstance(getattr(molecule, "physchem", {}), dict)
                    else None
                )
                for molecule in request.molecules
            ],
            diversity=request.selection.diversity,
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
