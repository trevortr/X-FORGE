from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from pymoo.util.nds.non_dominated_sorting import NonDominatedSorting

from .models import ADMETScreenParameters


class ADMETScreenError(ValueError):
    pass


@dataclass(frozen=True)
class ScreenedCandidate:
    values: dict[str, float]
    desirabilities: dict[str, float]
    pareto_rank: int
    passed: bool


def _value(row: dict[str, float], column: str | None) -> float | None:
    if column is None:
        return None
    if column not in row:
        raise ADMETScreenError(f"predictor did not return required endpoint {column!r}")
    value = float(row[column])
    if not math.isfinite(value):
        raise ADMETScreenError(f"endpoint {column!r} must be finite")
    return value


def _higher(value: float, threshold: float, span: float) -> float:
    return min(1.0, max(0.0, 0.5 + (value - threshold) / (2.0 * span)))


def _lower(value: float, threshold: float, span: float) -> float:
    return min(1.0, max(0.0, 0.5 + (threshold - value) / (2.0 * span)))


class ADMETScreen:
    """Threshold and Pareto-prune model-native or externally supplied endpoints."""

    def evaluate(
        self,
        rows: list[dict[str, float]],
        parameters: ADMETScreenParameters,
    ) -> list[ScreenedCandidate]:
        raw: list[tuple[dict[str, float], dict[str, float], bool]] = [
            self._evaluate_row(row, parameters) for row in rows
        ]
        objective_keys = sorted(
            set.intersection(
                *(set(desirabilities) for _, desirabilities, _ in raw)
            )
        )
        if not objective_keys:
            raise ADMETScreenError("ADMET screening produced no common objectives")
        objectives = np.asarray(
            [
                [-desirabilities[key] for key in objective_keys]
                for _, desirabilities, _ in raw
            ],
            dtype=float,
        )
        fronts = NonDominatedSorting().do(objectives)
        ranks = np.empty(len(rows), dtype=int)
        for rank, front in enumerate(fronts):
            ranks[front] = rank

        eligible = [index for index, (_, _, gated) in enumerate(raw) if gated]
        eligible.sort(
            key=lambda index: (
                int(ranks[index]),
                -self._geometric_mean(raw[index][1]),
                index,
            )
        )
        retained = set(
            eligible[
                : parameters.max_candidates
                if parameters.max_candidates is not None
                else len(eligible)
            ]
        )
        return [
            ScreenedCandidate(
                values=values,
                desirabilities=desirabilities,
                pareto_rank=int(ranks[index]),
                passed=gated and index in retained,
            )
            for index, (values, desirabilities, gated) in enumerate(raw)
        ]

    def _evaluate_row(
        self, row: dict[str, float], p: ADMETScreenParameters
    ) -> tuple[dict[str, float], dict[str, float], bool]:
        values: dict[str, float] = {}
        desirabilities: dict[str, float] = {}
        gates: list[bool] = []

        log_s = _value(row, p.solubility_column)
        assert log_s is not None
        values["aqueous_solubility_log_s"] = log_s
        desirabilities["solubility"] = _higher(log_s, p.min_log_s, 2.0)
        gates.append(log_s > p.min_log_s)

        microsomal = _value(row, p.microsomal_clearance_column)
        hepatocyte = _value(row, p.hepatocyte_clearance_column)
        half_life = _value(row, p.half_life_column)
        metabolic_gates: list[bool] = []
        if microsomal is not None:
            values["microsomal_clint"] = microsomal
            if p.max_microsomal_clint is not None:
                desirabilities["microsomal_clearance"] = _lower(
                    microsomal, p.max_microsomal_clint, max(p.max_microsomal_clint, 1.0)
                )
                metabolic_gates.append(microsomal <= p.max_microsomal_clint)
        if hepatocyte is not None:
            values["hepatocyte_clint"] = hepatocyte
            if p.max_hepatocyte_clint is not None:
                desirabilities["hepatocyte_clearance"] = _lower(
                    hepatocyte, p.max_hepatocyte_clint, max(p.max_hepatocyte_clint, 1.0)
                )
                metabolic_gates.append(hepatocyte <= p.max_hepatocyte_clint)
        if half_life is not None:
            values["half_life"] = half_life
            if p.min_half_life is not None:
                desirabilities["half_life"] = _higher(
                    half_life, p.min_half_life, max(p.min_half_life, 1.0)
                )
                metabolic_gates.append(half_life >= p.min_half_life)
        if metabolic_gates:
            gates.append(any(metabolic_gates))

        permeabilities = [
            value
            for value in (
                _value(row, p.caco2_log_papp_column),
                _value(row, p.mdck_log_papp_column),
            )
            if value is not None
        ]
        if not permeabilities:
            raise ADMETScreenError("Caco-2 or MDCK permeability is required")
        permeability = max(permeabilities)
        values["permeability_log_papp"] = permeability
        desirabilities["permeability"] = _higher(permeability, p.min_log_papp, 2.0)
        gates.append(permeability > p.min_log_papp)

        efflux = _value(row, p.pgp_efflux_ratio_column)
        pgp_risk = _value(row, p.pgp_risk_column)
        if efflux is not None:
            values["pgp_efflux_ratio"] = efflux
            desirabilities["pgp"] = _lower(efflux, p.max_pgp_efflux_ratio, 2.0)
            gates.append(efflux < p.max_pgp_efflux_ratio)
        elif pgp_risk is not None:
            values["pgp_risk_probability"] = pgp_risk
            desirabilities["pgp"] = 1.0 - min(1.0, max(0.0, pgp_risk))
            gates.append(pgp_risk <= p.max_pgp_risk)
        else:
            raise ADMETScreenError("P-gp efflux ratio or risk endpoint is required")

        herg_pic50 = _value(row, p.herg_pic50_column)
        herg_risk = _value(row, p.herg_risk_column)
        if herg_pic50 is not None:
            values["herg_pic50"] = herg_pic50
            desirabilities["herg"] = _lower(herg_pic50, p.max_herg_pic50, 2.0)
            gates.append(herg_pic50 < p.max_herg_pic50)
        elif herg_risk is not None:
            values["herg_risk_probability"] = herg_risk
            desirabilities["herg"] = 1.0 - min(1.0, max(0.0, herg_risk))
            gates.append(herg_risk <= p.max_herg_risk)
        else:
            raise ADMETScreenError("hERG pIC50 or risk endpoint is required")

        for name, column in p.cyp_risk_columns.items():
            risk = _value(row, column)
            assert risk is not None
            values[f"{name}_inhibition_risk"] = risk
            desirabilities[name] = 1.0 - min(1.0, max(0.0, risk))
            gates.append(risk <= p.max_cyp_risk)
        return values, desirabilities, all(gates)

    @staticmethod
    def _geometric_mean(values: dict[str, float]) -> float:
        if any(value <= 0 for value in values.values()):
            return 0.0
        return math.exp(sum(math.log(value) for value in values.values()) / len(values))
