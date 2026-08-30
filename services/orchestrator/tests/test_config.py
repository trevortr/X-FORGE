from __future__ import annotations

from pathlib import Path

import pytest
from app.config import ConfigurationError, ConfigurationLoader


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
