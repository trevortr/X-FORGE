from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.config import ConfigurationError, ConfigurationLoader


def _write_minimal_configuration(directory: Path, target_name: str = "demo") -> None:
    (directory / "target.yaml").write_text(
        f"name: {target_name}\nseeds:\n  - smiles: CCO\n", encoding="utf-8"
    )
    (directory / "pipeline.yaml").write_text(
        "target: target.yaml\npipeline: []\n", encoding="utf-8"
    )
    (directory / "services.yaml").write_text(
        "services:\n  generator: http://generator:12000\n"
        "  admet_moo: http://admet-moo:12001\n",
        encoding="utf-8",
    )


def test_loader_fails_fast_when_pipeline_service_is_missing(tmp_path: Path) -> None:
    (tmp_path / "target.yaml").write_text(
        "name: demo\nseeds:\n  - smiles: CCO\n", encoding="utf-8"
    )
    (tmp_path / "pipeline.yaml").write_text(
        "target: target.yaml\npipeline:\n  - docking: {}\n", encoding="utf-8"
    )
    (tmp_path / "services.yaml").write_text(
        "services:\n  generator: http://generator:12000\n"
        "  admet_moo: http://admet-moo:12001\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="docking"):
        ConfigurationLoader.load(tmp_path / "pipeline.yaml", tmp_path / "services.yaml")


def test_loader_uses_runtime_run_name_beneath_results_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_minimal_configuration(tmp_path)
    results_root = tmp_path / "results"
    monkeypatch.setenv("XFORGE_RUN_NAME", "my-compose-run")
    monkeypatch.setenv("XFORGE_RESULTS_ROOT", str(results_root))

    configuration = ConfigurationLoader.load(
        tmp_path / "pipeline.yaml", tmp_path / "services.yaml"
    )

    assert configuration.run_name == "my-compose-run"
    assert configuration.output_dir == results_root / "my-compose-run"


def test_loader_generates_target_timestamp_name_when_run_name_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_minimal_configuration(tmp_path, target_name="Acetaminophen Demo")
    monkeypatch.setenv("XFORGE_RUN_NAME", "")
    results_root = tmp_path / "results"

    configuration = ConfigurationLoader.load(
        tmp_path / "pipeline.yaml",
        tmp_path / "services.yaml",
        results_root_override=results_root,
        current_time=datetime(2026, 8, 30, 19, 46, 31, 123456, tzinfo=UTC),
    )

    assert configuration.run_name == "acetaminophen-demo-20260830T194631123456Z"
    assert configuration.output_dir == results_root / configuration.run_name


@pytest.mark.parametrize(
    "run_name", ["../escape", "nested/run", "has spaces", ".hidden"]
)
def test_loader_rejects_unsafe_run_names(tmp_path: Path, run_name: str) -> None:
    _write_minimal_configuration(tmp_path)

    with pytest.raises(ConfigurationError, match="run name"):
        ConfigurationLoader.load(
            tmp_path / "pipeline.yaml",
            tmp_path / "services.yaml",
            run_name_override=run_name,
        )


def test_loader_requires_configured_policy_reward_service(tmp_path: Path) -> None:
    _write_minimal_configuration(tmp_path)
    (tmp_path / "pipeline.yaml").write_text(
        "target: target.yaml\npipeline: []\n"
        "generator:\n"
        "  reward:\n"
        "    service: policy_scoring\n"
        "    parameters:\n"
        "      affinity_training_set:\n"
        "        - {smiles: CCO, value: -8.0}\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="policy_scoring"):
        ConfigurationLoader.load(tmp_path / "pipeline.yaml", tmp_path / "services.yaml")
