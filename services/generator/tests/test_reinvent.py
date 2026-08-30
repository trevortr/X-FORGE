from __future__ import annotations

import csv
import subprocess
from pathlib import Path

import pytest
import tomllib
from app.domain import GenerationJob, RuntimeReadiness, Seed
from app.models import molecule_id
from app.reinvent import ReinventError, ReinventGenerator
from app.settings import Settings


def make_generator() -> ReinventGenerator:
    return ReinventGenerator(Settings(model_path=Path("/models/mol2mol.prior")))


def make_job(
    *,
    seeds: tuple[Seed, ...] = (Seed(smiles="CCO"),),
    n_candidates_per_seed: int = 100,
    strategy: str = "multinomial",
    temperature: float = 1.0,
    random_seed: int = 42,
) -> GenerationJob:
    return GenerationJob(
        seeds=seeds,
        n_candidates_per_seed=n_candidates_per_seed,
        strategy=strategy,
        temperature=temperature,
        random_seed=random_seed,
    )


def test_sampling_config_uses_mol2mol_request_parameters(tmp_path: Path) -> None:
    request = make_job(
        n_candidates_per_seed=25,
        strategy="beamsearch",
        temperature=0.8,
    )

    config = make_generator()._sampling_config(
        request,
        tmp_path / "seeds.smi",
        tmp_path / "output.csv",
    )

    assert 'run_type = "sampling"' in config
    assert 'model_file = "/models/mol2mol.prior"' in config
    assert "num_smiles = 25" in config
    assert 'sample_strategy = "beamsearch"' in config
    assert "temperature = 0.8" in config


def test_read_output_preserves_parent_and_model_scores(tmp_path: Path) -> None:
    output = tmp_path / "generated.csv"
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["SMILES", "SMILES_state", "Input_SMILES", "Tanimoto", "NLL"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "SMILES": "CCN",
                "SMILES_state": "VALID",
                "Input_SMILES": "CCO",
                "Tanimoto": "0.67",
                "NLL": "12.4",
            }
        )

    request = make_job(seeds=(Seed(smiles="CCO", id="hit-1"),))
    molecules = make_generator()._read_output(output, request)

    assert len(molecules) == 1
    assert molecules[0].smiles == "CCN"
    assert molecules[0].id == molecule_id("CCN")
    assert molecules[0].parent_id == "hit-1"
    assert molecules[0].tanimoto == pytest.approx(0.67)
    assert molecules[0].nll == pytest.approx(12.4)


def test_read_output_matches_canonicalized_parent_to_supplied_id(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "generated.csv"
    output.write_text(
        "SMILES,Input_SMILES,Tanimoto,NLL\nCCN,CCO-canonical,0.5,5.0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        ReinventGenerator,
        "_canonical_smiles",
        staticmethod(lambda smiles: f"{smiles}-canonical"),
    )

    molecules = make_generator()._read_output(
        output,
        make_job(seeds=(Seed(smiles="CCO", id="supplied-parent-id"),)),
    )

    assert molecules[0].parent_id == "supplied-parent-id"


def test_read_output_rejects_unknown_csv_shape(tmp_path: Path) -> None:
    output = tmp_path / "generated.csv"
    output.write_text("molecule,parent\nCCN,CCO\n", encoding="utf-8")
    request = make_job()

    with pytest.raises(ReinventError, match="Unexpected REINVENT4 CSV columns"):
        make_generator()._read_output(output, request)


def test_generate_invokes_reinvent_and_returns_response(monkeypatch) -> None:
    generator = make_generator()
    monkeypatch.setattr(
        generator,
        "runtime_readiness",
        lambda: RuntimeReadiness(True, True, True),
    )
    captured_command: list[str] = []

    def fake_run(command, **kwargs):
        captured_command.extend(command)
        with Path(command[1]).open("rb") as handle:
            config = tomllib.load(handle)
        output = Path(config["parameters"]["output_file"])
        output.write_text(
            "SMILES,SMILES_state,Input_SMILES,Tanimoto,NLL\nCCN,VALID,CCO,0.67,12.4\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    request = make_job(
        seeds=(Seed(smiles="CCO", id="hit-1"),),
        n_candidates_per_seed=20,
        random_seed=7,
    )

    response = generator.generate(request)

    assert response.requested == 20
    assert response.generated == 1
    assert response.molecules[0].parent_id == "hit-1"
    assert captured_command[-2:] == ["-s", "7"]


def test_runtime_readiness_probes_cli_once(monkeypatch) -> None:
    generator = make_generator()
    monkeypatch.setattr(generator, "readiness", lambda: (True, True))
    calls = 0

    def fake_run(command, **kwargs):
        nonlocal calls
        calls += 1
        assert command == ["reinvent", "--help"]
        return subprocess.CompletedProcess(
            command, returncode=0, stdout="help", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert generator.runtime_readiness().runtime_available is True
    assert generator.runtime_readiness().runtime_available is True
    assert calls == 1


def test_runtime_readiness_reports_cli_import_failure(monkeypatch) -> None:
    generator = make_generator()
    monkeypatch.setattr(generator, "readiness", lambda: (True, True))

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            returncode=1,
            stdout="",
            stderr="ImportError: libXrender.so.1: cannot open shared object file",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    readiness = generator.runtime_readiness()

    assert readiness.runtime_available is False
    assert "libXrender.so.1" in readiness.detail
