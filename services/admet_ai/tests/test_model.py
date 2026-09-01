from __future__ import annotations

from admet import Admet


class DictModel:
    def predict(self, *, smiles: list[str]):
        assert smiles == ["CCO"]
        return {"QED": 0.8, "hERG": 0.1}


def test_legacy_getters_and_object_response_remain_available() -> None:
    model = Admet(model=DictModel())
    model.run("CCO")

    assert model.get_QED() == 0.8
    assert model.get_herg() == 0.1
    assert model.as_obj().QED == 0.8
