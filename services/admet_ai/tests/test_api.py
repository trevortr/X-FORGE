from __future__ import annotations

import asyncio
from asyncio import Queue

import httpx

from admet import Admet
from endpoint import app


class FakeModel:
    def predict(self, *, smiles: list[str]):
        return FakeFrame(
            [
                {
                    "QED": 0.75,
                    "Solubility_AqSolDB": -2.8,
                    "hERG": 0.12,
                }
                for _ in smiles
            ]
        )


class FakeFrame:
    def __init__(self, records: list[dict[str, float]]) -> None:
        self.records = records

    def to_dict(self, *, orient: str):
        assert orient == "records"
        return self.records


async def _request(
    method: str,
    path: str,
    **kwargs,
) -> httpx.Response:
    pool: Queue[Admet] = Queue()
    pool.put_nowait(Admet(model=FakeModel()))
    app.state.model_pool = pool
    app.state.model_count = 1
    app.state.load_error = None
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        return await client.request(method, path, **kwargs)


def test_health_and_property_catalog() -> None:
    health = asyncio.run(_request("GET", "/health"))
    properties = asyncio.run(_request("GET", "/properties"))

    assert health.status_code == 200
    assert health.json()["status"] == "healthy"
    assert any(item["id"] == "Solubility_AqSolDB" for item in properties.json())


def test_single_prediction_supports_original_property_field_and_aliases() -> None:
    response = asyncio.run(
        _request(
            "POST",
            "/smi",
            json={
                "smiles": "CCO",
                "property": ["QED", "aqueous_solubility", "herg"],
            },
        )
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["results"]["QED"]["results"] == 0.75
    assert payload["results"]["Solubility_AqSolDB"]["results"] == -2.8
    assert payload["results"]["hERG"]["results"] == 0.12


def test_bulk_upload_batches_smiles() -> None:
    response = asyncio.run(
        _request(
            "POST",
            "/upload_smi?property=QED&property=hERG",
            files={"file": ("molecules.smi", b"CCO\nCCN\n", "text/plain")},
        )
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_smiles"] == 2
    assert [item["smiles"] for item in payload["results"]] == ["CCO", "CCN"]
    assert set(payload["results"][0]["results"]) == {"QED", "hERG"}
