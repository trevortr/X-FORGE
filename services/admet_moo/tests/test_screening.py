from __future__ import annotations

from app.models import ADMETScreenParameters
from app.screening import ADMETScreen


def row(**updates: float) -> dict[str, float]:
    values = {
        "Solubility_AqSolDB": -3.0,
        "Clearance_Microsome_AZ": 20.0,
        "Clearance_Hepatocyte_AZ": 20.0,
        "Half_Life_Obach": 3.0,
        "Caco2_Wang": 0.5,
        "Pgp_Broccatelli": 0.2,
        "hERG": 0.2,
        "CYP3A4_Veith": 0.2,
        "CYP2D6_Veith": 0.2,
        "CYP2C9_Veith": 0.2,
    }
    return {**values, **updates}


def test_admet_gate_applies_thresholds_and_population_pruning() -> None:
    results = ADMETScreen().evaluate(
        [row(), row(Solubility_AqSolDB=-5.0)],
        ADMETScreenParameters(
            max_microsomal_clint=50.0,
            max_hepatocyte_clint=50.0,
            max_candidates=1,
        ),
    )

    assert results[0].passed is True
    assert results[1].passed is False
    assert "permeability" in results[0].desirabilities


def test_exact_efflux_and_pic50_endpoints_override_risk_probabilities() -> None:
    values = row(pgp_efflux_ratio=2.0, herg_pic50=4.0)
    result = ADMETScreen().evaluate(
        [values],
        ADMETScreenParameters(
            pgp_efflux_ratio_column="pgp_efflux_ratio",
            herg_pic50_column="herg_pic50",
        ),
    )[0]

    assert result.values["pgp_efflux_ratio"] == 2.0
    assert result.values["herg_pic50"] == 4.0
    assert result.passed is True
