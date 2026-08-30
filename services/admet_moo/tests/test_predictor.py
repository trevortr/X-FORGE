from __future__ import annotations

import pandas as pd
import pytest
from app.predictor import ADMETAIPredictor, InvalidMoleculeError
from app.settings import Settings


class FakeModel:
    device = "cpu"

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def predict(self, smiles: list[str]) -> pd.DataFrame:
        return pd.DataFrame(
            [{"Bioavailability_Ma": index / 10} for index, _ in enumerate(smiles, 1)],
            index=smiles,
        )


def test_predictor_loads_once_and_preserves_input_order() -> None:
    created: list[FakeModel] = []

    def factory(**kwargs):
        model = FakeModel(**kwargs)
        created.append(model)
        return model

    predictor = ADMETAIPredictor(Settings(), model_factory=factory)

    rows = predictor.predict(["CCO", "CCN"])
    readiness = predictor.readiness()

    assert rows == [{"Bioavailability_Ma": 0.1}, {"Bioavailability_Ma": 0.2}]
    assert readiness.available is True
    assert len(created) == 1
    assert created[0].kwargs["include_physchem"] is False
    assert created[0].kwargs["drugbank_path"] is None


class FilteringModel(FakeModel):
    def predict(self, smiles: list[str]) -> pd.DataFrame:
        return super().predict(smiles[:1])


def test_predictor_rejects_batch_when_admet_ai_filters_invalid_smiles() -> None:
    predictor = ADMETAIPredictor(Settings(), model_factory=FilteringModel)

    with pytest.raises(InvalidMoleculeError, match="discarded"):
        predictor.predict(["CCO", "invalid"])
