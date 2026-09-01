from __future__ import annotations

import asyncio

import httpx

from app.main import app


def test_reward_service_scores_and_selects_top_k() -> None:
    async def request() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "molecules": [
                    {"smiles": "CCO", "iteration": 1},
                    {"smiles": "c1ccccc1", "iteration": 1},
                ],
                "parameters": {
                    "affinity_training_set": [
                        {"smiles": "CCO", "value": -8.0},
                        {"smiles": "c1ccccc1", "value": -6.0},
                    ],
                    "top_k": 1,
                },
            }
            scored = await client.post("/score", json=payload)
            payload["molecules"] = scored.json()["molecules"]
            filtered = await client.post("/filter", json=payload)
            return scored, filtered

    scored, filtered = asyncio.run(request())
    assert scored.status_code == 200
    assert len(filtered.json()["passed"]) == 1
    assert all(
        molecule["scores"][-1]["stage"] == "policy_scoring"
        for molecule in scored.json()["molecules"]
    )
    assert "desirabilities" in scored.json()["molecules"][0]["policy_reward"]
