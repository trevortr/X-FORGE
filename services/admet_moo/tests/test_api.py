from __future__ import annotations

import asyncio

from app.main import app, health, list_properties, live, optimize
from app.models import OptimizeRequest
from app.optimization import ADMETOptimizer
from app.predictor import PredictorReadiness
from app.properties import property_registry


class FakePredictor:
    def readiness(self) -> PredictorReadiness:
        return PredictorReadiness(available=True, model_loaded=True, device="cpu")

    def predict(self, smiles: list[str]) -> list[dict[str, float]]:
        return [
            {
                "Bioavailability_Ma": 0.8,
                "Solubility_AqSolDB": -3.0,
                "CYP3A4_Veith": 0.1,
                "hERG": 0.1,
                "DILI": 0.1,
            }
            for _ in smiles
        ]


async def run_inline(function, *args, **kwargs):
    return function(*args, **kwargs)


def test_optimize_contract_preserves_provenance_and_appends_score(monkeypatch) -> None:
    monkeypatch.setattr(asyncio, "to_thread", run_inline)
    request = OptimizeRequest.model_validate(
        {
            "molecules": [
                {
                    "smiles": "CCO",
                    "id": "candidate-1",
                    "parent_id": "hit-1",
                    "iteration": 2,
                    "scores": [{"stage": "filter", "values": {"score": 1.0}}],
                }
            ],
            "top_k": 1,
            "selection": {"method": "desirability"},
        }
    )

    response = asyncio.run(
        optimize(request, FakePredictor(), ADMETOptimizer(property_registry))
    )

    assert response.selected[0].id == "candidate-1"
    assert response.selected[0].parent_id == "hit-1"
    assert response.selected[0].scores[-1]["stage"] == "admet_moo"
    assert response.selected[0].scores[-1]["computed_at_iteration"] == 2


def test_health_liveness_properties_and_routes(monkeypatch) -> None:
    monkeypatch.setattr(asyncio, "to_thread", run_inline)

    assert asyncio.run(health(FakePredictor())).status == "ok"
    assert asyncio.run(live()).status == "ok"
    assert len(asyncio.run(list_properties())) == 12
    paths = {route.path for route in app.routes}
    assert {
        "/score",
        "/filter",
        "/optimize",
        "/properties",
        "/health",
        "/live",
    }.issubset(paths)
