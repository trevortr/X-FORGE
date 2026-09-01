from __future__ import annotations

from pathlib import Path

import yaml
from app.config import ConfigurationLoader
from services.admet_moo.app.models import ADMETScreenParameters
from services.admet_moo.app.properties import property_registry
from services.binding.app.models import BindingParameters
from services.physchem.app.models import PhyschemParameters
from services.physics.app.models import PhysicsParameters
from services.policy_scoring.app.models import PolicyScoringParameters
from services.synthesizability.app.models import SynthesizabilityParameters


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPOSITORY_ROOT / "config" / "examples"
STAGE_PARAMETERS = {
    "admet_screen": ADMETScreenParameters,
    "binding": BindingParameters,
    "physchem": PhyschemParameters,
    "physics": PhysicsParameters,
    "synthesizability": SynthesizabilityParameters,
}


def test_all_ten_example_pipelines_validate(tmp_path: Path) -> None:
    paths = sorted(EXAMPLES.glob("*.yaml"))
    assert len(paths) == 10

    available_properties = {prop.key for prop in property_registry.all()}
    for path in paths:
        configuration = ConfigurationLoader.load(
            path,
            REPOSITORY_ROOT / "config" / "services.yaml",
            run_name_override=path.stem,
            results_root_override=tmp_path,
        )
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        reward = payload.get("generator", {}).get("reward")
        if reward is not None:
            PolicyScoringParameters.model_validate(reward["parameters"])
        for stage in configuration.stages:
            STAGE_PARAMETERS[stage.name].model_validate(stage.parameters)

        requested = payload.get("admet_moo", {}).get("properties")
        if requested is not None:
            assert set(requested) <= available_properties
