from __future__ import annotations

import pytest

from app.models import DesirabilityCurve
from app.scorer import evaluate_curve, weighted_geometric_mean


def test_piecewise_curve_is_continuous_and_interpolated() -> None:
    curve = DesirabilityCurve(
        points=[
            {"x": 0.0, "desirability": 0.0},
            {"x": 2.0, "desirability": 1.0},
            {"x": 4.0, "desirability": 0.0},
        ]
    )

    assert evaluate_curve(-1.0, curve) == 0.0
    assert evaluate_curve(1.0, curve) == 0.5
    assert evaluate_curve(2.0, curve) == 1.0
    assert evaluate_curve(3.0, curve) == 0.5
    assert evaluate_curve(5.0, curve) == 0.0


def test_weighted_geometric_mean_matches_definition() -> None:
    score = weighted_geometric_mean(
        {"a": 0.25, "b": 1.0},
        {"a": 1.0, "b": 3.0},
    )

    assert score == pytest.approx((0.25 * 1.0**3) ** 0.25)
    assert weighted_geometric_mean({"a": 0.0}, {"a": 1.0}) == 0.0
