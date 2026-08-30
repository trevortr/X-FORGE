from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from pymoo.indicators.hv import HV
from pymoo.mcdm.high_tradeoff import HighTradeoffPoints
from pymoo.util.nds.non_dominated_sorting import NonDominatedSorting

from .properties import ADMETProperty, ADMETPropertyRegistry

SelectionMethod = Literal[
    "knee_point",
    "desirability",
    "hypervolume_contribution",
]


class OptimizationError(ValueError):
    pass


@dataclass(frozen=True)
class EvaluatedCandidate:
    predictions: dict[str, float]
    objectives: dict[str, float]
    desirabilities: dict[str, float]
    pareto_rank: int
    selection_score: float | None
    selected: bool


@dataclass(frozen=True)
class OptimizationResult:
    candidates: tuple[EvaluatedCandidate, ...]
    pareto_indices: tuple[int, ...]
    selected_indices: tuple[int, ...]
    properties: tuple[ADMETProperty, ...]


def _normalize(objectives: np.ndarray) -> np.ndarray:
    ideal = objectives.min(axis=0)
    spans = objectives.max(axis=0) - ideal
    return np.divide(
        objectives - ideal,
        spans,
        out=np.zeros_like(objectives, dtype=float),
        where=spans > 0,
    )


def _stable_descending(values: np.ndarray) -> list[int]:
    return sorted(range(len(values)), key=lambda index: (-float(values[index]), index))


def _knee_scores(normalized: np.ndarray) -> np.ndarray:
    # Distance-to-ideal gives a deterministic compromise ranking when pymoo finds
    # fewer knee points than the requested number of leads.
    dimensions = max(normalized.shape[1], 1)
    compromise = 1.0 - np.linalg.norm(normalized, axis=1) / np.sqrt(dimensions)
    knee_indices: np.ndarray = np.array([], dtype=int)
    if len(normalized) >= 3 and normalized.shape[1] >= 2 and np.any(normalized):
        try:
            found = HighTradeoffPoints()(normalized)
            if found is not None:
                knee_indices = np.atleast_1d(found).astype(int)
        except (ValueError, IndexError, FloatingPointError):
            knee_indices = np.array([], dtype=int)
    scores = compromise
    scores[knee_indices] += 1.0
    return scores


def _desirability_scores(
    desirabilities: np.ndarray,
    properties: list[ADMETProperty],
    weights: dict[str, float] | None,
) -> np.ndarray:
    weights = weights or {}
    unknown_weights = sorted(set(weights) - {prop.key for prop in properties})
    if unknown_weights:
        raise OptimizationError(
            f"weights reference inactive properties: {', '.join(unknown_weights)}"
        )
    weight_array = np.array(
        [weights.get(prop.key, 1.0) for prop in properties], dtype=float
    )
    if not np.all(np.isfinite(weight_array)) or np.any(weight_array <= 0):
        raise OptimizationError(
            "all desirability weights must be finite and greater than zero"
        )

    scores = np.zeros(len(desirabilities), dtype=float)
    positive = np.all(desirabilities > 0, axis=1)
    scores[positive] = np.exp(
        np.average(np.log(desirabilities[positive]), axis=1, weights=weight_array)
    )
    return scores


def _hypervolume_scores(
    normalized: np.ndarray,
    properties: list[ADMETProperty],
    configured_reference: dict[str, float] | None,
) -> np.ndarray:
    configured_reference = configured_reference or {}
    unknown = sorted(set(configured_reference) - {prop.key for prop in properties})
    if unknown:
        raise OptimizationError(
            f"reference point contains inactive properties: {', '.join(unknown)}"
        )
    reference = np.array(
        [configured_reference.get(prop.key, 1.1) for prop in properties],
        dtype=float,
    )
    if not np.all(np.isfinite(reference)):
        raise OptimizationError("hypervolume reference values must be finite")
    if np.any(reference <= normalized.max(axis=0)):
        raise OptimizationError(
            "each hypervolume reference value must be worse than the normalized Pareto front"
        )

    indicator = HV(ref_point=reference)
    total = float(indicator(normalized))
    return np.array(
        [
            max(0.0, total - float(indicator(np.delete(normalized, index, axis=0))))
            for index in range(len(normalized))
        ]
    )


class ADMETOptimizer:
    def __init__(self, registry: ADMETPropertyRegistry) -> None:
        self.registry = registry

    def optimize(
        self,
        prediction_rows: list[dict[str, float]],
        *,
        top_k: int,
        method: SelectionMethod,
        property_keys: list[str] | None = None,
        weights: dict[str, float] | None = None,
        reference_point: dict[str, float] | None = None,
    ) -> OptimizationResult:
        if not prediction_rows:
            raise OptimizationError("at least one prediction row is required")
        if top_k < 1:
            raise OptimizationError("top_k must be at least one")
        try:
            properties = self.registry.create(property_keys)
            property_values = np.array(
                [
                    [prop.prediction(row) for prop in properties]
                    for row in prediction_rows
                ],
                dtype=float,
            )
        except (KeyError, ValueError) as exc:
            raise OptimizationError(str(exc)) from exc

        objectives = np.array(
            [
                [prop.objective(value) for prop, value in zip(properties, row)]
                for row in property_values
            ],
            dtype=float,
        )
        desirabilities = np.array(
            [
                [prop.desirability(value) for prop, value in zip(properties, row)]
                for row in property_values
            ],
            dtype=float,
        )

        fronts = NonDominatedSorting().do(objectives)
        ranks = np.empty(len(objectives), dtype=int)
        for rank, front in enumerate(fronts):
            ranks[front] = rank

        pareto_indices = np.asarray(fronts[0], dtype=int)
        normalized = _normalize(objectives[pareto_indices])
        if method == "knee_point":
            front_scores = _knee_scores(normalized)
        elif method == "desirability":
            front_scores = _desirability_scores(
                desirabilities[pareto_indices], properties, weights
            )
        elif method == "hypervolume_contribution":
            front_scores = _hypervolume_scores(normalized, properties, reference_point)
        else:
            raise OptimizationError(f"unknown selection method: {method}")

        selected_local = _stable_descending(front_scores)[
            : min(top_k, len(pareto_indices))
        ]
        selected_indices = tuple(int(pareto_indices[index]) for index in selected_local)
        selected_set = set(selected_indices)
        front_score_by_index = {
            int(pareto_indices[index]): float(score)
            for index, score in enumerate(front_scores)
        }

        candidates = tuple(
            EvaluatedCandidate(
                predictions={
                    prop.key: float(value)
                    for prop, value in zip(properties, property_values[index])
                },
                objectives={
                    prop.key: float(value)
                    for prop, value in zip(properties, objectives[index])
                },
                desirabilities={
                    prop.key: float(value)
                    for prop, value in zip(properties, desirabilities[index])
                },
                pareto_rank=int(ranks[index]),
                selection_score=front_score_by_index.get(index),
                selected=index in selected_set,
            )
            for index in range(len(prediction_rows))
        )
        return OptimizationResult(
            candidates=candidates,
            pareto_indices=tuple(int(index) for index in pareto_indices),
            selected_indices=selected_indices,
            properties=tuple(properties),
        )
