from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rdkit import Chem
from rdkit.Chem import BRICS, Crippen, Descriptors, Lipinski, rdMolDescriptors
from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams

from libs.schemas import Molecule

from .models import PhyschemParameters

WARHEAD_SMARTS = {
    "acyl_halide": "[CX3](=[OX1])[F,Cl,Br,I]",
    "sulfonyl_halide": "[SX4](=[OX1])(=[OX1])[F,Cl,Br,I]",
    "isocyanate": "[NX2]=[CX2]=[OX1]",
    "isothiocyanate": "[NX2]=[CX2]=[SX1]",
    "epoxide": "[OX2r3]1[CX4r3][CX4r3]1",
    "aziridine": "[NX3r3]1[CX4r3][CX4r3]1",
    "michael_acceptor": "[C,c]=[C,c]-[C,S](=[O,S])",
    "aldehyde": "[CX3H1](=O)[#6]",
}
BASIC_SITE_SMARTS = {
    "aliphatic_amine": "[NX3;H0,H1,H2;!$(N-C=O);!$(N-S=O)]",
    "amidine": "[NX3][CX3](=[NX2])",
    "guanidine": "[NX3][CX3](=[NX2])[NX3]",
}


@dataclass(frozen=True)
class PhyschemScore:
    values: dict[str, float]
    details: dict[str, Any]
    passed: bool
    error: str | None = None


def _catalog(*kinds: object) -> FilterCatalog:
    parameters = FilterCatalogParams()
    for kind in kinds:
        parameters.AddCatalog(kind)
    return FilterCatalog(parameters)


class PhyschemScorer:
    def __init__(self) -> None:
        catalogs = FilterCatalogParams.FilterCatalogs
        self.pains = _catalog(catalogs.PAINS_A, catalogs.PAINS_B, catalogs.PAINS_C)
        self.brenk = _catalog(catalogs.BRENK)

    def score_batch(
        self, molecules: list[Molecule], parameters: PhyschemParameters
    ) -> list[PhyschemScore]:
        blocks = self._building_blocks(parameters.building_blocks_path)
        routes = self._route_results(parameters.route_results_path)
        return [
            self._score(molecule, parameters, blocks, routes)
            for molecule in molecules
        ]

    @staticmethod
    def _building_blocks(path: str | None) -> list[Chem.Mol]:
        if path is None:
            return []
        source = Path(path)
        if not source.is_file():
            raise ValueError(f"building-block catalog does not exist: {source}")
        molecules = []
        for raw in source.read_text(encoding="utf-8").splitlines():
            smiles = raw.strip().split()[0] if raw.strip() else ""
            molecule = Chem.MolFromSmiles(smiles)
            if molecule is not None:
                molecules.append(molecule)
        if not molecules:
            raise ValueError("building-block catalog contains no valid SMILES")
        return molecules

    @staticmethod
    def _route_results(path: str | None) -> dict[str, dict[str, Any]]:
        if path is None:
            return {}
        source = Path(path)
        if not source.is_file():
            raise ValueError(f"route result file does not exist: {source}")
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("route result file must contain an object keyed by molecule")
        return {
            str(key): value for key, value in data.items() if isinstance(value, dict)
        }

    def _score(
        self,
        molecule: Molecule,
        parameters: PhyschemParameters,
        blocks: list[Chem.Mol],
        routes: dict[str, dict[str, Any]],
    ) -> PhyschemScore:
        try:
            rd_molecule = Chem.MolFromSmiles(molecule.smiles)
            if rd_molecule is None:
                raise ValueError("RDKit could not parse SMILES")
            values: dict[str, float] = {
                "molecular_weight": float(Descriptors.MolWt(rd_molecule)),
                "clogp": float(Crippen.MolLogP(rd_molecule)),
                "hbond_donors": float(Lipinski.NumHDonors(rd_molecule)),
                "hbond_acceptors": float(Lipinski.NumHAcceptors(rd_molecule)),
                "tpsa": float(rdMolDescriptors.CalcTPSA(rd_molecule)),
                "rotatable_bonds": float(Lipinski.NumRotatableBonds(rd_molecule)),
                "formal_charge": float(Chem.GetFormalCharge(rd_molecule)),
                "heavy_atom_count": float(rd_molecule.GetNumHeavyAtoms()),
            }
            pains = [entry.GetDescription() for entry in self.pains.GetMatches(rd_molecule)]
            brenk = [entry.GetDescription() for entry in self.brenk.GetMatches(rd_molecule)]
            warheads = self._matches(
                rd_molecule,
                {**WARHEAD_SMARTS, **{
                    f"custom_{index}": smarts
                    for index, smarts in enumerate(parameters.additional_warhead_smarts)
                }},
            )
            basic_sites = self._matches(rd_molecule, BASIC_SITE_SMARTS)
            predicted_pka = getattr(
                molecule, parameters.predicted_basic_pka_field, None
            )
            pka_available = predicted_pka is not None
            pka_pass = not parameters.require_pka_prediction or pka_available
            if pka_available:
                predicted_pka = float(predicted_pka)
                if parameters.min_basic_pka is not None:
                    pka_pass &= predicted_pka >= parameters.min_basic_pka
                if parameters.max_basic_pka is not None:
                    pka_pass &= predicted_pka <= parameters.max_basic_pka

            route = routes.get(molecule.id or "") or routes.get(molecule.smiles) or {}
            route_confidence = float(route.get("route_confidence", 0.0))
            route_steps = int(route.get("route_steps", 0))
            external_route_pass = (
                route_confidence >= parameters.min_route_confidence
                and 0 < route_steps <= parameters.max_route_steps
            )
            synthons = sorted(BRICS.BRICSDecompose(rd_molecule))
            building_block_pass = bool(blocks) and all(
                self._synthon_available(smiles, blocks) for smiles in synthons
            )
            template_hits = [
                template
                for template in parameters.reaction_templates
                if self._product_matches(rd_molecule, template)
            ]
            retrosynthesis_pass = (
                external_route_pass or building_block_pass or bool(template_hits)
            )
            if not parameters.require_retrosynthesis:
                retrosynthesis_pass = True

            lipinski_pass = (
                values["molecular_weight"] <= parameters.max_molecular_weight
                and values["clogp"] <= parameters.max_clogp
                and values["hbond_donors"] <= parameters.max_hbond_donors
                and values["hbond_acceptors"] <= parameters.max_hbond_acceptors
            )
            veber_pass = (
                values["tpsa"] <= parameters.max_tpsa
                and values["rotatable_bonds"] <= parameters.max_rotatable_bonds
            )
            charge_pass = (
                parameters.min_formal_charge
                <= values["formal_charge"]
                <= parameters.max_formal_charge
            )
            heavy_atom_pass = (
                parameters.min_heavy_atoms
                <= values["heavy_atom_count"]
                <= parameters.max_heavy_atoms
            )
            liability_pass = (
                not pains
                and not brenk
                and (parameters.allow_covalent_warheads or not warheads)
            )
            passed = all(
                (
                    lipinski_pass,
                    veber_pass,
                    charge_pass,
                    heavy_atom_pass,
                    liability_pass,
                    pka_pass,
                    retrosynthesis_pass,
                )
            )
            values.update(
                {
                    "lipinski_pass": float(lipinski_pass),
                    "veber_pass": float(veber_pass),
                    "charge_pass": float(charge_pass),
                    "heavy_atom_pass": float(heavy_atom_pass),
                    "pains_count": float(len(pains)),
                    "brenk_count": float(len(brenk)),
                    "warhead_count": float(len(warheads)),
                    "basic_site_count": float(len(basic_sites)),
                    "pka_prediction_available": float(pka_available),
                    "pka_pass": float(pka_pass),
                    "route_confidence": route_confidence,
                    "route_steps": float(route_steps),
                    "retrosynthesis_pass": float(retrosynthesis_pass),
                }
            )
            if pka_available:
                values["predicted_basic_pka"] = predicted_pka
            return PhyschemScore(
                values=values,
                details={
                    "pains_alerts": pains,
                    "brenk_alerts": brenk,
                    "warhead_alerts": warheads,
                    "basic_site_alerts": basic_sites,
                    "pka_check_mode": "predicted" if pka_available else "structural_only",
                    "brics_synthons": synthons,
                    "building_block_pass": building_block_pass,
                    "reaction_template_hits": template_hits,
                    "shared_intermediate_id": route.get("shared_intermediate_id"),
                },
                passed=passed,
            )
        except Exception as exc:
            return PhyschemScore(
                values={"scoring_succeeded": 0.0},
                details={},
                passed=False,
                error=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _matches(molecule: Chem.Mol, patterns: dict[str, str]) -> list[str]:
        matches = []
        for name, smarts in patterns.items():
            query = Chem.MolFromSmarts(smarts)
            if query is None:
                raise ValueError(f"invalid SMARTS for {name}: {smarts}")
            if molecule.HasSubstructMatch(query):
                matches.append(name)
        return matches

    @staticmethod
    def _synthon_available(smiles: str, blocks: list[Chem.Mol]) -> bool:
        synthon = Chem.MolFromSmiles(smiles)
        if synthon is None:
            return False
        query = Chem.DeleteSubstructs(synthon, Chem.MolFromSmarts("[#0]"))
        try:
            Chem.SanitizeMol(query)
        except Exception:
            return False
        return query.GetNumHeavyAtoms() == 0 or any(
            block.HasSubstructMatch(query) for block in blocks
        )

    @staticmethod
    def _product_matches(molecule: Chem.Mol, reaction_smarts: str) -> bool:
        if ">>" not in reaction_smarts:
            raise ValueError(f"reaction SMARTS has no product side: {reaction_smarts}")
        product = Chem.MolFromSmarts(reaction_smarts.split(">>", 1)[1])
        if product is None:
            raise ValueError(f"invalid reaction SMARTS: {reaction_smarts}")
        return molecule.HasSubstructMatch(product)
