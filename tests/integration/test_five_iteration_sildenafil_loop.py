from __future__ import annotations

import json
from pathlib import Path

import httpx

from libs.schemas import molecule_id
from services.orchestrator.app.client import ServiceClient
from services.orchestrator.app.config import ConfigurationLoader
from services.orchestrator.app.results import ResultWriter, RunResult
from services.orchestrator.app.runner import PipelineRunner

SILDENAFIL = "CCCc1c2c(n(n1)C)C(=O)NC(=N2)c3cc(ccc3OCC)S(=O)(=O)N4CCN(CC4)C"


def test_sildenafil_completes_five_synthesis_binding_admet_iterations(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config"
    targets_dir = config_dir / "targets"
    targets_dir.mkdir(parents=True)
    (config_dir / "pipeline.yaml").write_text(
        """\
target: targets/sildenafil.yaml
pipeline:
  - synthesizability:
      power: -2
      min_activation: 0.5
  - binding:
      receptor_pdbqt: /targets/pde5/receptor.pdbqt
      receptor_pdb: /targets/pde5/protein.pdb
      box_center: [28.792, 30.186, 64.179]
      box_size: [24.0, 24.0, 24.0]
iterations: 5
candidates_per_iteration: 3
top_k_feedback: 2
generator:
  strategy: multinomial
  temperature: 1.0
  random_seed: 42
admet_moo:
  selection:
    method: desirability
http:
  timeout_seconds: 10
  max_attempts: 1
  backoff_seconds: 0
""",
        encoding="utf-8",
    )
    (config_dir / "services.yaml").write_text(
        """\
services:
  generator: http://generator:12000
  synthesizability: http://synthesizability:12002
  binding: http://binding:12004
  admet_moo: http://admet-moo:12001
""",
        encoding="utf-8",
    )
    (targets_dir / "sildenafil.yaml").write_text(
        f'name: sildenafil-pde5-1tbf\nseeds:\n  - smiles: "{SILDENAFIL}"\n',
        encoding="utf-8",
    )

    generate_calls = 0
    calls: list[str] = []

    def append_score(payload: dict, stage: str, values: dict) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "molecules": [
                    {
                        **molecule,
                        "scores": [
                            *molecule["scores"],
                            {
                                "stage": stage,
                                "values": values,
                                "passed": True,
                                "computed_at_iteration": molecule["iteration"],
                            },
                        ],
                    }
                    for molecule in payload["molecules"]
                ]
            },
        )

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal generate_calls
        calls.append(f"{request.url.host}{request.url.path}")
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        payload = json.loads(request.content)
        if request.url.path == "/generate":
            generate_calls += 1
            generated = []
            for seed_index, seed in enumerate(payload["seeds"]):
                for candidate_index in range(payload["n_candidates_per_seed"]):
                    chain_length = (
                        10 * generate_calls + 2 * seed_index + candidate_index
                    )
                    smiles = "C" * chain_length + "N"
                    generated.append(
                        {
                            "smiles": smiles,
                            "id": molecule_id(smiles),
                            "parent_smiles": seed["smiles"],
                            "parent_id": seed["id"],
                            "tanimoto": 0.7,
                            "nll": float(chain_length),
                        }
                    )
            return httpx.Response(
                200,
                json={
                    "molecules": generated,
                    "requested": len(generated),
                    "generated": len(generated),
                    "model": "fake-mol2mol.prior",
                },
            )
        if request.url.path == "/score" and request.url.host == "synthesizability":
            return append_score(
                payload,
                "synthesizability",
                {
                    "rascore": 0.9,
                    "sascore": 2.5,
                    "power_mean_p_neg2": 0.85,
                    "synthesizability_activation": 0.98,
                },
            )
        if request.url.path == "/score" and request.url.host == "binding":
            return append_score(
                payload,
                "binding",
                {
                    "docking_succeeded": 1.0,
                    "vina_score": -8.0,
                    "vina_ligand_efficiency": 0.3,
                },
            )
        if request.url.path == "/filter":
            return httpx.Response(
                200,
                json={"passed": payload["molecules"], "rejected": []},
            )
        if request.url.path == "/optimize":
            evaluated = []
            for rank, molecule in enumerate(payload["molecules"]):
                evaluated.append(
                    {
                        **molecule,
                        "scores": [
                            *molecule["scores"],
                            {
                                "stage": "admet_moo",
                                "values": {"bioavailability": 0.9 - rank * 0.1},
                                "passed": rank < payload["top_k"],
                                "computed_at_iteration": molecule["iteration"],
                            },
                        ],
                        "pareto_rank": 0,
                        "selected": rank < payload["top_k"],
                    }
                )
            return httpx.Response(
                200,
                json={
                    "molecules": evaluated,
                    "selected": evaluated[: payload["top_k"]],
                    "pareto_front": evaluated,
                    "selection_method": payload["selection"]["method"],
                    "properties": [],
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    results_root = tmp_path / "results"
    configuration = ConfigurationLoader.load(
        config_dir / "pipeline.yaml",
        config_dir / "services.yaml",
        run_name_override="sildenafil-five-iteration-smoke-test",
        results_root_override=results_root,
    )
    with ServiceClient(
        configuration.services,
        configuration.http,
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    ) as client:
        result = PipelineRunner(
            configuration,
            client,
            ResultWriter(configuration.output_dir),
        ).run()

    assert result.status == "completed"
    assert result.completed_iterations == 5
    assert result.initial_seeds[0].smiles == SILDENAFIL
    assert calls[:4] == [
        "generator/health",
        "synthesizability/health",
        "binding/health",
        "admet-moo/health",
    ]
    expected_iteration_calls = [
        "generator/generate",
        "synthesizability/score",
        "synthesizability/filter",
        "binding/score",
        "binding/filter",
        "admet-moo/optimize",
    ]
    assert calls[4:] == expected_iteration_calls * 5

    previous_seed_ids = {result.initial_seeds[0].id}
    for iteration in result.iterations:
        assert len(iteration.generated) == 3
        assert [stage.stage for stage in iteration.filter_stages] == [
            "synthesizability",
            "binding",
        ]
        assert len(iteration.selected) == 2
        assert {
            molecule.parent_id for molecule in iteration.generated
        } <= previous_seed_ids
        assert all(
            [score.stage for score in molecule.scores[-4:]]
            == ["generator", "synthesizability", "binding", "admet_moo"]
            for molecule in iteration.evaluated
        )
        previous_seed_ids = {molecule.id for molecule in iteration.selected}

    output_dir = results_root / "sildenafil-five-iteration-smoke-test"
    persisted = RunResult.model_validate_json(
        (output_dir / "run.json").read_text(encoding="utf-8")
    )
    assert persisted.completed_iterations == 5
    assert all(
        (output_dir / f"iteration_{iteration:03d}.json").is_file()
        for iteration in range(1, 6)
    )
