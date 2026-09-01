from __future__ import annotations

import asyncio
import os
from asyncio import Queue
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import FastAPI, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from admet import (
    ALL_PROPS,
    PROPERTY_NAME_MAP,
    ADMETModelError,
    Admet,
)


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    smiles: str = Field(min_length=1, max_length=10_000)
    property: list[str] | None = None

    @field_validator("smiles")
    @classmethod
    def one_line_smiles(cls, value: str) -> str:
        value = value.strip()
        if not value or "\n" in value or "\r" in value:
            raise ValueError("SMILES must be a non-empty single line")
        return value


class HealthResponse(BaseModel):
    status: Literal["healthy", "not_ready"]
    message: str
    model_count: int = 0


class PropertyMetadata(BaseModel):
    id: str
    name: str
    task_type: Literal["regression", "classification"]


class PropertyResult(BaseModel):
    property: str
    status: Literal["success", "error"]
    results: float | None = None
    error: str | None = None


class PredictionResponse(BaseModel):
    smiles: str
    status: Literal["success", "error"]
    results: dict[str, PropertyResult]
    error: str | None = None


class BulkResponse(BaseModel):
    filename: str
    requested_properties: list[str] | None = None
    total_smiles: int
    results: list[PredictionResponse]
    error: str | None = None


def _positive_integer(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < 1:
        raise RuntimeError(f"{name} must be at least one")
    return value


def _nonnegative_integer(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < 0:
        raise RuntimeError(f"{name} must be nonnegative")
    return value


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    queue_count = _positive_integer(
        "ADMET_QUEUE_COUNT",
        int(os.getenv("QUEUE_COUNT", "1")),
    )
    num_workers = _nonnegative_integer("ADMET_NUM_WORKERS", 0)
    pool: Queue[Admet] = Queue(maxsize=queue_count)
    application.state.model_pool = pool
    application.state.model_count = 0
    application.state.load_error = None
    try:
        for _ in range(queue_count):
            model = await asyncio.to_thread(Admet, num_workers=num_workers)
            pool.put_nowait(model)
            application.state.model_count += 1
    except Exception as exc:
        application.state.load_error = f"{type(exc).__name__}: {exc}"
    yield


app = FastAPI(
    title="X-FORGE ADMET-AI",
    version="2.0.0",
    description="Standalone ADMET-AI prediction microservice.",
    lifespan=lifespan,
)
app.state.model_pool = None
app.state.model_count = 0
app.state.load_error = "service startup has not completed"


def get_valid_properties(
    requested_properties: list[str] | None,
) -> tuple[list[str], str | None]:
    if requested_properties is None:
        return [property_id for property_id, _, _ in ALL_PROPS], None
    normalized: list[str] = []
    for requested in requested_properties:
        key = requested.strip()
        property_id = (
            PROPERTY_NAME_MAP.get(key)
            or PROPERTY_NAME_MAP.get(key.lower())
        )
        if property_id is None:
            return [], f"invalid ADMET property: {requested!r}"
        if property_id not in normalized:
            normalized.append(property_id)
    return normalized, None


def _pool() -> Queue[Admet]:
    pool = getattr(app.state, "model_pool", None)
    if pool is None or app.state.model_count < 1:
        detail = app.state.load_error or "ADMET-AI model is not loaded"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        )
    return pool


async def _predict_many(smiles: list[str]) -> list[dict[str, float]]:
    pool = _pool()
    model = await pool.get()
    try:
        return await asyncio.to_thread(model.predict_many, smiles)
    except ADMETModelError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    finally:
        pool.put_nowait(model)


def _response(
    smiles: str,
    predictions: dict[str, float],
    properties: list[str],
) -> PredictionResponse:
    results: dict[str, PropertyResult] = {}
    for property_id in properties:
        if property_id in predictions:
            results[property_id] = PropertyResult(
                property=property_id,
                status="success",
                results=predictions[property_id],
            )
        else:
            results[property_id] = PropertyResult(
                property=property_id,
                status="error",
                error="ADMET-AI did not return this property",
            )
    overall = "success" if all(
        result.status == "success" for result in results.values()
    ) else "error"
    return PredictionResponse(smiles=smiles, status=overall, results=results)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "X-FORGE ADMET-AI microservice"}


@app.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    if app.state.model_count < 1:
        response = HealthResponse(
            status="not_ready",
            message=app.state.load_error or "ADMET-AI model is not loaded",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=response.model_dump(),
        )
    return HealthResponse(
        status="healthy",
        message="ADMET-AI microservice is ready",
        model_count=app.state.model_count,
    )


@app.get("/properties", response_model=list[PropertyMetadata])
async def properties() -> list[PropertyMetadata]:
    return [
        PropertyMetadata(id=property_id, name=name, task_type=task_type)
        for property_id, name, task_type in ALL_PROPS
    ]


@app.post("/smi", response_model=PredictionResponse)
async def smi_request(request: PredictionRequest) -> PredictionResponse:
    selected, error = get_valid_properties(request.property)
    if error is not None:
        return PredictionResponse(
            smiles=request.smiles,
            status="error",
            results={},
            error=error,
        )
    predictions = (await _predict_many([request.smiles]))[0]
    return _response(request.smiles, predictions, selected)


@app.post("/upload_smi", response_model=BulkResponse)
async def upload_smi(
    file: Annotated[UploadFile, File(...)],
    property: Annotated[list[str] | None, Query()] = None,
) -> BulkResponse:
    contents = (await file.read()).decode("utf-8")
    smiles = [line.strip() for line in contents.splitlines() if line.strip()]
    maximum = _positive_integer("ADMET_MAX_BULK_SIZE", 10_000)
    if not smiles:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="uploaded file contains no SMILES",
        )
    if len(smiles) > maximum:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"uploaded file exceeds {maximum} SMILES",
        )
    selected, error = get_valid_properties(property)
    if error is not None:
        return BulkResponse(
            filename=file.filename or "smiles.txt",
            requested_properties=property,
            total_smiles=len(smiles),
            results=[],
            error=error,
        )
    predictions = await _predict_many(smiles)
    return BulkResponse(
        filename=file.filename or "smiles.txt",
        requested_properties=property,
        total_smiles=len(smiles),
        results=[
            _response(value, row, selected)
            for value, row in zip(smiles, predictions, strict=True)
        ],
    )
