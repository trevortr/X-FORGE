from __future__ import annotations

import asyncio

import httpx

from app.main import app, get_scorer
from app.scorer import SynthesizabilityResult


class FakeScorer:
    def score_batch(self, molecules, parameters):
        assert len(molecules) == 2
        assert parameters.power == -2
        return [
            SynthesizabilityResult(
                values={
                    "scoring_succeeded": 1.0,
                    "rascore": 0.9,
                    "sascore": 2.1,
                    "power_mean_p_neg2": 0.8,
                    "synthesizability_activation": 0.97,
                },
                passed=True,
            ),
            SynthesizabilityResult(
                values={
                    "scoring_succeeded": 0.0,
                    "synthesizability_activation": 0.0,
                },
                passed=False,
                error="invalid SMILES",
            ),
        ]


async def _exercise_api() -> tuple[httpx.Response, httpx.Response]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        score_response = await client.post(
            "/score",
            json={
                "molecules": [
                    {"smiles": "CCO", "iteration": 3, "scores": []},
                    {"smiles": "invalid", "iteration": 3, "scores": []},
                ],
                "parameters": {},
            },
        )
        filter_response = await client.post(
            "/filter",
            json={
                "molecules": score_response.json()["molecules"],
                "parameters": {},
            },
        )
    return score_response, filter_response


def test_score_is_auditable_and_filter_only_partitions() -> None:
    app.dependency_overrides[get_scorer] = lambda: FakeScorer()
    try:
        score_response, filter_response = asyncio.run(_exercise_api())
    finally:
        app.dependency_overrides.clear()

    assert score_response.status_code == 200
    scored = score_response.json()["molecules"]
    assert scored[0]["scores"][-1]["stage"] == "synthesizability"
    assert scored[0]["scores"][-1]["passed"] is True
    assert scored[0]["scores"][-1]["computed_at_iteration"] == 3
    assert scored[0]["synthesizability"]["power"] == -2
    assert scored[1]["synthesizability"]["error"] == "invalid SMILES"

    assert filter_response.status_code == 200
    partition = filter_response.json()
    assert [item["id"] for item in partition["passed"]] == [scored[0]["id"]]
    assert [item["id"] for item in partition["rejected"]] == [scored[1]["id"]]


def test_filter_rejects_unscored_molecules() -> None:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                "/filter",
                json={"molecules": [{"smiles": "CCO", "scores": []}]},
            )

    response = asyncio.run(request())
    assert response.status_code == 422
    assert "has not been scored" in response.json()["detail"]
