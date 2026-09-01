from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from libs.schemas import Molecule, ScoreRecord

from .client import GeneratedCandidate, ServiceCallError, ServiceClient
from .config import PipelineStage, RunConfiguration
from .results import FilterStageResult, IterationResult, ResultWriter, RunResult

logger = logging.getLogger(__name__)


class PipelineRunError(RuntimeError):
    pass


class MoleculeLedger:
    """Keep the latest append-only snapshot for each stable molecule ID."""

    def __init__(self, molecules: list[Molecule] | None = None) -> None:
        self._latest: dict[str, Molecule] = {}
        for molecule in molecules or []:
            self.record(molecule)

    def get(self, molecule_id: str) -> Molecule | None:
        return self._latest.get(molecule_id)

    def record(self, molecule: Molecule) -> None:
        assert molecule.id is not None
        previous = self._latest.get(molecule.id)
        if previous is not None:
            if previous.smiles != molecule.smiles:
                raise PipelineRunError(
                    f"molecule ID collision for {molecule.id}: "
                    f"{previous.smiles!r} != {molecule.smiles!r}"
                )
            prefix_length = len(previous.scores)
            if molecule.scores[:prefix_length] != previous.scores:
                raise PipelineRunError(
                    f"score history is not append-only for molecule {molecule.id}"
                )
        self._latest[molecule.id] = molecule.model_copy(deep=True)

    def catalog(self) -> list[Molecule]:
        return [self._latest[key] for key in sorted(self._latest)]


class PipelineRunner:
    def __init__(
        self,
        configuration: RunConfiguration,
        client: ServiceClient,
        writer: ResultWriter,
    ) -> None:
        self.configuration = configuration
        self.client = client
        self.writer = writer

    def run(self) -> RunResult:
        started_at = datetime.now(UTC)
        initial_seeds = [
            molecule.model_copy(update={"iteration": 0}, deep=True)
            for molecule in self.configuration.target.seeds
        ]
        ledger = MoleculeLedger(initial_seeds)
        run = RunResult(
            run_id=f"{started_at:%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}",
            target=self.configuration.target.name,
            status="running",
            started_at=started_at,
            requested_iterations=self.configuration.iterations,
            completed_iterations=0,
            initial_seeds=initial_seeds,
            molecule_catalog=ledger.catalog(),
        )
        self.writer.write_run(run)

        service_order = [
            "generator",
            *(
                [self.configuration.generator.reward.service]
                if self.configuration.generator.reward is not None
                else []
            ),
            *(stage.name for stage in self.configuration.stages),
            "admet_moo",
        ]
        try:
            self.client.wait_until_ready(list(dict.fromkeys(service_order)))
        except ServiceCallError as exc:
            run.status = "failed"
            run.completed_at = datetime.now(UTC)
            run.termination_reason = str(exc)
            self.writer.write_run(run)
            raise PipelineRunError(str(exc)) from exc

        seeds = initial_seeds
        termination_reason = "configured_iterations_completed"
        try:
            for iteration_number in range(1, self.configuration.iterations + 1):
                iteration = self._run_iteration(iteration_number, seeds, ledger)
                run.iterations.append(iteration)
                run.completed_iterations = iteration_number
                run.final_selected = iteration.selected
                run.molecule_catalog = ledger.catalog()
                self.writer.write_iteration(iteration)
                self.writer.write_run(run)

                if not iteration.generated:
                    termination_reason = "generator_returned_no_candidates"
                    break
                if not iteration.survivors:
                    termination_reason = "all_candidates_filtered"
                    break
                if not iteration.selected:
                    termination_reason = "admet_moo_selected_no_leads"
                    break
                seeds = iteration.selected
        except (ServiceCallError, PipelineRunError) as exc:
            run.status = "failed"
            run.completed_at = datetime.now(UTC)
            run.termination_reason = str(exc)
            run.molecule_catalog = ledger.catalog()
            self.writer.write_run(run)
            raise PipelineRunError(str(exc)) from exc

        run.status = "completed"
        run.completed_at = datetime.now(UTC)
        run.termination_reason = termination_reason
        run.molecule_catalog = ledger.catalog()
        self.writer.write_run(run)
        return run

    def _run_iteration(
        self,
        iteration_number: int,
        seeds: list[Molecule],
        ledger: MoleculeLedger,
    ) -> IterationResult:
        logger.info(
            "iteration %d/%d: generating from %d seed(s)",
            iteration_number,
            self.configuration.iterations,
            len(seeds),
        )
        reward = self.configuration.generator.reward
        generation_budget = self.configuration.candidates_per_iteration * (
            reward.pool_multiplier if reward is not None else 1
        )
        response = self.client.generate(
            seeds,
            total_candidates=generation_budget,
            strategy=self.configuration.generator.strategy,
            temperature=self.configuration.generator.temperature,
            random_seed=self.configuration.generator.random_seed + iteration_number - 1,
        )
        generated = self._normalize_generated(
            response.molecules,
            response.model,
            iteration_number,
            seeds,
            ledger,
        )
        current = generated
        filter_results: list[FilterStageResult] = []
        if reward is not None and current:
            reward_stage = self._reward_stage(reward.service, reward.parameters)
            scored = self.client.score(reward_stage, current)
            for molecule in scored:
                ledger.record(molecule)
            filtered = self.client.filter(reward_stage, scored)
            for molecule in [*filtered.passed, *filtered.rejected]:
                ledger.record(molecule)
            filter_results.append(
                FilterStageResult(
                    stage=reward_stage.name,
                    parameters=reward_stage.parameters,
                    input_count=len(current),
                    passed=filtered.passed,
                    rejected=filtered.rejected,
                )
            )
            current = filtered.passed
        for stage in self.configuration.stages:
            if not current:
                break
            logger.info(
                "iteration %d: %s scoring %d molecule(s)",
                iteration_number,
                stage.name,
                len(current),
            )
            scored = self.client.score(stage, current)
            for molecule in scored:
                ledger.record(molecule)
            filtered = self.client.filter(stage, scored)
            for molecule in [*filtered.passed, *filtered.rejected]:
                ledger.record(molecule)
            filter_results.append(
                FilterStageResult(
                    stage=stage.name,
                    parameters=stage.parameters,
                    input_count=len(current),
                    passed=filtered.passed,
                    rejected=filtered.rejected,
                )
            )
            current = filtered.passed
            if not current:
                break

        if not current:
            return IterationResult(
                iteration=iteration_number,
                seeds=seeds,
                requested_candidates=self.configuration.candidates_per_iteration,
                generator_model=response.model,
                generated=generated,
                filter_stages=filter_results,
                survivors=[],
                evaluated=[],
                pareto_front=[],
                selected=[],
            )

        optimized = self.client.optimize(
            current,
            top_k=self.configuration.top_k_feedback,
            properties=self.configuration.admet_moo.properties,
            selection=self.configuration.admet_moo.selection,
        )
        for molecule in optimized.molecules:
            ledger.record(molecule)
        evaluated_by_id = {molecule.id: molecule for molecule in optimized.molecules}
        selected = [evaluated_by_id[molecule.id] for molecule in optimized.selected]
        pareto_front = [
            evaluated_by_id[molecule.id] for molecule in optimized.pareto_front
        ]
        logger.info(
            "iteration %d: %d survivor(s), %d Pareto candidate(s), %d selected",
            iteration_number,
            len(current),
            len(pareto_front),
            len(selected),
        )
        return IterationResult(
            iteration=iteration_number,
            seeds=seeds,
            requested_candidates=self.configuration.candidates_per_iteration,
            generator_model=response.model,
            generated=generated,
            filter_stages=filter_results,
            survivors=current,
            evaluated=optimized.molecules,
            pareto_front=pareto_front,
            selected=selected,
        )

    def _reward_stage(
        self, name: str, parameters: dict[str, object]
    ) -> PipelineStage:
        return PipelineStage(
            name=name,
            parameters={
                **parameters,
                "top_k": self.configuration.candidates_per_iteration,
            },
        )

    @staticmethod
    def _normalize_generated(
        candidates: list[GeneratedCandidate],
        model: str,
        iteration_number: int,
        seeds: list[Molecule],
        ledger: MoleculeLedger,
    ) -> list[Molecule]:
        ids = [candidate.id for candidate in candidates]
        if len(ids) != len(set(ids)):
            raise PipelineRunError("generator returned duplicate molecule IDs")
        seed_ids = {seed.id for seed in seeds}
        normalized: list[Molecule] = []
        for candidate in candidates:
            if candidate.parent_id not in seed_ids:
                raise PipelineRunError(
                    f"generator returned unknown parent ID {candidate.parent_id!r}"
                )
            previous = ledger.get(candidate.id)
            base = Molecule(
                smiles=candidate.smiles,
                id=candidate.id,
                parent_id=candidate.parent_id,
                iteration=iteration_number,
                scores=list(previous.scores) if previous else [],
                generator_model=model,
                parent_smiles=candidate.parent_smiles,
            )
            values = {
                name: value
                for name, value in {
                    "tanimoto": candidate.tanimoto,
                    "nll": candidate.nll,
                }.items()
                if value is not None
            }
            molecule = base.with_score(
                ScoreRecord(
                    stage="generator",
                    values=values,
                    passed=None,
                    computed_at_iteration=iteration_number,
                )
            )
            ledger.record(molecule)
            normalized.append(molecule)
        return normalized
