from __future__ import annotations

import asyncio

import httpx

from app.main import app, get_scorer
from app.scorer import BindingResult


PARAMETERS = {
    "receptor_pdbqt": "/target/receptor.pdbqt",
    "receptor_pdb": "/target/receptor.pdb",
    "box_center": [1.0, 2.0, 3.0],
    "box_size": [20.0, 20.0, 20.0],
}


class FakeScorer:
    def score_batch(self, molecules, parameters):
        assert len(molecules) == 2
        assert parameters.box_center == (1.0, 2.0, 3.0)
        return [
            BindingResult(
                values={"docking_succeeded": 1.0, "vina_score": -8.0},
                interactions=("HBAcceptor:ARG120.A",),
                passed=True,
            ),
            BindingResult(
                values={"docking_succeeded": 0.0, "binding_desirability": 0.0},
                interactions=(),
                passed=False,
                error="conformer failed",
            ),
        ]


async def _exercise_api() -> tuple[httpx.Response, httpx.Response]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        score_response = await client.post(
            "/score",
            json={
                "molecules": [
                    {"smiles": "CCO", "iteration": 2, "scores": []},
                    {"smiles": "invalid", "iteration": 2, "scores": []},
                ],
                "parameters": PARAMETERS,
            },
        )
        filter_response = await client.post(
            "/filter",
            json={
                "molecules": score_response.json()["molecules"],
                "parameters": PARAMETERS,
            },
        )
    return score_response, filter_response


def test_score_appends_auditable_metrics_and_filter_only_partitions() -> None:
    app.dependency_overrides[get_scorer] = lambda: FakeScorer()
    try:
        score_response, filter_response = asyncio.run(_exercise_api())
    finally:
        app.dependency_overrides.clear()

    assert score_response.status_code == 200
    scored = score_response.json()["molecules"]
    assert scored[0]["scores"][-1] == {
        "stage": "binding",
        "values": {"docking_succeeded": 1.0, "vina_score": -8.0},
        "passed": True,
        "computed_at_iteration": 2,
    }
    assert scored[0]["binding"]["interactions"] == ["HBAcceptor:ARG120.A"]
    assert scored[1]["binding"]["error"] == "conformer failed"

    assert filter_response.status_code == 200
    partition = filter_response.json()
    assert [molecule["id"] for molecule in partition["passed"]] == [scored[0]["id"]]
    assert [molecule["id"] for molecule in partition["rejected"]] == [scored[1]["id"]]
    assert partition["passed"][0]["scores"] == scored[0]["scores"]


def test_filter_rejects_an_unscored_population() -> None:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            return await client.post(
                "/filter",
                json={
                    "molecules": [{"smiles": "CCO", "scores": []}],
                    "parameters": PARAMETERS,
                },
            )

    response = asyncio.run(request())
    assert response.status_code == 422
    assert "has not been scored" in response.json()["detail"]
