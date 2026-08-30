from __future__ import annotations

import json

import httpx
import pytest
from app.client import ServiceCallError, ServiceClient
from app.config import HTTPOptions, PipelineStage, SelectionOptions

from libs.schemas import Molecule, ScoreRecord


def test_filter_stage_is_called_in_score_then_filter_order() -> None:
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append((request.url.path, payload))
        if request.url.path == "/score":
            molecules = [
                {
                    **molecule,
                    "scores": [
                        *molecule["scores"],
                        {
                            "stage": "solubility",
                            "values": {"log_s": -2.0},
                            "passed": None,
                            "computed_at_iteration": 1,
                        },
                    ],
                }
                for molecule in payload["molecules"]
            ]
            return httpx.Response(200, json={"molecules": molecules})
        molecules = payload["molecules"]
        return httpx.Response(
            200,
            json={"passed": molecules[:1], "rejected": molecules[1:]},
        )

    stage = PipelineStage("solubility", {"minimum": -4.0})
    molecules = [
        Molecule(
            smiles=smiles,
            iteration=1,
            scores=[
                ScoreRecord(
                    stage="generator",
                    values={},
                    computed_at_iteration=1,
                )
            ],
        )
        for smiles in ("CCO", "CCN")
    ]
    with ServiceClient(
        {"solubility": "http://filter-solubility:12002"},
        HTTPOptions(max_attempts=1),
        transport=httpx.MockTransport(handler),
    ) as client:
        scored = client.score(stage, molecules)
        filtered = client.filter(stage, scored)

    assert [path for path, _ in calls] == ["/score", "/filter"]
    assert all(payload["parameters"] == {"minimum": -4.0} for _, payload in calls)
    assert len(filtered.passed) == 1
    assert len(filtered.rejected) == 1
    assert filtered.passed[0].scores[-1].stage == "solubility"


def test_readiness_retries_transient_service_failure() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, json={"status": "not_ready"})
        return httpx.Response(200, json={"status": "ok"})

    with ServiceClient(
        {"generator": "http://generator:12000"},
        HTTPOptions(max_attempts=3, backoff_seconds=0.5),
        transport=httpx.MockTransport(handler),
        sleep=delays.append,
    ) as client:
        client.wait_until_ready(["generator"])

    assert attempts == 3
    assert delays == [0.5, 1.0]


def test_optimize_rejects_selection_outside_pareto_front() -> None:
    molecules = [Molecule(smiles="CCO"), Molecule(smiles="CCN")]

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        evaluated = [
            {
                **molecule,
                "scores": [
                    *molecule["scores"],
                    {
                        "stage": "admet_moo",
                        "values": {"bioavailability": 0.5},
                        "passed": False,
                        "computed_at_iteration": 0,
                    },
                ],
            }
            for molecule in payload["molecules"]
        ]
        return httpx.Response(
            200,
            json={
                "molecules": evaluated,
                "selected": evaluated[1:],
                "pareto_front": evaluated[:1],
                "selection_method": "knee_point",
                "properties": [],
            },
        )

    with (
        ServiceClient(
            {"admet_moo": "http://admet-moo:12001"},
            HTTPOptions(max_attempts=1),
            transport=httpx.MockTransport(handler),
        ) as client,
        pytest.raises(
            ServiceCallError,
            match="selected molecules outside the Pareto front",
        ),
    ):
        client.optimize(
            molecules,
            top_k=1,
            properties=None,
            selection=SelectionOptions(method="knee_point"),
        )
