from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from app.domain import GeneratedCandidate, GenerationResult, RuntimeReadiness
from app.main import app, generate, health, live
from app.models import (
    GenerateRequest,
    SeedMolecule,
)


class FakeGenerator:
    def readiness(self) -> tuple[bool, bool]:
        return True, True

    def runtime_readiness(self) -> RuntimeReadiness:
        return RuntimeReadiness(
            executable_available=True,
            model_available=True,
            runtime_available=True,
        )

    def generate(self, request):
        return GenerationResult(
            molecules=(
                GeneratedCandidate(
                    smiles="CCN",
                    id="generated-1",
                    parent_smiles=request.seeds[0].smiles,
                    parent_id=request.seeds[0].id or "parent-1",
                    tanimoto=0.7,
                    nll=10.0,
                ),
            ),
            requested=request.n_candidates_per_seed * len(request.seeds),
            generated=1,
            model="test.prior",
        )


def test_generate_contract(monkeypatch) -> None:
    async def run_inline(function, *args):
        return function(*args)

    monkeypatch.setattr(asyncio, "to_thread", run_inline)
    request = GenerateRequest(
        seeds=[SeedMolecule(smiles="CCO", id="hit-1")],
        n_candidates_per_seed=10,
    )

    response = asyncio.run(generate(request, FakeGenerator()))

    assert response.requested == 10
    assert response.generated == 1
    assert response.molecules[0].parent_id == "hit-1"


def test_request_requires_at_least_one_seed() -> None:
    with pytest.raises(ValidationError):
        GenerateRequest(seeds=[])


def test_health_contract_and_routes(monkeypatch) -> None:
    monkeypatch.setattr(asyncio, "to_thread", _run_inline)
    response = asyncio.run(health(FakeGenerator()))

    assert response.status == "ok"
    paths = {route.path for route in app.routes}
    assert {"/generate", "/health", "/live"}.issubset(paths)


async def _run_inline(function, *args):
    return function(*args)


def test_liveness_does_not_depend_on_reinvent() -> None:
    response = asyncio.run(live())

    assert response.status == "ok"
