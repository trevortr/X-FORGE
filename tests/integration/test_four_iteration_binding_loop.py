from __future__ import annotations

import json
from pathlib import Path

import httpx

from libs.schemas import molecule_id
from services.orchestrator.app.client import ServiceClient
from services.orchestrator.app.config import ConfigurationLoader
from services.orchestrator.app.results import ResultWriter, RunResult
from services.orchestrator.app.runner import PipelineRunner

IBUPROFEN = "CC(C)Cc1ccc(cc1)[C@@H](C)C(=O)O"


def test_ibuprofen_completes_four_generation_binding_admet_iterations(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config"
    targets_dir = config_dir / "targets"
    targets_dir.mkdir(parents=True)
    (config_dir / "pipeline.yaml").write_text(
        """\
target: targets/ibuprofen.yaml
pipeline:
  - binding:
      receptor_pdbqt: /targets/cox2/receptor.pdbqt
      receptor_pdb: /targets/cox2/protein.pdb
      box_center: [13.008, 23.487, 25.256]
      box_size: [22.0, 22.0, 22.0]
iterations: 4
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
  binding: http://binding:12004
  admet_moo: http://admet-moo:12001
""",
        encoding="utf-8",
    )
    (targets_dir / "ibuprofen.yaml").write_text(
        f'name: ibuprofen-cox2\nseeds:\n  - smiles: "{IBUPROFEN}"\n',
        encoding="utf-8",
    )

    generate_calls = 0
    call_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal generate_calls
        call_paths.append(request.url.path)
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
                    smiles = "C" * chain_length + "O"
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
        if request.url.path == "/score":
            return httpx.Response(
                200,
                json={
                    "molecules": [
                        {
                            **molecule,
                            "scores": [
                                *molecule["scores"],
                                {
                                    "stage": "binding",
                                    "values": {
                                        "docking_succeeded": 1.0,
                                        "vina_score": -7.5,
                                        "vina_ligand_efficiency": 0.4,
                                    },
                                    "passed": True,
                                    "computed_at_iteration": molecule["iteration"],
                                },
                            ],
                        }
                        for molecule in payload["molecules"]
                    ]
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
        run_name_override="ibuprofen-binding-smoke-test",
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
    assert result.completed_iterations == 4
    assert result.initial_seeds[0].smiles == IBUPROFEN
    assert len(result.iterations) == 4
    assert call_paths[:3] == ["/health", "/health", "/health"]
    assert call_paths[3:] == [
        path
        for _ in range(4)
        for path in ("/generate", "/score", "/filter", "/optimize")
    ]

    previous_seed_ids = {result.initial_seeds[0].id}
    for iteration in result.iterations:
        assert len(iteration.generated) == 3
        assert len(iteration.filter_stages) == 1
        assert len(iteration.filter_stages[0].passed) == 3
        assert len(iteration.selected) == 2
        assert {
            molecule.parent_id for molecule in iteration.generated
        } <= previous_seed_ids
        assert all(
            [score.stage for score in molecule.scores[-3:]]
            == ["generator", "binding", "admet_moo"]
            for molecule in iteration.evaluated
        )
        previous_seed_ids = {molecule.id for molecule in iteration.selected}

    output_dir = results_root / "ibuprofen-binding-smoke-test"
    assert (output_dir / "run.json").is_file()
    assert all(
        (output_dir / f"iteration_{iteration:03d}.json").is_file()
        for iteration in range(1, 5)
    )
    persisted = RunResult.model_validate_json(
        (output_dir / "run.json").read_text(encoding="utf-8")
    )
    assert persisted.completed_iterations == 4
    assert persisted.iterations[-1].filter_stages[0].stage == "binding"
