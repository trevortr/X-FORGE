from __future__ import annotations

import json
from pathlib import Path

import httpx

from libs.schemas import molecule_id
from services.orchestrator.app.client import ServiceClient
from services.orchestrator.app.config import ConfigurationLoader
from services.orchestrator.app.results import ResultWriter, RunResult
from services.orchestrator.app.runner import PipelineRunner

ACETAMINOPHEN = "CC(=O)NC1=CC=C(C=C1)O"


def test_acetaminophen_completes_three_iteration_feedback_loop(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config"
    targets_dir = config_dir / "targets"
    targets_dir.mkdir(parents=True)
    (config_dir / "pipeline.yaml").write_text(
        """\
target: targets/acetaminophen.yaml
pipeline: []
iterations: 3
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
  admet_moo: http://admet-moo:12001
""",
        encoding="utf-8",
    )
    (targets_dir / "acetaminophen.yaml").write_text(
        f'name: acetaminophen\nseeds:\n  - smiles: "{ACETAMINOPHEN}"\n',
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
        if request.url.path == "/optimize":
            evaluated = []
            for rank, molecule in enumerate(payload["molecules"]):
                evaluated_molecule = {
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
                evaluated.append(evaluated_molecule)
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
    output_dir = results_root / "acetaminophen-smoke-test"
    configuration = ConfigurationLoader.load(
        config_dir / "pipeline.yaml",
        config_dir / "services.yaml",
        run_name_override="acetaminophen-smoke-test",
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
    assert result.completed_iterations == 3
    assert result.initial_seeds[0].smiles == ACETAMINOPHEN
    assert len(result.iterations) == 3
    assert call_paths == [
        "/health",
        "/health",
        "/generate",
        "/optimize",
        "/generate",
        "/optimize",
        "/generate",
        "/optimize",
    ]

    previous_seed_ids = {result.initial_seeds[0].id}
    for iteration in result.iterations:
        assert len(iteration.generated) == 3
        assert len(iteration.selected) == 2
        assert {
            molecule.parent_id for molecule in iteration.generated
        } <= previous_seed_ids
        assert all(
            molecule.scores[-1].stage == "generator"
            and molecule.scores[-1].computed_at_iteration == iteration.iteration
            for molecule in iteration.generated
        )
        assert all(
            [score.stage for score in molecule.scores[-2:]]
            == ["generator", "admet_moo"]
            for molecule in iteration.evaluated
        )
        previous_seed_ids = {molecule.id for molecule in iteration.selected}

    assert result.final_selected == result.iterations[-1].selected
    assert (output_dir / "run.json").is_file()
    assert all(
        (output_dir / f"iteration_{iteration:03d}.json").is_file()
        for iteration in range(1, 4)
    )
    persisted = RunResult.model_validate_json(
        (output_dir / "run.json").read_text(encoding="utf-8")
    )
    assert persisted.completed_iterations == 3
