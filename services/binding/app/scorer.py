from __future__ import annotations

import hashlib
import math
import threading
from dataclasses import dataclass
from pathlib import Path
import prolif as plf
from meeko import MoleculePreparation, PDBQTMolecule, PDBQTWriterLegacy, RDKitMolCreate
from rdkit import Chem
from rdkit.Chem import AllChem, Crippen
from vina import Vina

from libs.schemas import Molecule

from .models import BindingParameters

GAS_CONSTANT_KCAL = 0.00198720425864083


class TargetConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class BindingResult:
    values: dict[str, float]
    interactions: tuple[str, ...]
    passed: bool
    error: str | None = None


@dataclass
class _DockingContext:
    vina: Vina
    protein: plf.Molecule
    lock: threading.Lock


def _logistic(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)


def _interaction_fraction(
    observed: set[str], parameters: BindingParameters
) -> tuple[float, bool]:
    requirements = parameters.critical_interactions
    if not requirements:
        return 1.0, True
    matches = [
        any(
            f"{kind}:{requirement.residue}" in observed
            for kind in requirement.interaction_types
        )
        for requirement in requirements
    ]
    fraction = sum(matches) / len(matches)
    passed = all(matches) if parameters.critical_mode == "all" else any(matches)
    return fraction, passed


def evaluate_metrics(
    *,
    vina_score: float,
    heavy_atom_count: int,
    clogp: float,
    interactions: set[str],
    parameters: BindingParameters,
) -> tuple[dict[str, float], bool]:
    ligand_efficiency = -vina_score / heavy_atom_count
    pkd_proxy = -vina_score / (
        GAS_CONSTANT_KCAL * parameters.temperature_kelvin * math.log(10.0)
    )
    lipe_proxy = pkd_proxy - clogp
    critical_fraction, interactions_passed = _interaction_fraction(
        interactions, parameters
    )

    desirabilities = [
        _logistic(parameters.max_vina_score - vina_score),
        _logistic((ligand_efficiency - parameters.min_ligand_efficiency) / 0.05),
    ]
    if parameters.min_lipe_proxy is not None:
        desirabilities.append(_logistic(lipe_proxy - parameters.min_lipe_proxy))
    if parameters.critical_interactions:
        desirabilities.append(max(critical_fraction, 1e-12))
    binding_desirability = math.prod(desirabilities) ** (1.0 / len(desirabilities))

    passed = (
        vina_score <= parameters.max_vina_score
        and ligand_efficiency >= parameters.min_ligand_efficiency
        and (
            parameters.min_lipe_proxy is None or lipe_proxy >= parameters.min_lipe_proxy
        )
        and interactions_passed
    )
    values = {
        "docking_succeeded": 1.0,
        "vina_score": vina_score,
        "heavy_atom_count": float(heavy_atom_count),
        "clogp": clogp,
        "vina_ligand_efficiency": ligand_efficiency,
        "vina_pkd_proxy": pkd_proxy,
        "vina_lipe_proxy": lipe_proxy,
        "interaction_count": float(len(interactions)),
        "critical_interaction_fraction": critical_fraction,
        "binding_desirability": binding_desirability,
    }
    return values, passed


class BindingScorer:
    def __init__(self) -> None:
        self._contexts: dict[str, _DockingContext] = {}
        self._contexts_lock = threading.Lock()

    def score_batch(
        self, molecules: list[Molecule], parameters: BindingParameters
    ) -> list[BindingResult]:
        context = self._context(parameters)
        results: list[BindingResult] = []
        with context.lock:
            for molecule in molecules:
                try:
                    results.append(self._score_molecule(molecule, parameters, context))
                except Exception as exc:  # reject one bad molecule, not the batch
                    results.append(
                        BindingResult(
                            values={
                                "docking_succeeded": 0.0,
                                "binding_desirability": 0.0,
                            },
                            interactions=(),
                            passed=False,
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    )
        return results

    def _context(self, parameters: BindingParameters) -> _DockingContext:
        receptor_pdbqt = Path(parameters.receptor_pdbqt)
        receptor_pdb = Path(parameters.receptor_pdb)
        for label, path in (
            ("receptor_pdbqt", receptor_pdbqt),
            ("receptor_pdb", receptor_pdb),
        ):
            if not path.is_file():
                raise TargetConfigurationError(f"{label} does not exist: {path}")

        signature = hashlib.sha256(
            repr(
                (
                    str(receptor_pdbqt.resolve()),
                    str(receptor_pdb.resolve()),
                    parameters.box_center,
                    parameters.box_size,
                    parameters.cpu,
                    parameters.random_seed,
                )
            ).encode()
        ).hexdigest()
        with self._contexts_lock:
            if signature not in self._contexts:
                vina = Vina(
                    sf_name="vina",
                    cpu=parameters.cpu,
                    seed=parameters.random_seed,
                    verbosity=0,
                )
                vina.set_receptor(str(receptor_pdbqt))
                vina.compute_vina_maps(
                    center=list(parameters.box_center),
                    box_size=list(parameters.box_size),
                )
                protein_rdkit = Chem.MolFromPDBFile(
                    str(receptor_pdb), removeHs=False, sanitize=False
                )
                if protein_rdkit is None:
                    raise TargetConfigurationError(
                        f"RDKit could not read receptor protein: {receptor_pdb}"
                    )
                protein = plf.Molecule.from_rdkit(protein_rdkit)
                self._contexts[signature] = _DockingContext(
                    vina=vina,
                    protein=protein,
                    lock=threading.Lock(),
                )
            return self._contexts[signature]

    def _score_molecule(
        self,
        molecule: Molecule,
        parameters: BindingParameters,
        context: _DockingContext,
    ) -> BindingResult:
        ligand = self._prepare_ligand(molecule)
        preparation = MoleculePreparation()
        setups = preparation.prepare(ligand)
        if not setups:
            raise ValueError("Meeko produced no ligand setup")
        pdbqt, ok, error = PDBQTWriterLegacy.write_string(setups[0])
        if not ok:
            raise ValueError(f"Meeko could not write ligand PDBQT: {error}")

        context.vina.set_ligand_from_string(pdbqt)
        context.vina.dock(
            exhaustiveness=parameters.exhaustiveness,
            n_poses=parameters.num_poses,
        )
        energies = context.vina.energies(n_poses=parameters.num_poses)
        if len(energies) == 0:
            raise ValueError("Vina returned no poses")
        vina_score = float(energies[0][0])
        pose_pdbqt = context.vina.poses(
            n_poses=parameters.num_poses,
            energy_range=parameters.energy_range,
        )
        interactions = self._fingerprint(
            pose_pdbqt,
            context.protein,
            parameters.interaction_types,
        )
        heavy_atom_count = ligand.GetNumHeavyAtoms()
        if heavy_atom_count == 0:
            raise ValueError("ligand contains no heavy atoms")
        clogp = float(Crippen.MolLogP(Chem.RemoveHs(ligand)))
        values, passed = evaluate_metrics(
            vina_score=vina_score,
            heavy_atom_count=heavy_atom_count,
            clogp=clogp,
            interactions=interactions,
            parameters=parameters,
        )
        return BindingResult(
            values=values,
            interactions=tuple(sorted(interactions)),
            passed=passed,
        )

    @staticmethod
    def _prepare_ligand(molecule: Molecule) -> Chem.Mol:
        ligand = Chem.MolFromSmiles(molecule.smiles)
        if ligand is None:
            raise ValueError("RDKit could not parse SMILES")
        ligand = Chem.AddHs(ligand)
        embedding = AllChem.ETKDGv3()
        stable_seed = int(hashlib.sha256(molecule.smiles.encode()).hexdigest()[:8], 16)
        embedding.randomSeed = stable_seed & 0x7FFFFFFF
        if AllChem.EmbedMolecule(ligand, embedding) != 0:
            raise ValueError("RDKit could not generate a 3D conformer")
        if AllChem.MMFFHasAllMoleculeParams(ligand):
            AllChem.MMFFOptimizeMolecule(ligand, maxIters=500)
        else:
            AllChem.UFFOptimizeMolecule(ligand, maxIters=500)
        return ligand

    @staticmethod
    def _fingerprint(
        pose_pdbqt: str,
        protein: plf.Molecule,
        interaction_types: list[str] | None,
    ) -> set[str]:
        pdbqt_molecule = PDBQTMolecule(pose_pdbqt)
        pose_molecules = RDKitMolCreate.from_pdbqt_mol(pdbqt_molecule)
        poses = [
            plf.Molecule.from_rdkit(pose) for pose in pose_molecules if pose is not None
        ]
        if not poses:
            raise ValueError("Meeko could not reconstruct Vina poses")
        fingerprint = plf.Fingerprint(interactions=interaction_types)
        fingerprint.run_from_iterable(poses, protein, n_jobs=1)
        dataframe = fingerprint.to_dataframe()
        observed: set[str] = set()
        for column in dataframe.columns:
            if bool(dataframe[column].any()):
                _, residue, interaction = column
                observed.add(f"{interaction}:{residue}")
        return observed
