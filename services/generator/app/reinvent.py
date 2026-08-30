from __future__ import annotations

import csv
import json
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from .domain import (
    GeneratedCandidate,
    GenerationJob,
    GenerationResult,
    RuntimeReadiness,
)
from .models import molecule_id
from .settings import Settings


class ReinventError(RuntimeError):
    """REINVENT4 could not complete a generation request."""


class ReinventNotReadyError(ReinventError):
    """The executable or Mol2Mol prior is unavailable."""


class ReinventTimeoutError(ReinventError):
    """REINVENT4 exceeded the configured request timeout."""


class ReinventGenerator:
    """File/CLI adapter around REINVENT4 Mol2Mol sampling.

    REINVENT4 is intentionally kept out of the HTTP layer. Each request gets an
    isolated working directory, while the semaphore prevents concurrent model
    processes from exhausting the service's CPU/GPU memory.
    """

    def __init__(self, settings: Settings, max_concurrent_runs: int = 1) -> None:
        self.settings = settings
        self._run_slots = threading.BoundedSemaphore(max_concurrent_runs)
        self._probe_lock = threading.Lock()
        self._runtime_probe: tuple[bool, str | None] | None = None

    def readiness(self) -> tuple[bool, bool]:
        executable_available = (
            shutil.which(self.settings.reinvent_executable) is not None
        )
        model_available = self.settings.model_path.is_file()
        return executable_available, model_available

    def runtime_readiness(self) -> RuntimeReadiness:
        """Check static assets and probe whether the REINVENT CLI can import.

        Native dependencies do not change during a container's lifetime, so the
        comparatively expensive CLI probe is cached after its first execution.
        """
        executable_available, model_available = self.readiness()
        missing = []
        if not executable_available:
            missing.append(f"executable {self.settings.reinvent_executable!r}")
        if not model_available:
            missing.append(f"model {str(self.settings.model_path)!r}")
        if missing:
            return RuntimeReadiness(
                executable_available=executable_available,
                model_available=model_available,
                runtime_available=False,
                detail="Missing " + " and ".join(missing),
            )

        with self._probe_lock:
            if self._runtime_probe is None:
                self._runtime_probe = self._probe_reinvent_cli()
            runtime_available, detail = self._runtime_probe

        return RuntimeReadiness(
            executable_available=True,
            model_available=True,
            runtime_available=runtime_available,
            detail=detail,
        )

    def _probe_reinvent_cli(self) -> tuple[bool, str | None]:
        try:
            completed = subprocess.run(
                [self.settings.reinvent_executable, "--help"],
                capture_output=True,
                check=False,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"REINVENT4 runtime probe failed: {exc}"

        if completed.returncode == 0:
            return True, None
        details = completed.stderr.strip() or completed.stdout.strip()
        details = details[-2_000:] if details else f"exit code {completed.returncode}"
        return False, f"REINVENT4 runtime probe failed: {details}"

    def generate(self, request: GenerationJob) -> GenerationResult:
        readiness = self.runtime_readiness()
        if not readiness.runtime_available:
            raise ReinventNotReadyError(readiness.detail or "REINVENT4 is not ready")

        with (
            self._run_slots,
            tempfile.TemporaryDirectory(prefix="xforge-reinvent-") as tmp,
        ):
            workdir = Path(tmp)
            seeds_path = workdir / "seeds.smi"
            output_path = workdir / "generated.csv"
            config_path = workdir / "sampling.toml"
            log_path = workdir / "reinvent.log"

            seeds_path.write_text(
                "".join(f"{seed.smiles}\n" for seed in request.seeds),
                encoding="utf-8",
            )
            config_path.write_text(
                self._sampling_config(request, seeds_path, output_path),
                encoding="utf-8",
            )

            command = [
                self.settings.reinvent_executable,
                str(config_path),
                "-l",
                str(log_path),
                "-s",
                str(request.random_seed),
            ]
            try:
                completed = subprocess.run(
                    command,
                    cwd=workdir,
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=self.settings.timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                raise ReinventTimeoutError(
                    f"REINVENT4 exceeded {self.settings.timeout_seconds} seconds"
                ) from exc

            if completed.returncode != 0 or not output_path.is_file():
                details = self._failure_details(completed, log_path)
                raise ReinventError(f"REINVENT4 sampling failed: {details}")

            molecules = self._read_output(output_path, request)
            return GenerationResult(
                molecules=tuple(molecules),
                requested=len(request.seeds) * request.n_candidates_per_seed,
                generated=len(molecules),
                model=self.settings.model_path.name,
            )

    def _sampling_config(
        self,
        request: GenerationJob,
        seeds_path: Path,
        output_path: Path,
    ) -> str:
        quote = json.dumps
        return "\n".join(
            [
                'run_type = "sampling"',
                f"device = {quote(self.settings.device)}",
                "",
                "[parameters]",
                f"model_file = {quote(str(self.settings.model_path))}",
                f"smiles_file = {quote(str(seeds_path))}",
                f"output_file = {quote(str(output_path))}",
                f"num_smiles = {request.n_candidates_per_seed}",
                f"sample_strategy = {quote(request.strategy)}",
                f"temperature = {request.temperature}",
                "unique_molecules = true",
                "randomize_smiles = true",
                "",
            ]
        )

    @staticmethod
    def _read_output(
        output_path: Path,
        request: GenerationJob,
    ) -> list[GeneratedCandidate]:
        seeds_by_smiles = {
            representation: seed
            for seed in request.seeds
            for representation in {
                seed.smiles,
                ReinventGenerator._canonical_smiles(seed.smiles),
            }
        }
        molecules: list[GeneratedCandidate] = []
        with output_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            required = {"SMILES", "Input_SMILES"}
            if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                raise ReinventError(
                    "Unexpected REINVENT4 CSV columns: "
                    f"{reader.fieldnames!r}; expected at least {sorted(required)!r}"
                )
            for row in reader:
                smiles = row["SMILES"].strip()
                parent_smiles = row["Input_SMILES"].strip()
                if not smiles or not parent_smiles:
                    continue
                parent = seeds_by_smiles.get(parent_smiles)
                parent_id = (
                    parent.id if parent and parent.id else molecule_id(parent_smiles)
                )
                molecules.append(
                    GeneratedCandidate(
                        smiles=smiles,
                        id=molecule_id(smiles),
                        parent_smiles=parent_smiles,
                        parent_id=parent_id,
                        tanimoto=ReinventGenerator._optional_float(row.get("Tanimoto")),
                        nll=ReinventGenerator._optional_float(row.get("NLL")),
                    )
                )
        return molecules

    @staticmethod
    def _canonical_smiles(smiles: str) -> str:
        """Match REINVENT's canonicalized Input_SMILES back to an API seed."""
        try:
            from rdkit import Chem
        except ImportError:
            return smiles
        molecule = Chem.MolFromSmiles(smiles)
        return Chem.MolToSmiles(molecule) if molecule is not None else smiles

    @staticmethod
    def _optional_float(value: str | None) -> float | None:
        if value is None or not value.strip():
            return None
        try:
            parsed = float(value)
        except ValueError:
            return None
        return None if parsed < 0 and value.strip() == "-1" else parsed

    @staticmethod
    def _failure_details(
        completed: subprocess.CompletedProcess[str], log_path: Path
    ) -> str:
        parts = [completed.stderr.strip(), completed.stdout.strip()]
        if log_path.is_file():
            parts.append(
                log_path.read_text(encoding="utf-8", errors="replace")[-4_000:]
            )
        details = "\n".join(part for part in parts if part)
        return details[-4_000:] if details else f"exit code {completed.returncode}"
