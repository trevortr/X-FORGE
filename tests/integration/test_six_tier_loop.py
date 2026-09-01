from __future__ import annotations

import json
from pathlib import Path

import httpx

from libs.schemas import molecule_id
from services.orchestrator.app.client import ServiceClient
from services.orchestrator.app.config import ConfigurationLoader
from services.orchestrator.app.results import ResultWriter
from services.orchestrator.app.runner import PipelineRunner


def test_reward_guided_six_tier_contract_order(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "target.yaml").write_text(
        "name: tiered-demo\nseeds:\n  - smiles: CCO\n", encoding="utf-8"
    )
    (config / "pipeline.yaml").write_text(
        """target: target.yaml
iterations: 1
candidates_per_iteration: 2
top_k_feedback: 1
generator:
  reward:
    service: policy_scoring
    pool_multiplier: 2
    parameters:
      affinity_training_set:
        - {smiles: CCO, value: -8.0}
pipeline:
  - physchem: {}
  - admet_screen: {}
  - binding: {}
  - physics: {}
admet_moo:
  properties: [binding_free_energy]
  selection:
    method: nsga3
    diversity: {enabled: true}
http: {timeout_seconds: 10, max_attempts: 1, backoff_seconds: 0}
""",
        encoding="utf-8",
    )
    (config / "services.yaml").write_text(
        """services:
  generator: http://generator:12000
  policy_scoring: http://policy-scoring:12003
  physchem: http://physchem:12005
  admet_screen: http://admet-moo:12001
  binding: http://binding:12004
  physics: http://physics:12006
  admet_moo: http://admet-moo:12001
""",
        encoding="utf-8",
    )
    calls: list[str] = []

    def append_stage(payload: dict, stage: str, limit: int | None = None):
        molecules = []
        for index, molecule in enumerate(payload["molecules"]):
            passed = limit is None or index < limit
            molecules.append(
                {
                    **molecule,
                    "scores": [
                        *molecule["scores"],
                        {
                            "stage": stage,
                            "values": {f"{stage}_score": float(index)},
                            "passed": passed,
                            "computed_at_iteration": molecule["iteration"],
                        },
                    ],
                }
            )
        return httpx.Response(200, json={"molecules": molecules})

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.url.host}{request.url.path}")
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        payload = json.loads(request.content)
        if request.url.path == "/generate":
            generated = [
                {
                    "smiles": "C" * (index + 2),
                    "id": molecule_id("C" * (index + 2)),
                    "parent_smiles": payload["seeds"][0]["smiles"],
                    "parent_id": payload["seeds"][0]["id"],
                    "tanimoto": 0.5,
                    "nll": float(index),
                }
                for index in range(payload["n_candidates_per_seed"])
            ]
            return httpx.Response(
                200,
                json={
                    "molecules": generated,
                    "requested": len(generated),
                    "generated": len(generated),
                    "model": "fake.prior",
                },
            )
        if request.url.path == "/score":
            stage = {
                "policy-scoring": "policy_scoring",
                "physchem": "physchem",
                "admet-moo": "admet_screen",
                "binding": "binding",
                "physics": "physics",
            }[request.url.host]
            return append_stage(
                payload,
                stage,
                limit=2 if stage == "policy_scoring" else None,
            )
        if request.url.path == "/filter":
            passed = [
                molecule
                for molecule in payload["molecules"]
                if molecule["scores"][-1]["passed"]
            ]
            rejected = [
                molecule
                for molecule in payload["molecules"]
                if not molecule["scores"][-1]["passed"]
            ]
            return httpx.Response(
                200, json={"passed": passed, "rejected": rejected}
            )
        if request.url.path == "/optimize":
            evaluated = []
            for molecule in payload["molecules"]:
                evaluated.append(
                    {
                        **molecule,
                        "scores": [
                            *molecule["scores"],
                            {
                                "stage": "admet_moo",
                                "values": {"binding_free_energy": -9.0},
                                "passed": True,
                                "computed_at_iteration": molecule["iteration"],
                            },
                        ],
                        "selected": True,
                    }
                )
            return httpx.Response(
                200,
                json={
                    "molecules": evaluated,
                    "selected": evaluated[:1],
                    "pareto_front": evaluated,
                    "selection_method": "nsga3",
                    "properties": [],
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    configuration = ConfigurationLoader.load(
        config / "pipeline.yaml",
        config / "services.yaml",
        run_name_override="six-tier-test",
        results_root_override=tmp_path / "results",
    )
    with ServiceClient(
        configuration.services,
        configuration.http,
        transport=httpx.MockTransport(handler),
    ) as client:
        result = PipelineRunner(
            configuration,
            client,
            ResultWriter(configuration.output_dir),
        ).run()

    assert result.status == "completed"
    assert len(result.iterations[0].generated) == 4
    assert [stage.stage for stage in result.iterations[0].filter_stages] == [
        "policy_scoring",
        "physchem",
        "admet_screen",
        "binding",
        "physics",
    ]
    assert len(result.final_selected) == 1
    assert calls[-1] == "admet-moo/optimize"
