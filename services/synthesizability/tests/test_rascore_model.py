from __future__ import annotations

import pytest
from rdkit import Chem

from app.scorer import RAScorePredictor


def test_pinned_model_reproduces_upstream_omeprazole_example() -> None:
    molecule = Chem.MolFromSmiles("CC1=CN=C(C(=C1OC)C)CS(=O)C2=NC3=C(N2)C=C(C=C3)OC")
    assert molecule is not None

    score = RAScorePredictor().predict(molecule)

    assert score == pytest.approx(0.9556329, abs=1e-6)
